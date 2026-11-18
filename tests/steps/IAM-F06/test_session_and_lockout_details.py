"""IAM-R33（改密碼後的 session）與 IAM-R34（錯誤的目前密碼與登入共用鎖定）：scenario 沒有逐字涵蓋的部分（T-308）。

每個測試只放**一個**錯誤原因（pitfall #32），不斷言規格沒寫的行為。每個拒絕都檢查三件事：結果類別、完整錯誤字串、資料的變動
（錯誤的目前密碼是這個端點唯一會寫資料的拒絕：恰好寫 `sign_in_failures` 那一列，D-124）。

以下「比規格更嚴格的斷言」會在 PR 說明逐條列出（D-091）：整個資料庫的前後差異（只有哪幾張表、各多或少哪幾列）、
`sign_in_attempts`（來源位址的頻率限制）完全不變、被結束的 session 以資料庫列數確認、別的帳戶的 session 不受影響。
"""
from __future__ import annotations

from datetime import timedelta

import iam_f02_steps as f02
import iam_f06_steps as f06
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.main import create_app
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, session_rows, set_password, sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected

LOCKED_MSG = "密碼錯誤次數過多，請在 15 分鐘後再試"
CURRENT_WRONG = "目前密碼不正確"
NEW = {"new_password": "newpass1", "password_confirm": "newpass1"}


def signed_in(db, name: str) -> TestClient:
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert sign_in_with_correct_password(client, db, name).status_code == 303
    return client


def change(db, client, current: str, **overrides) -> Recorder:
    recorder = Recorder(db)
    fields = {"current_password": current, **NEW, **overrides}
    recorder.perform(lambda: f06.post_form(client, db, f06.OWN_PASSWORD_PATH, fields))
    return recorder


def protected_status(client) -> int:
    return client.get("/account/password", follow_redirects=False).status_code


def added(recorder: Recorder, table: str) -> list[str]:
    return recorder.changes().get(table, {}).get("added", [])


# ───────────────────────── IAM-R34：錯誤的目前密碼寫什麼 ─────────────────────────


def test_a_wrong_current_password_writes_only_one_failure_count_row(db):
    client = signed_in(db, "Wen")
    r = change(db, client, "wrong")
    check_rejected(r, "INVALID", CURRENT_WRONG)
    assert set(r.changes()) == {"sign_in_failures"}, f"只有失敗次數那一張表可以有變動：{r.changes()}"
    assert len(added(r, "sign_in_failures")) == 1 and r.changes()["sign_in_failures"]["removed"] == []
    assert f02.failure_row(db, "Wen")[0] == 1 and f02.failure_row(db, "Wen")[2] is None


def test_the_fourth_wrong_password_is_still_invalid_not_locked(db):
    client = signed_in(db, "Wen")
    f02.seed_failures(db, "Wen", 3, last_failed_at=clock.now() - timedelta(minutes=1))
    check_rejected(change(db, client, "wrong"), "INVALID", CURRENT_WRONG)
    assert f02.failure_row(db, "Wen")[0] == 4 and f02.failure_row(db, "Wen")[2] is None


def test_wrong_current_passwords_and_wrong_sign_ins_add_up_to_one_count(db):
    client = signed_in(db, "Wen")
    other = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(other, "Wen", "wrong").status_code == 401  # 登入頁的第 1 次
    assert post_sign_in(other, "Wen", "wrong").status_code == 401  # 第 2 次
    check_rejected(change(db, client, "wrong"), "INVALID", CURRENT_WRONG)  # 改密碼頁的第 3 次
    assert f02.failure_row(db, "Wen")[0] == 3, "兩個入口的失敗要累加在同一個計數"


def test_the_lockout_by_a_wrong_current_password_writes_one_lockout_row_and_changes_nothing_else(db):
    client = signed_in(db, "Wen")
    f02.seed_failures(db, "Wen", 4, last_failed_at=clock.now() - timedelta(minutes=1))
    r = change(db, client, "wrong")
    check_rejected(r, "LOCKED", LOCKED_MSG)
    assert set(r.changes()) == {"sign_in_failures", "audit_log"}, f"只有失敗次數與一列稽核：{r.changes()}"
    assert len(added(r, "audit_log")) == 1
    assert f02.failure_row(db, "Wen")[0] == 5 and f02.failure_row(db, "Wen")[2] == clock.now()


def test_a_wrong_current_password_during_the_lock_is_locked_and_writes_nothing(db):
    client = signed_in(db, "Wen")
    locked_at = clock.now() - timedelta(minutes=5)
    f02.seed_failures(db, "Wen", 5, last_failed_at=locked_at, locked_at=locked_at)
    r = change(db, client, "wrong")
    check_rejected(r, "LOCKED", LOCKED_MSG)
    check_nothing_written(r)
    assert f02.failure_row(db, "Wen")[2] == locked_at, "鎖定的起點不得被延後"


def test_a_lock_ends_after_15_minutes_for_a_password_change_too(db):
    client = signed_in(db, "Wen")
    locked_at = clock.now() - timedelta(minutes=15)  # 剛好滿 15 分鐘 = 鎖定結束（IAM-R04）
    f02.seed_failures(db, "Wen", 5, last_failed_at=locked_at, locked_at=locked_at)
    assert change(db, client, TEST_PASSWORD).response.status_code == 200


