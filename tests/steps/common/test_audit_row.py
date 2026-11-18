"""`an audit row "X" is written`（D-117 S2）的反例：步驟在「該失敗的時候」真的會失敗。

每個測試只放一個錯誤原因。直接呼叫步驟背後的函式，因為「該失敗」無法用一個必須通過的 Gherkin scenario 表達
（同 test_nothing_else_written.py）。
"""
import pytest

from app.core import audit
from app.core.actor import Actor, Role
from tests.steps.common import audit_row
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_nothing_else_written


def _actor(db, name: str) -> Actor:
    i, role = db.execute("select id, role from yc_v3.accounts where name = %s", (name,)).fetchone()
    db.rollback()
    return Actor(id=i, name=name, role=Role(role))


def _signed_in(client, db, name: str) -> None:
    assert sign_in_with_correct_password(client, db, name).status_code == 303


def _perform(db, action) -> Recorder:
    r = Recorder(db)
    r.perform(action)
    return r


def _write(db, who: str, type_: str):
    return lambda: audit.write(_actor(db, who), type_, f"test {type_}")


def test_passes_when_the_session_owner_wrote_a_row_of_that_type(client, db):
    _signed_in(client, db, "Kuei")
    r = _perform(db, _write(db, "Kuei", "ACCOUNT_ROLE_CHANGE"))
    audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")
    check_nothing_else_written(r)  # 被認領的那一列可以被扣掉


def test_fails_when_the_type_is_different(client, db):
    _signed_in(client, db, "Kuei")
    r = _perform(db, _write(db, "Kuei", "ACCOUNT_UPDATE"))
    with pytest.raises(AssertionError, match="ACCOUNT_ROLE_CHANGE"):
        audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")


def test_fails_when_the_actor_is_not_the_session_owner(client, db):
    _signed_in(client, db, "Admin1")
    r = _perform(db, _write(db, "Kuei", "ACCOUNT_ROLE_CHANGE"))  # 類型對，行為者是 Kuei，不是 session 的主人 Admin1
    with pytest.raises(AssertionError, match="Admin1"):
        audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")


def test_fails_when_no_audit_row_is_added(client, db):
    _signed_in(client, db, "Kuei")
    r = _perform(db, lambda: None)
    with pytest.raises(AssertionError):
        audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")


def test_fails_when_nobody_is_signed_in(client, db):
    r = _perform(db, _write(db, "Kuei", "ACCOUNT_ROLE_CHANGE"))  # 這個 client 沒有 session cookie
    with pytest.raises(AssertionError, match="已登入"):
        audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")


def test_one_row_cannot_be_claimed_twice(client, db):
    _signed_in(client, db, "Kuei")
    r = _perform(db, _write(db, "Kuei", "ACCOUNT_ROLE_CHANGE"))
    audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")
    with pytest.raises(AssertionError):
        audit_row.check_audit_row_written(r, client, db, "ACCOUNT_ROLE_CHANGE")
