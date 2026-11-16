"""IAM-F02 登入鎖定與頻率限制的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

設計：
- 失敗次數與嘗試次數存在資料庫（migration 0004），所以「Given」直接把列寫進那兩張表，不是呼叫 N 次登入：
  一次 scrypt 約零點幾秒，真的登入 5 次會讓每個 scenario 慢好幾秒，而且「已經鎖定」本身要測的就是資料庫裡的狀態。
- 「When」一律走真正的 `POST /sign-in`，並透過 `recorder.perform` 記下前後快照。
- 被拒絕的登入一定會寫那兩張表（D-069）。規格的 scenario 沒有寫 `nothing is written`，所以這裡的 Then 步驟自己明確斷言：
  那兩張表各多出預期的那一列，而且其他所有表（sessions、accounts…）完全不變（audit_log 只有鎖定當下那一列）。
- `RATE_LIMITED` 與鎖定期間的拒絕不寫任何資料：前者在 When 步驟內斷言（規格沒有再寫 And），後者由共用的
  `the outcome is LOCKED`（tests/steps/common/outcome.py）斷言 nothing is written。
"""
from __future__ import annotations

import re
import threading
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core.clock import clock
from app.main import create_app
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import TEST_PASSWORD, post_sign_in, set_password
from tests.steps.common.session import *  # noqa: F401,F403  (signs in with the correct password、is signed in)
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、共用的拒絕與稽核步驟)
from tests.steps.common.steps import claim_audit_row

FAILURES = "sign_in_failures"
ATTEMPTS = "sign_in_attempts"
LOCK_TABLES = frozenset({FAILURES, ATTEMPTS})
# 規格沒有指定位址；用文件保留的測試網段（RFC 5737），不會和任何真實位址混淆
ADDRESS = "198.51.100.23"


# ───────────────────────── 資料庫輔助 ─────────────────────────


def _account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        value = cur.fetchone()[0]
    db.rollback()
    return value


def seed_failures(db, name: str, count: int, *, last_failed_at, locked_at=None) -> None:
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.sign_in_failures(account_id, fail_count, last_failed_at, locked_at) values (%s, %s, %s, %s)",
            (_account_id(db, name), count, last_failed_at, locked_at),
        )
    db.commit()


def failure_row(db, name: str):
    with db.cursor() as cur:
        cur.execute("select fail_count, last_failed_at, locked_at from yc_v3.sign_in_failures where account_id = %s", (_account_id(db, name),))
        row = cur.fetchone()
    db.rollback()
    return row


def attempts_for(db, address: str) -> int:
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.sign_in_attempts where client_address = %s", (address,))
        value = cur.fetchone()[0]
    db.rollback()
    return value


def parse_elapsed(text: str) -> timedelta:
    """`5 minutes`、`14 min 59 sec`、`15 min 00 sec` → timedelta。"""
    m = re.fullmatch(r"(\d+) min(?:utes?)?(?: (\d+) sec)?", text.strip())
    assert m, f"看不懂的時間長度：{text!r}"
    return timedelta(minutes=int(m.group(1)), seconds=int(m.group(2) or 0))


def assert_only_lock_tables_written(recorder, *, allow_audit: bool = False) -> dict:
    """被拒絕的登入只能寫失敗次數與嘗試次數兩張表（以及鎖定當下的稽核列）；其他任何表有變動都算違規。"""
    allowed = LOCK_TABLES | ({"audit_log"} if allow_audit else set())
    changes = recorder.changes()
    others = {t: c for t, c in changes.items() if t not in allowed}
    assert not others, f"除了失敗次數、嘗試次數{'、稽核' if allow_audit else ''}之外，還有其他資料表被改動：{others}"
    return changes


# ───────────────────────── IAM-R04、R05、R06：Given ─────────────────────────


