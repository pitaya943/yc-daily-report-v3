"""IAM-R08（提前解除鎖定，D-126）：scenario 沒有逐字涵蓋的部分（T-308 完成條件 13）。

每個測試只放**一個**錯誤原因（pitfall #32）。每個拒絕都檢查三件事：結果類別、完整錯誤字串、資料的變動：
- `FORBIDDEN`：結果類別與（沒有）錯誤字串，資料只多一列 `ACCESS_DENIED`、行為者是發出請求的人（D-095），鎖定仍在；
- `CONFLICT`、`UNAUTHENTICATED`、404：沒有錯誤字串（規格沒寫），整個資料庫完全不變。

以下「比規格更嚴格的斷言」會在 PR 說明逐條列出（D-091）：對沒有鎖定的帳戶解除為 `CONFLICT`（規格沒寫）、
USER 不論目標為何一律 `FORBIDDEN`、OWNER 帳戶沒有人能解除（包括 OWNER 自己）、解除不動來源位址的嘗試次數、
解除後被解除者真的能以正確的密碼登入、別的帳戶的鎖定不受影響。
"""
from __future__ import annotations

from datetime import timedelta

import iam_f02_steps as f02
import pytest
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.main import create_app
from tests.steps.common.outcome import check_forbidden_writes_only_access_denied
from tests.steps.common.session import TEST_PASSWORD, post_sign_in, set_password, sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected


def signed_in(db, name: str) -> TestClient:
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert sign_in_with_correct_password(client, db, name).status_code == 303
    return client


def lock(db, name: str, ago: timedelta = timedelta(minutes=5)) -> None:
    at = clock.now() - ago
    f02.seed_failures(db, name, 5, last_failed_at=at, locked_at=at)


def unlock(db, client, target_id: int) -> Recorder:
    recorder = Recorder(db)
    recorder.perform(lambda: f02.post_unlock(client, db, target_id))
    return recorder


def id_of(db, name: str) -> int:
    return f02._account_id(db, name)


# ───────────────────────── 成功 ─────────────────────────


def test_an_unlocked_account_can_sign_in_with_the_correct_password_again(db):
    lock(db, "Wen")
    assert unlock(db, signed_in(db, "Admin1"), id_of(db, "Wen")).response.status_code == 200
    set_password(db, "Wen")
    assert post_sign_in(TestClient(create_app(), raise_server_exceptions=False), "Wen", TEST_PASSWORD).status_code == 303


def test_unlocking_touches_only_the_target_failure_row_and_one_audit_row(db):
    lock(db, "Wen")
    lock(db, "Wei")
    r = unlock(db, signed_in(db, "Admin1"), id_of(db, "Wen"))
    assert r.response.status_code == 200
    assert set(r.changes()) == {"sign_in_failures", "audit_log"}, r.changes()
    assert f02.failure_row(db, "Wen") is None and f02.failure_row(db, "Wei")[2] is not None, "別的帳戶的鎖定不受影響（IAM-R06）"


def test_unlocking_leaves_the_address_rate_limit_alone(db):
    lock(db, "Wen")
    f02._seed_attempts(db, 10)
    r = unlock(db, signed_in(db, "Admin1"), id_of(db, "Wen"))
    assert r.response.status_code == 200 and "sign_in_attempts" not in r.changes()
    assert f02.attempts_for(db, f02.ADDRESS) == 10


def test_the_audit_row_names_the_unlocker_and_does_not_use_a_new_type(db):
    lock(db, "Wen")
    r = unlock(db, signed_in(db, "Admin1"), id_of(db, "Wen"))
    rows = db.execute("select type, actor_name, description from yc_v3.audit_log where type <> 'ACCESS_DENIED'").fetchall()
    db.rollback()
    assert len(r.changes()["audit_log"]["added"]) == 1
    assert [(t, a) for t, a, _ in rows] == [("ACCOUNT_UPDATE", "Admin1")] and "解除鎖定" in rows[0][2] and "Wen" in rows[0][2]


# ───────────────────────── FORBIDDEN ─────────────────────────


