"""自訂工項的資料存取（`reports` 的 custom_name、custom_tenths、custom_price，migration 0005；D-086）。

只有 SQL，沒有規則；用呼叫端的連線，**不自己提交**（自訂工項、狀態、份額作廢與稽核同一個 transaction，見 service.py）。
三個欄位同時為 null 或同時有值是資料庫的 check 約束（D-086），這裡一次寫三個、一次清三個，不分開更新。
"""
from __future__ import annotations

from datetime import datetime

import psycopg


def set_custom_item(conn: psycopg.Connection, report_id: int, name: str, tenths: int, price: int, now: datetime) -> None:
    """附加或取代：每張回報最多一個自訂工項，所以取代就是覆寫這三個欄位（REV-R20）。"""
    conn.execute(
        "update yc_v3.reports set custom_name = %s, custom_tenths = %s, custom_price = %s, updated_at = %s where id = %s",
        (name, tenths, price, now, report_id),
    )


def clear_custom_item(conn: psycopg.Connection, report_id: int, now: datetime) -> None:
    """移除（REV-R21）：三個欄位同時清成 null。"""
    conn.execute(
        "update yc_v3.reports set custom_name = null, custom_tenths = null, custom_price = null, updated_at = %s where id = %s",
        (now, report_id),
    )