@given(parsers.re(r'"(?P<name>[^"]+)" has (?P<count>\d+) failed sign-ins in the last 15 minutes'))
def _failures_in_last_15(db, name, count):
    seed_failures(db, name, int(count), last_failed_at=clock.now() - timedelta(minutes=1))


@given(parsers.re(r'"(?P<name>[^"]+)" was locked (?P<elapsed>(?:\d+ min(?:utes)?)(?: \d+ sec)?) ago'))
def _locked_ago(db, name, elapsed):
    locked_at = clock.now() - parse_elapsed(elapsed)
    seed_failures(db, name, 5, last_failed_at=locked_at, locked_at=locked_at)


@given(parsers.re(r'"(?P<name>[^"]+)" has 5 failed sign-ins and is locked'))
def _five_and_locked(db, name):
    seed_failures(db, name, 5, last_failed_at=clock.now(), locked_at=clock.now())


@given(parsers.re(r'"(?P<name>[^"]+)" has (?P<count>\d+) failed sign-ins'))
def _failures_before(db, name, count):
    # 滿 5 次的狀態一定是已鎖定（資料表的 check 約束也這樣要求）
    n = int(count)
    seed_failures(db, name, n, last_failed_at=clock.now(), locked_at=clock.now() if n >= 5 else None)


@given(parsers.re(r'"(?P<name>[^"]+)" then signed in successfully'))
def _then_signed_in(client, db, name):
    set_password(db, name)
    response = post_sign_in(client, name, TEST_PASSWORD)
    assert response.status_code == 303, f"登入應成功（303），實際 {response.status_code}：{response.text[:200]}"


@given("the 15-minute lock has ended")
def _lock_ended():
    clock.advance(timedelta(minutes=15))


@given("15 minutes passed with no further failure")
def _quiet_15():
    clock.advance(timedelta(minutes=15))


# ───────────────────────── IAM-R04、R05：When / Then ─────────────────────────


@when(parsers.re(r'"(?P<name>[^"]+)" signs in with a wrong password'))
def _wrong_password(recorder, client, db, name):
    set_password(db, name)  # 動作「之前」寫入，不算動作造成的資料變動
    recorder.perform(lambda: post_sign_in(client, name, "wrong"))


@then(parsers.re(r'an audit row "(?P<type_>[A-Z_]+)" is written with actor SYSTEM'))
def _audit_with_system_actor(recorder, db, type_):
    # SYSTEM 在規格裡沒有引號（它是行為者的角色，不是帳戶名稱）；共用步驟要求引號，所以這裡另寫，行為相同
    claim_audit_row(recorder, db, type_, "SYSTEM")
    changes = assert_only_lock_tables_written(recorder, allow_audit=True)
    assert len(changes["audit_log"]["added"]) == 1, f"鎖定當下應只新增 1 列稽核，實際：{changes['audit_log']}"
    # 鎖定與稽核同生同死：鎖定的那一刻（現在）要記在失敗次數表裡
    sessions = recorder.changes().get("sessions")
    assert sessions is None, f"被鎖定的登入不得建立 session：{sessions}"


@then(parsers.re(r'the failure count for "(?P<name>[^"]+)" is (?P<count>\d+)'))
def _failure_count(recorder, db, name, count):
    row = failure_row(db, name)
    assert row is not None, f"{name} 沒有失敗次數的紀錄"
    assert row[0] == int(count), f"{name} 的失敗次數應為 {count}，實際 {row[0]}"
    # 明確斷言被排除的兩張表確實寫了預期的一列：一次被接受的嘗試、一列失敗次數
    changes = assert_only_lock_tables_written(recorder)
    assert len(changes[ATTEMPTS]["added"]) == 1 and not changes[ATTEMPTS]["removed"], f"應新增 1 列嘗試次數：{changes.get(ATTEMPTS)}"
    assert len(changes[FAILURES]["added"]) == 1, f"失敗次數表應多出 1 列（新的一輪）：{changes.get(FAILURES)}"


