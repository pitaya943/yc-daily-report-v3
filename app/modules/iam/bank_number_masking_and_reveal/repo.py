"""銀行帳號與發薪方式的資料存取：只有 SQL，沒有規則，也沒有加解密。"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Holder:
    """被查看或修改的帳戶。`role` 讓 access.py 的 `target` 檢查（T-304，D-115）看得到目標的角色。"""

    id: int
    name: str
    role: str
    payment_method: str  # TRANSFER／CASH
    bank_number_cipher: bytes | None


def get(conn: psycopg.Connection, account_id: int, *, lock: bool = False) -> Holder | None:
    """`lock=True` 時鎖住該列直到 transaction 結束：同一個帳戶的並行修改排隊。"""
    row = conn.execute(
        "select id, name, role, payment_method, bank_number_cipher from yc_v3.accounts where id = %s" + (" for update" if lock else ""),
        (account_id,),
    ).fetchone()
    if row is None:
        return None
    return Holder(row[0], row[1], row[2], row[3], None if row[4] is None else bytes(row[4]))


def set_cipher(conn: psycopg.Connection, account_id: int, cipher: bytes) -> None:
    conn.execute("update yc_v3.accounts set bank_number_cipher = %s where id = %s", (cipher, account_id))


def set_payment_method(conn: psycopg.Connection, account_id: int, method: str) -> None:
    conn.execute("update yc_v3.accounts set payment_method = %s where id = %s", (method, account_id))
