"""帳戶管理的資料存取：只有 SQL，沒有規則。"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

_COLUMNS = (
    "id, name, role, zone, big_meter, archived, insured, insurance_deduction, uninsured_rate_bp, "
    "uninsured_exempt, fixed_salary, pays_fixed_salary_every_period"
)


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    role: str
    zone: str
    big_meter: bool
    archived: bool
    insured: bool
    insurance_deduction: int
    uninsured_rate_bp: int | None  # 萬分之一：5 % = 500；None = 空白，用區域比例
    uninsured_exempt: bool
    fixed_salary: int
    pays_fixed_salary_every_period: bool


def get(conn: psycopg.Connection, account_id: int, *, lock: bool = False) -> Account | None:
    """`lock=True` 時鎖住該列直到 transaction 結束：同一個帳戶的並行修改排隊，舊值與新值才不會互相蓋掉。

    用 `for no key update`（不是 `for update`）：兩個同時的修改仍會互相等待，但不擋外鍵的 `for key share`。
    被拒絕時的 `ACCESS_DENIED` 用獨立連線寫入（audit.py），它的外鍵要對行為者的帳戶列取 key share；
    行為者對自己的帳戶動作（例如 ADMIN 改自己的區域，IAM-R20）時，這一列正是被鎖住的那一列，`for update` 會讓請求自己等自己而死結。
    """
    row = conn.execute(f"select {_COLUMNS} from yc_v3.accounts where id = %s" + (" for no key update" if lock else ""), (account_id,)).fetchone()
    return None if row is None else Account(*row)


def _list_by_role(conn: psycopg.Connection, role: str) -> list[Account]:
    """某個角色的全部帳戶（含已封存：要能復原）。西區在南區之前；同區依名稱。排序在 Python 做，不依賴資料庫的 collation。"""
    rows = conn.execute(f"select {_COLUMNS} from yc_v3.accounts where role = %s", (role,)).fetchall()
    accounts = [Account(*r) for r in rows]
    return sorted(accounts, key=lambda a: (0 if a.zone == "WEST" else 1, a.name))


def list_users(conn: psycopg.Connection) -> list[Account]:
    return _list_by_role(conn, "USER")


def list_administrators(conn: psycopg.Connection) -> list[Account]:
    """全部 ADMIN。只有 OWNER 的帳戶管理頁會列出（Q-056：ADMIN 的帳戶管理只列 USER）。"""
    return _list_by_role(conn, "ADMIN")


def name_exists(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("select 1 from yc_v3.accounts where name = %s", (name,)).fetchone() is not None


def insert(conn: psycopg.Connection, *, name: str, role: str, zone: str, big_meter: bool, password_hash: str) -> int:
    """薪資設定不在這裡送：欄位的 default 就是 D-116 的初始值（migration 0007）。"""
    return conn.execute(
        "insert into yc_v3.accounts(name, role, zone, big_meter, password_hash) values (%s, %s, %s, %s, %s) returning id",
        (name, role, zone, big_meter, password_hash),
    ).fetchone()[0]


# 可更新的欄位白名單：欄位名稱只來自這裡，不來自使用者輸入
_UPDATABLE = frozenset(
    {"zone", "big_meter", "insured", "insurance_deduction", "uninsured_rate_bp", "uninsured_exempt", "fixed_salary"}
)


def update(conn: psycopg.Connection, account_id: int, values: dict[str, object]) -> None:
    assert values and set(values) <= _UPDATABLE, values
    sets = ", ".join(f"{column} = %s" for column in values)
    conn.execute(f"update yc_v3.accounts set {sets} where id = %s", (*values.values(), account_id))


def set_archived(conn: psycopg.Connection, account_id: int, archived: bool) -> None:
    conn.execute("update yc_v3.accounts set archived = %s where id = %s", (archived, account_id))


def delete_sessions(conn: psycopg.Connection, account_id: int) -> None:
    conn.execute("delete from yc_v3.sessions where account_id = %s", (account_id,))
