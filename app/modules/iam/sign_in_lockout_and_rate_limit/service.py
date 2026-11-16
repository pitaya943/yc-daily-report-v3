"""登入鎖定與頻率限制的規則（IAM-F02）。

## 規則

- IAM-R04：同一個帳戶密碼錯誤滿 5 次，鎖定 15 分鐘。鎖定中，連正確的密碼也一律 `LOCKED`。
  鎖定的起點是第 5 次錯誤的那一刻；剛好滿 15 分鐘就解除（14 分 59 秒仍鎖定）。
- IAM-R05：失敗次數在三種情況下歸零：登入成功、鎖定結束、距離最後一次失敗滿 15 分鐘沒有新的失敗。
  鎖定本來就是在最後一次失敗時開始，所以「鎖定結束」與「安靜滿 15 分鐘」是同一個時間點。
- IAM-R06：次數依帳戶計，與來源位址無關。
- IAM-R07：同一個來源位址每 60 秒最多 10 次被評估的嘗試；第 11 次 `RATE_LIMITED`。

## 什麼會寫資料（D-069）

| 情況 | 寫入 |
| --- | --- |
| `RATE_LIMITED` | 不寫任何東西 |
| 帳戶鎖定中（連正確的密碼也是） | 不寫任何東西：不延長鎖定、不累計次數、不記嘗試 |
| 欄位不合（`INVALID`） | 不寫任何東西 |
| 其他被評估的嘗試 | 一列嘗試（`sign_in_attempts`） |
| 帳戶存在、密碼錯誤 | 再加上失敗次數（`sign_in_failures`）；第 5 次同時寫 `ACCOUNT_LOCKOUT`（actor SYSTEM） |
| 登入成功 | 失敗次數整列刪除 |

## 取捨

- 不記「被鎖定拒絕」的嘗試：那種請求不做 scrypt，成本只有兩次索引查詢，記下來只會讓被鎖定的人更久無法恢復，
  而且違反「鎖定期間的拒絕不寫資料」。代價是對一個已鎖定的帳戶，單一位址不受每分鐘 10 次的限制；
  但那個帳戶本來就不能登入，其他帳戶不受影響（IAM-R06）。
- 先做「只讀」的頻率檢查（便宜），到要做 scrypt 之前才在鎖內「再檢查並記下」：
  只讀檢查擋掉大部分被限制的請求而不取鎖；鎖內的再檢查才是 worker 之間真正的互斥。
- scrypt 在帳戶鎖之外執行（約零點幾秒，不能握著鎖）；之後在鎖內重讀狀態再決定，
  所以兩個 worker 同時送出第 5 次錯誤，只會有一個寫出 `ACCOUNT_LOCKOUT`。
- 位址取自 ASGI 的 `client`。在反向代理後面時，要由 uvicorn 的 `--proxy-headers`／`--forwarded-allow-ips`
  把真實位址放進 `client`；這裡不自己讀 `X-Forwarded-For`（任何人都能偽造那個標頭來繞過限制）。
"""
from __future__ import annotations

from datetime import timedelta

import psycopg

from app.core import audit
from app.core.actor import SYSTEM
from app.core.clock import clock
from app.core.outcomes import Outcome, OutcomeError
from app.modules.iam.sign_in_lockout_and_rate_limit import repo
from app.modules.iam.sign_in_lockout_and_rate_limit.repo import FailureState

# spec/appendix-b-fields.md「登入密碼」，逐字照抄
MSG_LOCKED = "密碼錯誤次數過多，請在 15 分鐘後再試"

MAX_FAILURES = 5
LOCK_DURATION = timedelta(minutes=15)
QUIET_PERIOD = timedelta(minutes=15)
RATE_WINDOW = timedelta(seconds=60)
MAX_ATTEMPTS_PER_WINDOW = 10


def _is_locked(state: FailureState | None) -> bool:
    return state is not None and state.locked_at is not None and clock.now() - state.locked_at < LOCK_DURATION


def _effective_count(state: FailureState | None) -> int:
    """距離最後一次失敗滿安靜期（含剛好滿）就是新的一輪，次數視為 0。"""
    if state is None or clock.now() - state.last_failed_at >= QUIET_PERIOD:
        return 0
    return state.fail_count


