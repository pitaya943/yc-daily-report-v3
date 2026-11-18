"""切換角色的資料存取：只有 SQL，沒有規則。讀取帳戶用 account_lifecycle_and_pay_settings.repo.get（同一個 Account）。"""
from __future__ import annotations

import psycopg


def set_role(conn: psycopg.Connection, account_id: int, role: str) -> None:
    """只更新角色這一欄。由呼叫端提交（與稽核同生同死）。"""
    conn.execute("update yc_v3.accounts set role = %s where id = %s", (role, account_id))
