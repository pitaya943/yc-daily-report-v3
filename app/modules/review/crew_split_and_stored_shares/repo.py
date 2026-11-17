"""份額表的資料存取（migration 0006：report_shares、report_custom_shares）。

只有 SQL，沒有規則；用呼叫端給的連線，**不自己提交**（份額與確認同一個 transaction，見 service.py）。
"""
from __future__ import annotations

from datetime import date

import psycopg


def insert_shares(conn: psycopg.Connection, report_id: int, item_code: str, shares: list[tuple[int, int, int]]) -> None:
    """一個工項的份額。shares = [(account_id, position, tenths)]，position 0 是提交者。"""
    for account_id, position, tenths in shares:
        conn.execute(
            "insert into yc_v3.report_shares(report_id, item_code, account_id, position, tenths) values (%s, %s, %s, %s, %s)",
            (report_id, item_code, account_id, position, tenths),
        )


def insert_custom_shares(conn: psycopg.Connection, report_id: int, shares: list[tuple[int, int, int]]) -> None:
    """自訂工項的份額。shares = [(account_id, position, tenths)]。"""
    for account_id, position, tenths in shares:
        conn.execute(
            "insert into yc_v3.report_custom_shares(report_id, account_id, position, tenths) values (%s, %s, %s, %s)",
            (report_id, account_id, position, tenths),
        )


def quantities_between(conn: psycopg.Connection, date_from: date, date_to: date) -> dict[int, dict[str, int]]:
    """期間內（含頭尾）每個帳戶在已確認回報上的各工項數量 {account_id: {item_code: tenths}}。

    只讀 `report_shares`；`reports` 只用來取回報日期與狀態。狀態條件是保險：份額只在 CONFIRMED 時存在，
    編輯會刪掉它（RPT-R12），這裡仍不信任「一定同步」。
    """
    rows = conn.execute(
        "select s.account_id, s.item_code, sum(s.tenths)::integer "
        "from yc_v3.report_shares s join yc_v3.reports r on r.id = s.report_id "
        "where r.status = 'CONFIRMED' and r.report_date between %s and %s "
        "group by s.account_id, s.item_code order by s.account_id, s.item_code",
        (date_from, date_to),
    ).fetchall()
    out: dict[int, dict[str, int]] = {}
    for account_id, item_code, tenths in rows:
        out.setdefault(account_id, {})[item_code] = tenths
    return out