# ───────────────────────── 頻率限制（IAM-R07）─────────────────────────


def ensure_not_rate_limited(conn: psycopg.Connection, address: str) -> None:
    """只讀的快速檢查：超過就 RATE_LIMITED，不寫任何東西。真正的互斥在 `record_attempt`。"""
    count = repo.count_attempts_since(conn, address, clock.now() - RATE_WINDOW)
    conn.rollback()  # 不留下開啟的交易
    if count >= MAX_ATTEMPTS_PER_WINDOW:
        raise OutcomeError(Outcome.RATE_LIMITED)


def record_attempt(conn: psycopg.Connection, address: str) -> None:
    """在位址的鎖內「檢查並記下」這一次嘗試，立刻提交；超過就 RATE_LIMITED 並回滾（不寫任何東西）。

    檢查與寫入在同一把鎖內，所以兩個 worker 同時送出第 10、11 次時，只有一個會被接受。
    """
    now = clock.now()
    since = now - RATE_WINDOW
    repo.lock_address(conn, address)
    if repo.count_attempts_since(conn, address, since) >= MAX_ATTEMPTS_PER_WINDOW:
        conn.rollback()
        raise OutcomeError(Outcome.RATE_LIMITED)
    repo.add_attempt_and_prune(conn, address, now, since)
    conn.commit()


# ───────────────────────── 鎖定（IAM-R04～R06）─────────────────────────


def ensure_not_locked(conn: psycopg.Connection, account_id: int) -> None:
    """只讀：鎖定中就 LOCKED（連正確的密碼也是），不寫任何東西、不做 scrypt。"""
    locked = _is_locked(repo.get_failure_state(conn, account_id))
    conn.rollback()
    if locked:
        raise OutcomeError(Outcome.LOCKED, MSG_LOCKED)


def record_failure(conn: psycopg.Connection, account_id: int, account_name: str) -> None:
    """密碼錯誤：在帳戶的鎖內累計；第 5 次同時鎖定並寫 ACCOUNT_LOCKOUT，然後提交。

    - 鎖內重讀狀態：scrypt 期間可能已有別的 worker 鎖定了這個帳戶，這時什麼都不寫，直接 LOCKED。
    - 第 5 次的回應就是 LOCKED（規格：「The fifth failure locks the account」要求第 5 次就拒絕為 LOCKED）。
    """
    repo.lock_account(conn, account_id)
    state = repo.get_failure_state(conn, account_id)
    if _is_locked(state):
        conn.rollback()
        raise OutcomeError(Outcome.LOCKED, MSG_LOCKED)
    now = clock.now()
    count = _effective_count(state) + 1
    locks = count >= MAX_FAILURES
    repo.put_failure_state(conn, account_id, FailureState(fail_count=count, last_failed_at=now, locked_at=now if locks else None))
    if locks:
        # 稽核與鎖定寫在同一個交易：同生同死。行為者是 SYSTEM（不是被鎖的帳戶，也不是任何登入者）
        audit.write(SYSTEM, "ACCOUNT_LOCKOUT", f"帳戶 {account_name} 密碼錯誤滿 {MAX_FAILURES} 次，鎖定 15 分鐘", conn=conn)
    conn.commit()
    if locks:
        raise OutcomeError(Outcome.LOCKED, MSG_LOCKED)


def begin_success(conn: psycopg.Connection, account_id: int) -> None:
    """登入成功前，在帳戶的鎖內最後確認一次沒有被鎖定，然後清掉失敗次數（IAM-R05）。

    與 `record_failure` 同一把鎖：scrypt 期間別的 worker 剛好鎖定了這個帳戶時，這次成功不算數。
    呼叫端接著在同一個交易發出 session 並提交（失敗次數的清除與 session 同生同死）。
    """
    repo.lock_account(conn, account_id)
    if _is_locked(repo.get_failure_state(conn, account_id)):
        conn.rollback()
        raise OutcomeError(Outcome.LOCKED, MSG_LOCKED)
    repo.clear_failure_state(conn, account_id)
