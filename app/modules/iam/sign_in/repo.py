"""登入用的資料存取：只有 SQL，沒有規則。"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

# 群組 → 篩選條件。條件是這裡的常數，不是使用者輸入拼出來的字串（群組先經過 service 的白名單檢查）。
_GROUP_FILTER = {
    "admin": "role in ('ADMIN', 'OWNER')",
    "west": "role = 'USER' and zone = 'WEST'",
    "south": "role = 'USER' and zone = 'SOUTH'",
}


@dataclass(frozen=True)
class AccountRow:
    id: int
    role: str
    archived: bool
    password_hash: str | None


def names_in_group(conn: psycopg.Connection, group: str) -> list[str]:
    """群組內未封存的帳戶名稱（IAM-R01）。排序用 Python 做，不依賴資料庫的 collation。"""
    rows = conn.execute(f"select name from yc_v3.accounts where not archived and {_GROUP_FILTER[group]}").fetchall()
    return sorted(r[0] for r in rows)


def find_account(conn: psycopg.Connection, name: str) -> AccountRow | None:
    row = conn.execute("select id, role, archived, password_hash from yc_v3.accounts where name = %s", (name,)).fetchone()
    return None if row is None else AccountRow(*row)
