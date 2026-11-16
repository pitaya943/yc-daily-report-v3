"""「nothing else is written」的語意（修正第 1 輪，Verifier 對 AUD-R03 的判定）。

- `nothing is written`：整個資料庫完全沒有變動，不放寬。
- `nothing else is written`：扣掉「同一個 scenario 前面的步驟已經明確斷言過」的寫入之後，不得有其他變動。
  只有明確斷言過的寫入可以被扣掉；沒斷言過的、多寫的、改到或刪掉既有資料的，一律算違規。

這裡直接呼叫共用步驟背後的函式（claim_audit_row、check_nothing_else_written、check_nothing_written），
因為「該失敗的時候會失敗」無法用一個必須通過的 Gherkin scenario 表達。
AUD-R03 的正常情況（通過）則由 common_steps.feature 的 scenario 走真的 HTTP 請求驗證。
"""
import pytest

from app.core import audit
from app.core.permissions import Actor, Role
from tests.steps.common import steps as common
from tests.steps.common.steps import Recorder


def _wen(db) -> Actor:
    i, role = db.execute("select id, role from yc_v3.accounts where name = 'Wen'").fetchone()
    db.rollback()
    return Actor(id=i, name="Wen", role=Role(role))


def _perform(db, action) -> Recorder:
    r = Recorder(db)
    r.perform(action)
    return r


def _deny(db, who="Wen"):
    audit.write(_wen(db), "ACCESS_DENIED", f"嘗試執行但被拒絕：confirm a report ({who})")


def _extra_account(db):
    db.execute("insert into yc_v3.accounts(name, role, zone) values ('Extra','USER','WEST')")
    db.commit()


def test_only_the_asserted_access_denied_row_is_allowed(db):
    """(1) AUD-R03 的情境：正確的產品行為（只寫一列 ACCESS_DENIED）→ 通過。"""
    r = _perform(db, lambda: _deny(db))
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    common.check_nothing_else_written(r)


def test_a_second_write_besides_access_denied_fails(db):
    """(2) 除了 ACCESS_DENIED 之外又偷寫一列（另一張表）→ 失敗。"""

    def act():
        _deny(db)
        _extra_account(db)

    r = _perform(db, act)
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError, match="Extra"):
        common.check_nothing_else_written(r)


def test_a_second_audit_row_besides_the_asserted_one_fails(db):
    """多寫了第二列稽核（同類型也算）：斷言只扣掉一列。"""

    def act():
        _deny(db)
        _deny(db)

    r = _perform(db, act)
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError):
        common.check_nothing_else_written(r)


def test_an_access_denied_row_that_was_never_asserted_fails(db):
    """(3) 沒有先斷言就寫了 ACCESS_DENIED → nothing else is written 也失敗。"""
    r = _perform(db, lambda: _deny(db))
    with pytest.raises(AssertionError, match="ACCESS_DENIED"):
        common.check_nothing_else_written(r)


def test_changing_or_deleting_existing_data_fails_even_with_an_asserted_row(db):
    def upd():
        _deny(db)
        db.execute("update yc_v3.accounts set zone = 'SOUTH' where name = 'Wen'")
        db.commit()

    r = _perform(db, upd)
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError):
        common.check_nothing_else_written(r)

    def dele():
        _deny(db)
        db.execute("delete from yc_v3.accounts where name = 'Old'")
        db.commit()

    r = _perform(db, dele)
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError):
        common.check_nothing_else_written(r)


def test_nothing_written_stays_strict_and_is_not_relaxed_by_claims(db):
    """`nothing is written` 不放寬：即使 ACCESS_DENIED 已被斷言，整個資料庫仍然有變動 → 失敗。"""
    r = _perform(db, lambda: _deny(db))
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError):
        common.check_nothing_written(r)


def test_nothing_else_written_with_no_write_and_no_claim_passes(db):
    common.check_nothing_else_written(_perform(db, lambda: None))


def test_a_claim_needs_a_matching_new_row(db):
    r = _perform(db, lambda: None)
    with pytest.raises(AssertionError, match="ACCESS_DENIED"):
        common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")


def test_the_same_row_cannot_be_claimed_twice(db):
    """兩次斷言同一列不能把兩列都扣掉。"""

    def act():
        _deny(db)
        _deny(db)

    r = _perform(db, act)
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")
    common.claim_audit_row(r, db, "ACCESS_DENIED", "Wen")  # 第二列
    common.check_nothing_else_written(r)  # 兩列各被斷言一次 → 通過
    r2 = _perform(db, lambda: _deny(db))
    common.claim_audit_row(r2, db, "ACCESS_DENIED", "Wen")
    with pytest.raises(AssertionError):
        common.claim_audit_row(r2, db, "ACCESS_DENIED", "Wen")  # 只有一列，不能再扣第二次
