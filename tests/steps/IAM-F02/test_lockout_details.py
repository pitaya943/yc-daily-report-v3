"""IAM-F02 的 scenario 沒有逐字涵蓋、但 T-102 的完成條件與 D-069 要求的行為。

每個拒絕都檢查三件事：結果類別、完整錯誤字串、資料沒有變動（D-069：只有被評估的嘗試才寫那兩張表，
而且寫了什麼要明確斷言，不是被忽略）。
"""
from datetime import timedelta

import iam_f02_steps as f02
import pytest
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.main import create_app
from tests.steps.common.session import TEST_PASSWORD, post_sign_in, set_password
from tests.steps.common.steps import Recorder, check_rejected

LOCKED_MSG = "密碼錯誤次數過多，請在 15 分鐘後再試"
WRONG_MSG = "密碼錯誤，請重試"


def _perform(db, send) -> Recorder:
    recorder = Recorder(db)
    recorder.perform(send)
    return recorder


def test_fourth_failure_is_still_a_wrong_password_not_a_lock(client, db):
    set_password(db, "Wen")
    f02.seed_failures(db, "Wen", 3, last_failed_at=clock.now() - timedelta(minutes=1))
    r = _perform(db, lambda: post_sign_in(client, "Wen", "wrong"))
    check_rejected(r, "UNAUTHENTICATED", WRONG_MSG)
    assert f02.failure_row(db, "Wen")[0] == 4 and f02.failure_row(db, "Wen")[2] is None
    f02.assert_only_lock_tables_written(r)


def test_five_wrong_passwords_in_a_row_lock_and_write_exactly_one_lockout_audit_row(client, db):
    set_password(db, "Wen")
    for i in range(4):
        check_rejected(_perform(db, lambda: post_sign_in(client, "Wen", "wrong")), "UNAUTHENTICATED", WRONG_MSG)
    r = _perform(db, lambda: post_sign_in(client, "Wen", "wrong"))
    check_rejected(r, "LOCKED", LOCKED_MSG)
    assert f02.failure_row(db, "Wen")[0] == 5 and f02.failure_row(db, "Wen")[2] == clock.now()
    assert len(r.changes()["audit_log"]["added"]) == 1


def test_attempts_during_the_lock_write_nothing_and_do_not_extend_it(client, db):
    set_password(db, "Wen")
    locked_at = clock.now() - timedelta(minutes=5)
    f02.seed_failures(db, "Wen", 5, last_failed_at=locked_at, locked_at=locked_at)
    for password in ("wrong", TEST_PASSWORD):
        r = _perform(db, lambda password=password: post_sign_in(client, "Wen", password))
        check_rejected(r, "LOCKED", LOCKED_MSG)
        assert not r.changes(), f"鎖定期間的拒絕不得寫任何資料：{r.changes()}"
    assert f02.failure_row(db, "Wen")[2] == locked_at, "鎖定的起點不得被延後"


def test_a_failure_after_the_quiet_period_starts_a_new_round(client, db):
    set_password(db, "Wen")
    f02.seed_failures(db, "Wen", 4, last_failed_at=clock.now() - timedelta(minutes=15))  # 剛好滿 15 分鐘 = 新的一輪
    r = _perform(db, lambda: post_sign_in(client, "Wen", "wrong"))
    check_rejected(r, "UNAUTHENTICATED", WRONG_MSG)
    assert f02.failure_row(db, "Wen")[0] == 1


def test_a_failure_just_inside_the_quiet_period_keeps_counting(client, db):
    set_password(db, "Wen")
    f02.seed_failures(db, "Wen", 4, last_failed_at=clock.now() - timedelta(minutes=14, seconds=59))
    r = _perform(db, lambda: post_sign_in(client, "Wen", "wrong"))
    check_rejected(r, "LOCKED", LOCKED_MSG)


def test_unknown_and_archived_accounts_are_attempts_but_never_failures(client, db):
    set_password(db, "Old")
    for name in ("Nobody", "Old"):
        for _ in range(6):  # 超過 5 次也不會被鎖：沒有帳戶可鎖，而且回應不變（IAM-R03）
            clock.advance(timedelta(seconds=61))  # 避免撞到每分鐘 10 次的頻率限制，這裡要測的是帳戶鎖定
            r = _perform(db, lambda name=name: post_sign_in(client, name, "wrong"))
            check_rejected(r, "UNAUTHENTICATED", WRONG_MSG)
            changes = f02.assert_only_lock_tables_written(r)
            assert f02.FAILURES not in changes and len(changes[f02.ATTEMPTS]["added"]) == 1


