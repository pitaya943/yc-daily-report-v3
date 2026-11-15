"""共用步驟的測試。

兩部分：
1. common_steps.feature：步驟對真的 HTTP 請求（含應用程式內的 handler 與資料庫）有效。
2. 反向測試：步驟在「該失敗的時候」真的會失敗——否則「永遠通過」的步驟毫無價值。
"""
import pytest
from fastapi import APIRouter
from pytest_bdd import parsers, scenarios, when

from app.core import audit
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Actor, Role, Rule, authorize
from app.main import create_app
from tests.steps.common import steps as common
from tests.steps.common.steps import Recorder, take_snapshot

scenarios("../../tests/steps/common/common_steps.feature")

# ───────── 測試專用路由（只存在於這個測試檔建立的 app，不是產品程式）─────────
_router = APIRouter()


def _actor(name: str) -> Actor:
    from app.core.db import connect

    with connect() as c:
        i, role = c.execute("select id, role from yc_v3.accounts where name = %s", (name,)).fetchone()
    return Actor(id=i, name=name, role=Role(role))


@_router.post("/__t__/fourth-report")
def _fourth():
    raise OutcomeError(Outcome.CONFLICT, "每日最多只能送出 3 筆回報")


@_router.post("/__t__/protected")
def _protected():
    authorize(None, "protected action", Rule(roles={Role.USER}))


@_router.post("/__t__/confirm/{who}")
def _confirm(who: str):
    authorize(_actor(who), "confirm a report", Rule(roles={Role.ADMIN}))
    audit.write(_actor(who), "REPORT_CONFIRM", "確認回報")
    return {"ok": True}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    app = create_app()
    app.include_router(_router)
    return TestClient(app, raise_server_exceptions=False)


@when("a USER submits a fourth report on the same day")
def _w1(recorder, client):
    recorder.perform(lambda: client.post("/__t__/fourth-report"))


@when("a visitor requests any protected action")
def _w2(recorder, client):
    recorder.perform(lambda: client.post("/__t__/protected"))


@when(parsers.parse('"{who}" confirms a report directly'))
def _w3(recorder, client, who):
    recorder.perform(lambda: client.post(f"/__t__/confirm/{who}"))


# ───────── 反向測試：該失敗時會失敗 ─────────


def _recorder_after(db, mutate, response):
    r = Recorder(db)
    r.perform(lambda: (mutate(), response)[1])
    return r


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def test_nothing_written_detects_an_insert_the_response_hides(db):
    """回應看起來完全正常的拒絕，但動作偷偷寫了一個帳戶：步驟必須失敗（完成條件 5）。"""

    def sneaky():
        db.execute("insert into yc_v3.accounts(name, role, zone) values ('Sneaky','USER','WEST')")
        db.commit()

    r = _recorder_after(db, sneaky, _Resp(409, {"outcome": "CONFLICT", "message": "m"}))
    with pytest.raises(AssertionError, match="Sneaky"):
        common.check_nothing_written(r)


def test_nothing_written_detects_update_and_delete(db):
    def upd():
        db.execute("update yc_v3.accounts set zone = 'SOUTH' where name = 'Wen'")
        db.commit()

    with pytest.raises(AssertionError):
        common.check_nothing_written(_recorder_after(db, upd, _Resp(200, {})))

    def dele():
        db.execute("delete from yc_v3.accounts where name = 'Old'")
        db.commit()

    with pytest.raises(AssertionError):
        common.check_nothing_written(_recorder_after(db, dele, _Resp(200, {})))


def test_nothing_written_passes_when_the_database_is_identical(db):
    common.check_nothing_written(_recorder_after(db, lambda: None, _Resp(409, {})))


def test_nothing_written_ignores_a_write_that_was_rolled_back(db):
    def rolled_back():
        db.execute("insert into yc_v3.accounts(name, role, zone) values ('Ghost','USER','WEST')")
        db.rollback()

    common.check_nothing_written(_recorder_after(db, rolled_back, _Resp(409, {})))


def test_nothing_written_requires_the_action_to_go_through_the_recorder(db):
    with pytest.raises(AssertionError, match="recorder.perform"):
        common.check_nothing_written(Recorder(db))


def test_rejection_step_checks_class_status_and_the_full_message(db):
    ok = _recorder_after(db, lambda: None, _Resp(409, {"outcome": "CONFLICT", "message": "每日最多只能送出 3 筆回報"}))
    common.check_rejected(ok, "CONFLICT", "每日最多只能送出 3 筆回報")
    # BLOCKED 與 CONFLICT 同為 409：status 相同、只有類別不同，也要抓得到
    same_status_other_class = _recorder_after(db, lambda: None, _Resp(409, {"outcome": "BLOCKED", "message": "x"}))
    with pytest.raises(AssertionError, match="結果類別"):
        common.check_rejected(same_status_other_class, "CONFLICT", "x")
    wrong_status = _recorder_after(db, lambda: None, _Resp(400, {"outcome": "CONFLICT", "message": "x"}))
    with pytest.raises(AssertionError, match="HTTP status"):  # status 錯
        common.check_rejected(wrong_status, "CONFLICT", "x")
    with pytest.raises(AssertionError, match="錯誤字串"):  # 字串只差一個字也不行
        common.check_rejected(ok, "CONFLICT", "每日最多只能送出 4 筆回報")
    with pytest.raises(AssertionError, match="錯誤字串"):  # 前綴也不行（不是 contains）
        common.check_rejected(ok, "CONFLICT", "每日最多只能送出 3 筆")


def test_snapshot_covers_every_table_except_the_migration_ledger(db):
    snap = take_snapshot(db)
    assert "accounts" in snap and "audit_log" in snap and "schema_migrations" not in snap
