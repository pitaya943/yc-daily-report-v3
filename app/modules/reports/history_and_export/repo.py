"""歷史的額外查詢（只有 SQL）。回報本身的讀取重用 T-201 的 `list_reports`，這裡不複製。

只放 `list_reports` 沒有的兩件事：依帳戶名稱找帳戶（帳戶篩選要驗證「名稱在清單內」）、取得帳戶的施工區域
（區域篩選依「提交者的區域」）。
"""
from __future__ import annotations

import psycopg


def find_user_by_name(conn: psycopg.Connection, name: str) -> int | None:
    """名稱對得上的 USER 帳戶 id（含已封存者：封存帳戶的歷史仍要查得到）；ADMIN、OWNER 不填日報，不在清單內。"""
    row = conn.execute("select id from yc_v3.accounts where name = %s and role = 'USER'", (name,)).fetchone()
    return None if row is None else row[0]


def zones_by_account(conn: psycopg.Connection, account_ids: set[int]) -> dict[int, str]:
    if not account_ids:
        return {}
    rows = conn.execute("select id, zone from yc_v3.accounts where id = any(%s)", (sorted(account_ids),)).fetchall()
    return {r[0]: r[1] for r in rows}
