"""共用步驟 `the outcome is <OUTCOME>` 的錯誤字串規則（D-093）。

規則：
- LOCKED：只接受自己那一句（「密碼錯誤次數過多，請在 15 分鐘後再試」）。
- 其他拒絕類別：message 必須是 spec/appendix-b-fields.md「錯誤訊息」欄逐字存在的字串，或為 null。

這是從「LOCKED 以外一律只接受 null」放寬成「也接受附錄 B 的字串」；null 仍然可以。
所以這裡的重點是反向測試：不在附錄 B 的字串（多一個字、少一個字、換一句）必須失敗，
否則步驟會變成「任何字串都通過」，等於把 AGENTS.md 不可違反 #5 的「完整錯誤字串」拿掉。

這裡直接呼叫步驟背後的函式，因為「該失敗的時候會失敗」無法用一個必須通過的 Gherkin scenario 表達
（與 test_nothing_else_written.py 相同）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core import audit
from app.core import session as session_core
from app.core.actor import Actor, Role
from app.main import create_app
from app.core.outcomes import Outcome
from tests.steps.common import outcome as step
from tests.steps.common.spec_tables import outcome_http_table
from tests.steps.common.steps import Recorder


class _Response:
    def __init__(self, status_code: int, body: dict | None):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _reject(db, outcome: str, message: str | None, *, status: int | None = None) -> Recorder:
    """假裝動作回了這個拒絕（沒有寫任何資料），回傳 recorder。"""
    r = Recorder(db)
    r.perform(lambda: _Response(status if status is not None else outcome_http_table()[outcome], {"outcome": outcome, "message": message}))
    return r


def _check(db, recorder: Recorder, outcome: str, client=None) -> None:
    """呼叫 `the outcome is <OUTCOME>` 背後的函式。非 FORBIDDEN 不看 client；FORBIDDEN 要有已登入的 client（D-095）。"""
    step._outcome_rejected(recorder, client if client is not None else TestClient(create_app()), db, outcome)


# ───────── 附錄 B 字串清單是從 spec 解析出來的 ─────────


def test_appendix_b_messages_are_parsed_from_the_spec():
    messages = step.appendix_b_messages()
    # 單句、多句（<br>）、含內層「」的字串都要解析正確
    assert "回報日期須為今天或往前 30 天內，不可選擇未來日期" in messages
    assert "工項數量須為 0 到 999.9，最小單位 0.1" in messages
    assert "每日最多只能送出 3 筆回報" in messages
    assert "密碼錯誤次數過多，請在 15 分鐘後再試" in messages
    assert "請上傳 xlsx 或 csv 檔，且標題列須含「材料編號」與「實領量」" in messages
    # 只剝最外層的「」：沒有字串以「開頭（內層的「」，如上面那句結尾的」，要保留）；「—」與欄位標題不是字串
    assert not any(m.startswith("「") for m in messages)
    assert "—" not in messages and "錯誤訊息" not in messages
    assert len(messages) > 50


# ───────── 會通過的 ─────────


@pytest.mark.parametrize(
    "outcome, message",
    [
        ("INVALID", "回報日期須為今天或往前 30 天內，不可選擇未來日期"),
        ("INVALID", "工項數量須為 0 到 999.9，最小單位 0.1"),
        ("INVALID", None),  # 規格沒有為該情況寫字串（例如 RPT-R01 的工項組以外）
        ("CONFLICT", "每日最多只能送出 3 筆回報"),
        ("CONFLICT", None),
        ("UNAUTHENTICATED", None),
        ("LOCKED", "密碼錯誤次數過多，請在 15 分鐘後再試"),
    ],
)
def test_accepts_an_appendix_b_message_or_null(db, outcome, message):
    _check(db, _reject(db, outcome, message), outcome)


# ───────── 會失敗的（反向測試）─────────


@pytest.mark.parametrize(
    "message",
    [
        "回報日期須為今天或往前 30 天內，不可選擇未來日期。",  # 多一個字
        "回報日期須為今天或往前 30 天內，不可選擇未來日期 ",  # 多一個空白
        "回報日期須為今天或往前 30 天內，不可選擇未來日期嗎",  # 多一個字
        "回報日期須為今天或往前 30 天內，不可選擇未來日",  # 少一個字
        "每日最多只能送出 3 筆回報。",
        "日期錯誤",  # 規格裡沒有的句子
        "",  # 空字串不是 null，也不在附錄 B
        "錯誤訊息",
        "—",
    ],
)
@pytest.mark.parametrize("outcome", ["INVALID", "CONFLICT", "FORBIDDEN"])
def test_rejects_a_message_that_is_not_in_appendix_b(db, outcome, message):
    with pytest.raises(AssertionError):
        _check(db, _reject(db, outcome, message), outcome)


@pytest.mark.parametrize(
    "message",
    [
        None,
        "密碼錯誤，請重試",  # 附錄 B 的另一句（登入密碼的 UNAUTHENTICATED）
        "每日最多只能送出 3 筆回報",
        "密碼錯誤次數過多，請在 15 分鐘後再試。",
        "",
    ],
)
def test_locked_accepts_only_its_own_sentence(db, message):
    with pytest.raises(AssertionError):
        _check(db, _reject(db, "LOCKED", message), "LOCKED")


def test_wrong_http_status_or_outcome_still_fails(db):
    # 字串對，但結果類別對不上 HTTP status／回應裡的類別：仍然失敗
    with pytest.raises(AssertionError):
        _check(db, _reject(db, "INVALID", "每日最多只能送出 3 筆回報", status=409), "INVALID")
    with pytest.raises(AssertionError):
        _check(db, _reject(db, "CONFLICT", "每日最多只能送出 3 筆回報"), "INVALID")


def test_a_non_json_response_fails_instead_of_passing(db):
    r = Recorder(db)
    r.perform(lambda: _Response(422, None))
    with pytest.raises(Exception):
        _check(db, r, "INVALID")


def test_data_changes_still_fail_the_step(db):
    # check_nothing_written 照舊：字串合法，但動作寫了資料，一樣失敗
    r = Recorder(db)

    def action():
        db.execute("insert into yc_v3.accounts(name, role, zone) values ('Extra','USER','WEST')")
        db.commit()
        return _Response(422, {"outcome": "INVALID", "message": "回報日期須為今天或往前 30 天內，不可選擇未來日期"})

    r.perform(action)
    with pytest.raises(AssertionError):
        _check(db, r, "INVALID")


def test_every_outcome_class_is_known():
    assert {o.value for o in Outcome} == set(outcome_http_table())


# ───────── D-095：FORBIDDEN 的資料斷言 ─────────
#
# 規格規定每個 FORBIDDEN 都寫 ACCESS_DENIED（spec/README.md 結果類別表、AUD-R03），所以 `the outcome is FORBIDDEN`
# 要求「恰好新增 1 列 ACCESS_DENIED、行為者是被拒絕的人，其他資料表完全不變」；其他類別仍是「完全沒有變動」。


def _wen_client(db) -> tuple[TestClient, Actor]:
    from tests.steps.common.session import SESSION_COOKIE, sign_in_with_correct_password

    client = TestClient(create_app())
    assert sign_in_with_correct_password(client, db, "Wen").status_code == 303
    actor = session_core.actor_for_token(db, client.cookies.get(SESSION_COOKIE))
    db.rollback()
    return client, actor


def _actor(db, name: str) -> Actor:
    row = db.execute("select id, role from yc_v3.accounts where name = %s", (name,)).fetchone()
    db.rollback()
    return Actor(id=row[0], name=name, role=Role(row[1]))


def _forbidden(db, client, *writes) -> Recorder:
    """假裝動作回了 FORBIDDEN，並依 `writes`（每個是 callable(conn)）寫資料。"""
    r = Recorder(db)

    def action():
        for write in writes:
            write(db)
        db.commit()
        return _Response(403, {"outcome": "FORBIDDEN", "message": None})

    r.perform(action)
    return r


def _denied(db, actor_name: str = "Wen", type_: str = "ACCESS_DENIED"):
    actor = _actor(db, actor_name)  # 先查（_actor 會 rollback，不能夾在待提交的寫入中間）
    return lambda conn: audit.write(actor, type_, "嘗試執行但被拒絕：edit a report", conn=conn)


def test_forbidden_passes_with_exactly_one_access_denied_by_the_rejected_person(db):
    client, _ = _wen_client(db)
    _check(db, _forbidden(db, client, _denied(db)), "FORBIDDEN", client)


def test_forbidden_claims_the_access_denied_row_for_nothing_else_is_written(db):
    from tests.steps.common.steps import check_nothing_else_written

    client, _ = _wen_client(db)
    r = _forbidden(db, client, _denied(db))
    _check(db, r, "FORBIDDEN", client)
    check_nothing_else_written(r)  # ACCESS_DENIED 已被斷言過，不算「其他寫入」


def test_forbidden_fails_when_no_access_denied_is_written(db):
    client, _ = _wen_client(db)
    with pytest.raises(AssertionError, match="恰好新增 1 列稽核"):
        _check(db, _forbidden(db, client), "FORBIDDEN", client)


def test_forbidden_fails_when_two_audit_rows_are_written(db):
    client, _ = _wen_client(db)
    with pytest.raises(AssertionError, match="恰好新增 1 列稽核"):
        _check(db, _forbidden(db, client, _denied(db), _denied(db)), "FORBIDDEN", client)


def test_forbidden_fails_when_the_actor_is_not_the_rejected_person(db):
    client, _ = _wen_client(db)
    with pytest.raises(AssertionError, match="ACCESS_DENIED"):
        _check(db, _forbidden(db, client, _denied(db, "Wei")), "FORBIDDEN", client)


def test_forbidden_fails_when_the_audit_row_is_not_access_denied(db):
    client, _ = _wen_client(db)
    with pytest.raises(AssertionError, match="ACCESS_DENIED"):
        _check(db, _forbidden(db, client, _denied(db, type_="REPORT_UPDATE")), "FORBIDDEN", client)


def test_forbidden_fails_when_another_table_changes(db):
    client, _ = _wen_client(db)
    extra = lambda conn: conn.execute("insert into yc_v3.accounts(name, role, zone) values ('Extra','USER','WEST')")  # noqa: E731
    with pytest.raises(AssertionError, match="其他資料表"):
        _check(db, _forbidden(db, client, _denied(db), extra), "FORBIDDEN", client)


def test_forbidden_fails_when_the_request_had_no_session(db):
    anonymous = TestClient(create_app())
    with pytest.raises(AssertionError, match="已登入"):
        _check(db, _forbidden(db, anonymous, _denied(db)), "FORBIDDEN", anonymous)


def test_forbidden_with_a_message_outside_appendix_b_still_fails(db):
    client, _ = _wen_client(db)
    r = Recorder(db)
    r.perform(lambda: (_denied(db)(db), db.commit(), _Response(403, {"outcome": "FORBIDDEN", "message": "日期錯誤"}))[2])
    with pytest.raises(AssertionError):
        _check(db, r, "FORBIDDEN", client)


@pytest.mark.parametrize("outcome", ["INVALID", "CONFLICT", "UNAUTHENTICATED"])
def test_other_outcomes_still_require_nothing_to_be_written(db, outcome):
    """D-095 只放寬 FORBIDDEN：其他類別寫了 ACCESS_DENIED 一樣失敗。"""
    client, _ = _wen_client(db)
    r = Recorder(db)

    def action():
        _denied(db)(db)
        db.commit()
        return _Response(outcome_http_table()[outcome], {"outcome": outcome, "message": None})

    r.perform(action)
    with pytest.raises(AssertionError):
        _check(db, r, outcome, client)
