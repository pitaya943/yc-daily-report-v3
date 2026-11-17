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
    """
    row = conn.execute("select password_hash from yc_v3.accounts where id = %s for update", (account_id,)).fetchone()
    return None if row is None else row[0]


def find_account(conn: psycopg.Connection, account_id: int) -> AccountRow | None:
    row = conn.execute("select id, name, role, archived from yc_v3.accounts where id = %s", (account_id,)).fetchone()
    return None if row is None else AccountRow(*row)


def set_password_hash(conn: psycopg.Connection, account_id: int, password_hash: str) -> None:
    """只更新密碼雜湊這一欄。由呼叫端提交（與稽核同生同死）。"""
    conn.execute("update yc_v3.accounts set password_hash = %s where id = %s", (password_hash, account_id))
