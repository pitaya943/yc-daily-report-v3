"""共用步驟 `the outcome is <outcome> with message "<message>"` 的反向測試（D-117 S1，T-305 完成條件 8）。

規則（見 tests/steps/common/outcome.py 的 docstring）：
- `accepted`：message 必須是空字串，HTTP 200。
- 其他類別：message 逐字比對（空字串 = 規格沒寫字串 = 回應的 message 為 null）；資料斷言同 `the outcome is X`
  （FORBIDDEN 依 D-095，其他完全不變）。

「該失敗的時候會失敗」無法用必須通過的 Gherkin scenario 表達，所以這裡直接呼叫步驟背後的函式
（與 test_outcome_messages.py、test_nothing_else_written.py 相同）。每個測試只放一個錯誤原因（pitfall #32）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_bdd.steps import step_function_context_registry

from app.core import audit
from app.core.actor import Actor, Role
from app.core.outcomes import Outcome
from app.main import create_app
from tests.steps.common import outcome as step
from tests.steps.common.spec_tables import outcome_http_table
from tests.steps.common.steps import Recorder

INVALID_MSG = "目前密碼不正確"  # 附錄 B 的一句；這裡只當作「某個固定字串」
OTHER_MSG = "兩次輸入的密碼不一致"  # 附錄 B 的另一句


class _Response:
    def __init__(self, status_code: int, body: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text or str(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _reject(db, outcome: str, message: str | None, *, status: int | None = None, writes=()) -> Recorder:
    """假裝動作回了這個拒絕，並依 `writes`（每個是 callable(conn)）寫資料。"""
    r = Recorder(db)

    def action():
        for write in writes:
            write(db)
        db.commit()
        return _Response(status if status is not None else outcome_http_table()[outcome], {"outcome": outcome, "message": message})

    r.perform(action)
    return r


def _accept(db, status: int = 200, *, body: dict | None = None, writes=()) -> Recorder:
    r = Recorder(db)

    def action():
        for write in writes:
            write(db)
        db.commit()
        return _Response(status, body)

    r.perform(action)
    return r


def _check(db, recorder: Recorder, outcome: str, message: str, client=None) -> None:
    step._outcome_with_message(recorder, client if client is not None else TestClient(create_app()), db, outcome, message)


def _insert_account(conn) -> None:
    conn.execute("insert into yc_v3.accounts(name, role, zone) values ('Extra','USER','WEST')")


def _actor(db, name: str) -> Actor:
    row = db.execute("select id, role from yc_v3.accounts where name = %s", (name,)).fetchone()
    db.rollback()
    return Actor(id=row[0], name=name, role=Role(row[1]))


def _wen_client(db) -> TestClient:
    from tests.steps.common.session import sign_in_with_correct_password

    client = TestClient(create_app())
    assert sign_in_with_correct_password(client, db, "Wen").status_code == 303
    return client


# ───────── 步驟註冊：新句子不會被 `the outcome is (?P<outcome>[A-Z_]+)` 吃掉 ─────────


def _matching_steps(line: str) -> list:
    """outcome.py 內所有 parser 比對得上這一行的步驟函式。"""
    return [
        ctx.step_func
        for ctx in step_function_context_registry.values()
        if ctx.step_func.__module__ == step.__name__ and ctx.parser.is_matching(line)
    ]


@pytest.mark.parametrize(
    "line",
    [
        'the outcome is accepted with message ""',
        'the outcome is INVALID with message "目前密碼不正確"',
        'the outcome is FORBIDDEN with message ""',
        'the outcome is LOCKED with message "密碼錯誤次數過多，請在 15 分鐘後再試"',
    ],
)
def test_the_new_sentence_matches_only_the_new_step(line):
    assert _matching_steps(line) == [step._outcome_with_message]


@pytest.mark.parametrize(
    "line, expected",
    [
        ("the outcome is accepted", step._outcome_accepted),
        ("the outcome is INVALID", step._outcome_rejected),
        ("the outcome is FORBIDDEN", step._outcome_rejected),
    ],
)
def test_the_existing_sentences_keep_their_own_steps(line, expected):
    assert _matching_steps(line) == [expected]


# ───────── 會通過的 ─────────


def test_accepted_with_an_empty_message_and_http_200_passes(db):
    _check(db, _accept(db), "accepted", "")


def test_accepted_may_write_data(db):
    # accepted 是成功：資料有變動是正常的（斷言寫了什麼是各 scenario 自己的 Then）
    _check(db, _accept(db, writes=[_insert_account]), "accepted", "")


@pytest.mark.parametrize("outcome", ["INVALID", "CONFLICT", "BLOCKED", "RATE_LIMITED", "UNAUTHENTICATED"])
def test_a_rejection_with_the_exact_message_and_no_writes_passes(db, outcome):
    _check(db, _reject(db, outcome, INVALID_MSG), outcome, INVALID_MSG)


def test_a_rejection_with_an_empty_message_expects_null(db):
    _check(db, _reject(db, "INVALID", None), "INVALID", "")


def test_forbidden_passes_with_exactly_one_access_denied_by_the_rejected_person(db):
    client = _wen_client(db)
    actor = _actor(db, "Wen")
    r = _reject(db, "FORBIDDEN", None, writes=[lambda conn: audit.write(actor, "ACCESS_DENIED", "嘗試執行但被拒絕：reset a password", conn=conn)])
    _check(db, r, "FORBIDDEN", "", client)


# ───────── 會失敗的（反向測試）─────────


@pytest.mark.parametrize(
    "expected",
    [
        INVALID_MSG + "。",  # 多一個字
        INVALID_MSG + " ",  # 多一個空白
        INVALID_MSG[:-1],  # 少一個字
        OTHER_MSG,  # 規格裡的另一句
        "",  # 回應有字串，但例子表是空的
    ],
)
def test_a_message_that_differs_from_the_response_fails(db, expected):
    with pytest.raises(AssertionError, match="錯誤字串"):
        _check(db, _reject(db, "INVALID", INVALID_MSG), "INVALID", expected)


def test_a_null_response_message_fails_when_the_example_has_a_string(db):
    with pytest.raises(AssertionError, match="錯誤字串"):
        _check(db, _reject(db, "INVALID", None), "INVALID", INVALID_MSG)


def test_the_message_is_compared_literally_not_against_appendix_b(db):
    # 兩邊一致但不在附錄 B：這句步驟只管「回應 = 例子表」，不替規格背書（D-093 的白名單屬於 `the outcome is X`）
    _check(db, _reject(db, "INVALID", "日期錯誤"), "INVALID", "日期錯誤")


def test_accepted_with_a_message_in_the_example_fails(db):
    with pytest.raises(AssertionError, match="accepted 不可帶錯誤字串"):
        _check(db, _accept(db), "accepted", INVALID_MSG)


@pytest.mark.parametrize("status", [201, 204, 303, 404, 422, 500])
def test_accepted_fails_when_the_http_status_is_not_200(db, status):
    with pytest.raises(AssertionError, match="應被接受（200）"):
        _check(db, _accept(db, status), "accepted", "")


def test_accepted_fails_when_the_response_was_a_rejection(db):
    with pytest.raises(AssertionError, match="應被接受（200）"):
        _check(db, _reject(db, "INVALID", INVALID_MSG), "accepted", "")


def test_a_rejection_that_wrote_data_fails(db):
    with pytest.raises(AssertionError, match="資料庫在動作前後不一致"):
        _check(db, _reject(db, "INVALID", INVALID_MSG, writes=[_insert_account]), "INVALID", INVALID_MSG)


def test_a_rejection_with_the_wrong_outcome_class_fails(db):
    with pytest.raises(AssertionError, match="結果類別應為"):
        # HTTP status 是 INVALID 的 422，只有回應主體的類別不同：隔離成單一原因
        _check(db, _reject(db, "CONFLICT", INVALID_MSG, status=422), "INVALID", INVALID_MSG)


def test_a_rejection_with_a_mismatching_http_status_fails(db):
    with pytest.raises(AssertionError, match="HTTP status"):
        _check(db, _reject(db, "INVALID", INVALID_MSG, status=409), "INVALID", INVALID_MSG)


def test_a_rejection_with_a_non_json_response_fails(db):
    r = Recorder(db)
    r.perform(lambda: _Response(422, None))
    with pytest.raises(Exception):
        _check(db, r, "INVALID", INVALID_MSG)


def test_an_unknown_outcome_class_fails(db):
    with pytest.raises(AssertionError, match="不是 spec/README.md 的結果類別"):
        _check(db, _reject(db, "INVALID", INVALID_MSG), "WHATEVER", INVALID_MSG)


@pytest.mark.parametrize("outcome", [o.value for o in Outcome if o is not Outcome.FORBIDDEN])
def test_every_other_class_still_fails_when_an_access_denied_row_is_written(db, outcome):
    """D-095 只放寬 FORBIDDEN：其他類別寫了 ACCESS_DENIED 一樣失敗。"""
    actor = _actor(db, "Wen")
    r = _reject(db, outcome, INVALID_MSG, writes=[lambda conn: audit.write(actor, "ACCESS_DENIED", "嘗試執行但被拒絕：x", conn=conn)])
    with pytest.raises(AssertionError, match="資料庫在動作前後不一致"):
        _check(db, r, outcome, INVALID_MSG)


def test_forbidden_fails_when_no_access_denied_is_written(db):
    client = _wen_client(db)
    with pytest.raises(AssertionError, match="恰好新增 1 列稽核"):
        _check(db, _reject(db, "FORBIDDEN", None), "FORBIDDEN", "", client)


def test_forbidden_fails_when_the_example_expects_a_string_but_the_response_is_null(db):
    client = _wen_client(db)
    actor = _actor(db, "Wen")
    r = _reject(db, "FORBIDDEN", None, writes=[lambda conn: audit.write(actor, "ACCESS_DENIED", "嘗試執行但被拒絕：x", conn=conn)])
    with pytest.raises(AssertionError, match="錯誤字串"):
        _check(db, r, "FORBIDDEN", INVALID_MSG, client)


def test_forbidden_fails_when_another_table_changes(db):
    client = _wen_client(db)
    actor = _actor(db, "Wen")
    r = _reject(
        db,
        "FORBIDDEN",
        None,
        writes=[lambda conn: audit.write(actor, "ACCESS_DENIED", "嘗試執行但被拒絕：x", conn=conn), _insert_account],
    )
    with pytest.raises(AssertionError, match="其他資料表"):
        _check(db, r, "FORBIDDEN", "", client)