def test_the_first_wrong_current_password_after_a_lock_ended_starts_a_new_round(db):
    client = signed_in(db, "Wen")
    locked_at = clock.now() - timedelta(minutes=15)
    f02.seed_failures(db, "Wen", 5, last_failed_at=locked_at, locked_at=locked_at)
    check_rejected(change(db, client, "wrong"), "INVALID", CURRENT_WRONG)
    row = f02.failure_row(db, "Wen")
    assert row[0] == 1 and row[2] is None, f"IAM-R05：鎖定結束後新的一輪從 1 開始：{row}"


def test_the_correct_current_password_does_not_reset_the_failure_count(db):
    client = signed_in(db, "Wen")
    seeded = clock.now() - timedelta(minutes=1)
    f02.seed_failures(db, "Wen", 3, last_failed_at=seeded)
    r = change(db, client, TEST_PASSWORD)
    assert r.response.status_code == 200
    assert "sign_in_failures" not in r.changes(), "規格沒寫正確的目前密碼是否重置：維持不重置（IAM-R05 只有三種重置事件）"
    assert f02.failure_row(db, "Wen")[0] == 3


def test_a_wrong_current_password_is_not_counted_toward_the_address_rate_limit(db):
    """來源位址已經用完 10 次登入額度，改密碼仍然被評估（INVALID，不是 RATE_LIMITED），也不新增嘗試次數（D-124、IAM-R07）。"""
    client = TestClient(create_app(), raise_server_exceptions=False, client=(f02.ADDRESS, 50000))
    set_password(db, "Wen")
    assert post_sign_in(client, "Wen", TEST_PASSWORD).status_code == 303
    f02._seed_attempts(db, 10)
    r = change(db, client, "wrong")
    check_rejected(r, "INVALID", CURRENT_WRONG)
    assert "sign_in_attempts" not in r.changes(), f"改密碼不得寫來源位址的嘗試次數：{r.changes().get('sign_in_attempts')}"


def test_a_locked_password_change_leaves_the_password_and_the_sessions_alone(db):
    client = signed_in(db, "Wen")
    locked_at = clock.now() - timedelta(minutes=5)
    f02.seed_failures(db, "Wen", 5, last_failed_at=locked_at, locked_at=locked_at)
    r = change(db, client, TEST_PASSWORD)
    check_rejected(r, "LOCKED", LOCKED_MSG)
    check_nothing_written(r)
    assert post_sign_in(TestClient(create_app(), raise_server_exceptions=False), "Wen", TEST_PASSWORD).status_code == 423


# ───────────────────────── IAM-R33：誰的 session 會結束 ─────────────────────────


def test_changing_ones_own_password_ends_exactly_the_other_sessions_of_that_account(db):
    set_password(db, "Wen")
    devices = []
    for _ in range(3):
        d = TestClient(create_app(), raise_server_exceptions=False)
        assert post_sign_in(d, "Wen", TEST_PASSWORD).status_code == 303
        devices.append(d)
    before = {row[0] for row in session_rows(db, "Wen")}
    assert len(before) == 3
    kept_token = devices[1].cookies.get(SESSION_COOKIE)
    assert change(db, devices[1], TEST_PASSWORD).response.status_code == 200
    rows = session_rows(db, "Wen")
    assert len(rows) == 1 and rows[0][0] in before, "只剩目前這一列 session，而且是原來那一列（不是換發新的）"
    assert devices[1].cookies.get(SESSION_COOKIE) == kept_token
    assert [protected_status(d) for d in devices] == [401, 200, 401]


def test_changing_a_password_does_not_end_the_sessions_of_other_accounts(db):
    wei = signed_in(db, "Wei")
    admin = signed_in(db, "Admin1")
    wen = signed_in(db, "Wen")
    assert change(db, wen, TEST_PASSWORD).response.status_code == 200
    assert protected_status(wei) == 200 and protected_status(admin) == 200
    assert len(session_rows(db, "Wei")) == 1 and len(session_rows(db, "Admin1")) == 1


def test_a_rejected_change_does_not_end_any_session(db):
    first = signed_in(db, "Wen")
    second = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(second, "Wen", TEST_PASSWORD).status_code == 303
    r = change(db, first, "wrong")
    check_rejected(r, "INVALID", CURRENT_WRONG)
    assert "sessions" not in r.changes()
    assert protected_status(first) == 200 and protected_status(second) == 200


def test_a_reset_ends_only_the_target_sessions_and_keeps_the_administrators_own(db):
    admin = signed_in(db, "Admin1")
    wei = signed_in(db, "Wei")
    set_password(db, "Wen")
    wen = [TestClient(create_app(), raise_server_exceptions=False) for _ in range(2)]
    for d in wen:
        assert post_sign_in(d, "Wen", TEST_PASSWORD).status_code == 303
    r = Recorder(db)
    r.perform(lambda: f06.post_form(admin, db, f06.RESET_PATH.format(id=f06.account_id(db, "Wen")), {"new_password": "newpass1", "password_confirm": "newpass1"}))
    assert r.response.status_code == 200
    assert session_rows(db, "Wen") == [] and [protected_status(d) for d in wen] == [401, 401]
    assert protected_status(admin) == 200 and protected_status(wei) == 200


def test_an_ended_session_cannot_be_revived_by_the_new_password(db):
    first = signed_in(db, "Wen")
    second = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(second, "Wen", TEST_PASSWORD).status_code == 303
    assert change(db, first, TEST_PASSWORD).response.status_code == 200
    assert protected_status(second) == 401
    again = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(again, "Wen", "newpass1").status_code == 303, "結束的是舊 session，帳戶本身可以用新密碼再登入"