@then(parsers.re(r'"(?P<name>[^"]+)" is not locked'))
def _not_locked(db, name):
    row = failure_row(db, name)
    assert row is not None and row[2] is None, f"{name} 不應被鎖定：{row}"


# ───────────────────────── IAM-R07：頻率限制 ─────────────────────────


@pytest.fixture
def address_client() -> TestClient:
    """來源位址固定為 ADDRESS 的用戶端（Starlette 的 `client=` 就是 ASGI scope 的 client）。"""
    return TestClient(create_app(), raise_server_exceptions=False, client=(ADDRESS, 50000))


@given(parsers.re(r"one client address has made (?P<count>\d+) sign-in attempts in the last 60 seconds"))
def _seed_attempts(db, count):
    with db.cursor() as cur:
        for i in range(int(count)):  # 5、10、…秒前：都在最近 60 秒內
            cur.execute(
                "insert into yc_v3.sign_in_attempts(client_address, attempted_at) values (%s, %s)",
                (ADDRESS, clock.now() - timedelta(seconds=5 * (i + 1))),
            )
    db.commit()


@when("that address attempts another sign-in with a correct password")
def _another_attempt(recorder, address_client, db):
    set_password(db, "Wen")
    recorder.perform(lambda: post_sign_in(address_client, "Wen", TEST_PASSWORD))
    # D-069：RATE_LIMITED 不寫任何資料。規格在這個 scenario 沒有再寫 And，所以在這裡斷言（Then 只檢查結果類別）
    assert recorder.response.status_code == 429, f"應被頻率限制（429），實際 {recorder.response.status_code}"
    assert not recorder.changes(), f"被頻率限制的請求不得寫入任何資料：{recorder.changes()}"


@pytest.fixture
def workers() -> list:
    return []


@pytest.fixture
def attempt_results() -> list:
    return []


@given(parsers.re(r"(?P<count>\d+) workers serve sign-in"))
def _workers(workers, count):
    # 每個 worker 是一個獨立的應用程式實例（各自的 router、各自的資料庫連線），唯一共用的是資料庫：
    # 就是正式環境多個 uvicorn worker 的樣子。任何只存在行程記憶體的計數都會在這裡失敗。
    workers.extend(create_app() for _ in range(int(count)))


@when(parsers.re(r"one client address makes (?P<count>\d+) attempts in 60 seconds spread over both workers"))
def _spread_attempts(db, workers, attempt_results, count):
    n = int(count)
    set_password(db, "Wen")
    barrier = threading.Barrier(n)
    results: list[int | None] = [None] * n

    def attempt(i: int) -> None:
        # 每次嘗試一個新的用戶端、輪流打到兩個 worker；同一個來源位址
        c = TestClient(workers[i % len(workers)], raise_server_exceptions=False, client=(ADDRESS, 40000 + i))
        barrier.wait(timeout=30)  # 全部就位後同時送出，讓檢查與寫入真的交錯
        results[i] = post_sign_in(c, "Wen", TEST_PASSWORD).status_code

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert all(r is not None for r in results), f"有請求沒有回應：{results}"
    attempt_results.extend(results)


@then(parsers.re(r"exactly (?P<count>\d+) attempts are evaluated"))
def _evaluated(db, attempt_results, count):
    evaluated = [r for r in attempt_results if r != 429]
    limited = [r for r in attempt_results if r == 429]
    assert len(evaluated) == int(count), f"被評估的嘗試應恰為 {count}，實際 {len(evaluated)}（回應：{sorted(attempt_results)}）"
    assert len(limited) == len(attempt_results) - int(count), f"其餘的都應是 429：{sorted(attempt_results)}"
    assert all(r == 303 for r in evaluated), f"被評估的嘗試用的是正確密碼，應全部登入成功：{sorted(attempt_results)}"
    assert attempts_for(db, ADDRESS) == int(count), "資料庫裡記下的嘗試次數應等於被評估的次數"