def test_invalid_fields_write_nothing(client, db):
    r = _perform(db, lambda: client.post("/sign-in", data={"password": "x"}, follow_redirects=False))
    check_rejected(r, "INVALID", "請選擇帳戶")
    assert not r.changes()


def test_a_success_clears_the_failure_count(client, db):
    set_password(db, "Wen")
    f02.seed_failures(db, "Wen", 4, last_failed_at=clock.now())
    assert post_sign_in(client, "Wen", TEST_PASSWORD).status_code == 303
    assert f02.failure_row(db, "Wen") is None


def test_rate_limit_boundary_an_attempt_exactly_60_seconds_old_has_expired(address_client, db):
    set_password(db, "Wen")
    with db.cursor() as cur:
        for i in range(10):
            # 其中一次剛好 60 秒前（已過期），其餘 9 次在窗內：所以只有 9 次有效，第 10 次還可以進來
            age = 60 if i == 0 else 5 * i
            cur.execute("insert into yc_v3.sign_in_attempts(client_address, attempted_at) values (%s, %s)", (f02.ADDRESS, clock.now() - timedelta(seconds=age)))
    db.commit()
    assert post_sign_in(address_client, "Wen", TEST_PASSWORD).status_code == 303
    # 現在窗內有 10 次（9 + 剛才這次），下一次被限制
    r = _perform(db, lambda: post_sign_in(address_client, "Wen", TEST_PASSWORD))
    check_rejected(r, "RATE_LIMITED", None)
    assert not r.changes()


def test_rate_limit_is_per_address_and_resets_after_the_window(db):
    set_password(db, "Wen")
    a = TestClient(create_app(), raise_server_exceptions=False, client=("198.51.100.1", 1))
    b = TestClient(create_app(), raise_server_exceptions=False, client=("198.51.100.2", 1))
    with db.cursor() as cur:
        for i in range(10):
            cur.execute("insert into yc_v3.sign_in_attempts(client_address, attempted_at) values (%s, %s)", ("198.51.100.1", clock.now() - timedelta(seconds=i + 1)))
    db.commit()
    check_rejected(_perform(db, lambda: post_sign_in(a, "Wen", TEST_PASSWORD)), "RATE_LIMITED", None)
    assert post_sign_in(b, "Wen", TEST_PASSWORD).status_code == 303, "別的位址不受影響"
    clock.advance(timedelta(seconds=61))
    assert post_sign_in(a, "Wen", TEST_PASSWORD).status_code == 303, "窗過了就恢復"


def test_expired_attempts_are_pruned_when_the_address_is_next_accepted(client, db):
    with db.cursor() as cur:
        cur.execute("insert into yc_v3.sign_in_attempts(client_address, attempted_at) values ('testclient', %s)", (clock.now() - timedelta(minutes=5),))
    db.commit()
    post_sign_in(client, "Nobody", "x")
    assert f02.attempts_for(db, "testclient") == 1


@pytest.mark.concurrency
def test_two_workers_cannot_both_record_the_fifth_failure(db):
    """兩個 worker 同時送出第 5 次錯誤：只會有一個寫出 ACCOUNT_LOCKOUT，且次數不會重複累計。"""
    import threading

    set_password(db, "Wen")
    f02.seed_failures(db, "Wen", 4, last_failed_at=clock.now())
    apps = [create_app(), create_app()]
    barrier = threading.Barrier(2)
    codes: list[int] = [0, 0]

    def go(i: int) -> None:
        c = TestClient(apps[i], raise_server_exceptions=False, client=(f"198.51.100.{10 + i}", 1))
        barrier.wait(timeout=30)
        codes[i] = post_sign_in(c, "Wen", "wrong").status_code

    ts = [threading.Thread(target=go, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    assert sorted(codes) == [423, 423], codes  # 第 5 次是 LOCKED；另一個看到已經鎖定，也是 LOCKED
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.audit_log where type = 'ACCOUNT_LOCKOUT'")
        assert cur.fetchone()[0] == 1
    db.rollback()
    assert f02.failure_row(db, "Wen")[0] == 5