@pytest.mark.parametrize("target", ["Wen", "Wei"], ids=["locked-user", "another-locked-user"])
def test_a_user_cannot_unlock_anyone_and_the_lock_stays(db, target):
    lock(db, target)
    client = signed_in(db, "Nan")
    r = unlock(db, client, id_of(db, target))
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)
    assert f02.failure_row(db, target)[2] is not None


def test_a_user_gets_forbidden_even_for_an_account_that_does_not_exist(db):
    """USER 在查目標之前就被拒絕，不能藉由 404 與 403 的差別探測哪些帳戶存在。"""
    client = signed_in(db, "Wen")
    r = unlock(db, client, 99999)
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_nobody_can_unlock_the_owner_not_even_the_owner(db):
    clients = {who: signed_in(db, who) for who in ("Admin1", "Kuei")}
    lock(db, "Kuei")  # 登入之後才鎖定，所以兩個 session 仍有效
    for who, client in clients.items():
        r = unlock(db, client, id_of(db, "Kuei"))
        check_rejected(r, "FORBIDDEN", None)
        check_forbidden_writes_only_access_denied(r, client, db)
    assert f02.failure_row(db, "Kuei")[2] is not None


def test_an_admin_cannot_unlock_themselves(db):
    client = signed_in(db, "Admin1")
    lock(db, "Admin1")  # 登入之後才鎖定，所以這個 session 仍有效
    r = unlock(db, client, id_of(db, "Admin1"))
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


# ───────────────────────── CONFLICT、404、UNAUTHENTICATED ─────────────────────────


def _conflict_cases():
    return {
        "never-failed": lambda db: None,
        "failures-but-not-locked": lambda db: f02.seed_failures(db, "Wen", 3, last_failed_at=clock.now() - timedelta(minutes=1)),
        "lock-already-ended": lambda db: lock(db, "Wen", ago=timedelta(minutes=15)),
    }


@pytest.mark.parametrize("case", list(_conflict_cases()))
def test_unlocking_an_account_that_is_not_locked_is_a_conflict_and_changes_nothing(db, case):
    _conflict_cases()[case](db)
    r = unlock(db, signed_in(db, "Admin1"), id_of(db, "Wen"))
    check_rejected(r, "CONFLICT", None)
    check_nothing_written(r)


def test_an_admin_unlocking_another_admin_is_forbidden_before_the_conflict_is_considered(db):
    """Admin2 沒有被鎖定，但 ADMIN 不能解除 ADMIN：權限先於狀態（FORBIDDEN，不是 CONFLICT）。"""
    client = signed_in(db, "Admin1")
    r = unlock(db, client, id_of(db, "Admin2"))
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_unlocking_a_missing_account_is_404_and_writes_nothing(db):
    r = unlock(db, signed_in(db, "Admin1"), 99999)
    assert r.response.status_code == 404
    check_nothing_written(r)


def test_a_visitor_cannot_unlock(db):
    lock(db, "Wen")
    visitor = TestClient(create_app(), raise_server_exceptions=False)
    r = Recorder(db)
    r.perform(lambda: visitor.post(f"/accounts/{id_of(db, 'Wen')}/unlock"))
    check_rejected(r, "UNAUTHENTICATED", None)
    check_nothing_written(r)


def test_an_unlock_without_the_anti_forgery_token_is_forbidden_and_the_lock_stays(db):
    lock(db, "Wen")
    client = signed_in(db, "Admin1")
    r = Recorder(db)
    r.perform(lambda: client.post(f"/accounts/{id_of(db, 'Wen')}/unlock"))
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)
    assert f02.failure_row(db, "Wen")[2] is not None


def test_a_get_on_the_unlock_path_is_not_allowed_and_changes_nothing(db):
    lock(db, "Wen")
    client = signed_in(db, "Admin1")
    r = Recorder(db)
    r.perform(lambda: client.get(f"/accounts/{id_of(db, 'Wen')}/unlock"))
    assert r.response.status_code in (404, 405)
    check_nothing_written(r)
