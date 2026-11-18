"""密碼變更與重設用的資料存取：只有 SQL，沒有規則。"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class AccountRow:
    id: int
    name: str
    role: str
    archived: bool


def lock_password_hash(conn: psycopg.Connection, account_id: int) -> str | None:
    """讀取帳戶目前的密碼雜湊，並鎖住這一列直到 transaction 結束。

    鎖的目的：「驗證目前密碼」與「寫入新密碼」之間不能被另一個同時進行的變更插進來，
    否則兩個同時送出的請求都能用同一個舊密碼通過驗證（TOCTOU）。

    用 `for no key update`（不是 `for update`）：與 `update ... set password_hash` 取得的鎖相同，兩個同時的變更仍會互相等待；
    但不擋外鍵的 `for key share`。登入的失敗次數表（`sign_in_failures.account_id` 外鍵）寫入時需要 key share，
    錯誤的目前密碼（IAM-R34）會在握著這把鎖時寫那張表，用 `for update` 會讓它與同時進行的登入失敗互相等待而死結。
    """
    row = conn.execute("select password_hash from yc_v3.accounts where id = %s for no key update", (account_id,)).fetchone()
    return None if row is None else row[0]


def find_account(conn: psycopg.Connection, account_id: int) -> AccountRow | None:
    row = conn.execute("select id, name, role, archived from yc_v3.accounts where id = %s", (account_id,)).fetchone()
    return None if row is None else AccountRow(*row)


def set_password_hash(conn: psycopg.Connection, account_id: int, password_hash: str) -> None:
    """只更新密碼雜湊這一欄。由呼叫端提交（與稽核同生同死）。"""
    conn.execute("update yc_v3.accounts set password_hash = %s where id = %s", (password_hash, account_id))


def end_other_sessions(conn: psycopg.Connection, account_id: int, keep_token_hash: str) -> int:
    """結束同一個帳戶「除了 `keep_token_hash` 以外」的所有 session（IAM-R33，自己改密碼）。只動這個帳戶。由呼叫端提交。"""
    return conn.execute("delete from yc_v3.sessions where account_id = %s and token_hash <> %s", (account_id, keep_token_hash)).rowcount


def end_all_sessions(conn: psycopg.Connection, account_id: int) -> int:
    """結束這個帳戶的全部 session（IAM-R33，被管理員重設）。只動這個帳戶。由呼叫端提交。"""
    return conn.execute("delete from yc_v3.sessions where account_id = %s", (account_id,)).rowcount
