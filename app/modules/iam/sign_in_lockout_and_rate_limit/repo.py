"""登入鎖定與頻率限制的資料存取：只有 SQL，沒有規則（規則在 service.py）。

兩種 advisory lock 都是「交易層級」（`pg_advisory_xact_lock`）：交易結束（提交或回滾）自動釋放，不會因為例外而漏放。
- 帳戶：兩個 int 的形式 `(classid, account_id)`，同一個帳戶的「讀狀態、決定、寫狀態」串成一條線。
- 位址：單一 bigint 的形式，key 是位址文字的雜湊。兩種形式在 PostgreSQL 裡是不同的 key 空間，不會互撞。
雜湊碰撞只會讓兩個不相干的位址偶爾互相等待，不影響正確性。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

# advisory lock 的 classid：只要求在這個應用程式內不與別的用途重複
_ACCOUNT_LOCK_CLASS = 1002


@dataclass(frozen=True)
class FailureState:
    fail_count: int
    last_failed_at: datetime
    locked_at: datetime | None


def lock_account(conn: psycopg.Connection, account_id: int) -> None:
    conn.execute("select pg_advisory_xact_lock(%s, %s)", (_ACCOUNT_LOCK_CLASS, account_id))


def lock_address(conn: psycopg.Connection, address: str) -> None:
    conn.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (address,))


def get_failure_state(conn: psycopg.Connection, account_id: int) -> FailureState | None:
    row = conn.execute(
        "select fail_count, last_failed_at, locked_at from yc_v3.sign_in_failures where account_id = %s", (account_id,)
    ).fetchone()
    return None if row is None else FailureState(*row)


def put_failure_state(conn: psycopg.Connection, account_id: int, state: FailureState) -> None:
    conn.execute(
        "insert into yc_v3.sign_in_failures(account_id, fail_count, last_failed_at, locked_at) values (%s, %s, %s, %s) "
        "on conflict (account_id) do update set fail_count = excluded.fail_count, "
        "last_failed_at = excluded.last_failed_at, locked_at = excluded.locked_at",
        (account_id, state.fail_count, state.last_failed_at, state.locked_at),
    )


def clear_failure_state(conn: psycopg.Connection, account_id: int) -> None:
    conn.execute("delete from yc_v3.sign_in_failures where account_id = %s", (account_id,))


def count_attempts_since(conn: psycopg.Connection, address: str, since: datetime) -> int:
    """`since` 之後（不含）的嘗試次數；剛好在 `since` 的那一次已經過期，不算。"""
    return conn.execute(
        "select count(*) from yc_v3.sign_in_attempts where client_address = %s and attempted_at > %s", (address, since)
    ).fetchone()[0]


def add_attempt_and_prune(conn: psycopg.Connection, address: str, now: datetime, since: datetime) -> None:
    """記下這次嘗試，同時刪掉這個位址已過期的列（表的大小因此有上限）。"""
    conn.execute("delete from yc_v3.sign_in_attempts where client_address = %s and attempted_at <= %s", (address, since))
    conn.execute("insert into yc_v3.sign_in_attempts(client_address, attempted_at) values (%s, %s)", (address, now))
