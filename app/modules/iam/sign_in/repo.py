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


def lock_password_hash(conn: psycopg.Connection, account_id: int) -> str | None:
    """重新讀取帳戶目前的密碼雜湊，並鎖住這一列直到交易結束（D-141，IAM-R33 的競爭）。

    與改密碼／重設用的是同一種鎖（`for no key update`，見 password_change_and_reset/repo.py）：兩者互相等待，所以
    「登入發出 session」與「密碼輪替並結束 session」不會交錯——登入先拿到鎖，輪替就等到登入提交，之後的刪除看得到這個新 session；
    輪替先拿到鎖，登入就等到輪替提交，之後讀到的是新的雜湊，與比對時的不同而被拒絕。
    不用 `for update`：它會擋住外鍵的 `for key share`（`sign_in_failures` 寫入需要），與同時進行的登入失敗互相等待而死結。
    """
    row = conn.execute("select password_hash from yc_v3.accounts where id = %s for no key update", (account_id,)).fetchone()
    return None if row is None else row[0]
