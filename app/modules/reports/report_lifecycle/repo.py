"""回報生命週期（RPT-F02）專用的資料存取：只有 T-201 的 repo.py 沒有的幾個查詢。

回報本身的讀寫（get_report、replace_report_content、delete_report…）直接用
`app.modules.reports.submit_a_daily_report.repo`，不複製。這裡不自己提交，由呼叫端決定 transaction 範圍。
"""
from __future__ import annotations

import psycopg

from app.modules.reports.submit_a_daily_report import repo as reports_repo


def lock_report(conn: psycopg.Connection, report_id: int) -> reports_repo.Report | None:
    """鎖住這張回報的那一列直到 transaction 結束，再讀出來；不存在回傳 None。

    為什麼要鎖：編輯與刪除都是「先看狀態、再決定能不能做」。沒有鎖時，提交者的編輯可以和管理員的確認同時進行：
    兩邊都先看到 PENDING，結果是已確認的回報被提交者改掉。先鎖列、再讀狀態，兩個請求就排隊，後來的看見新的狀態。
    （確認／駁回由 M3 的 REV feature 實作，之後它也要用同樣的鎖；這裡先把自己這一側做對。）
    """
    locked = conn.execute("select id from yc_v3.reports where id = %s for update", (report_id,)).fetchone()
    return None if locked is None else reports_repo.get_report(conn, report_id)


def account_names(conn: psycopg.Connection, ids: list[int]) -> dict[int, str]:
    """帳戶 id → 名稱（稽核說明要寫共同作業者的名稱）。"""
    if not ids:
        return {}
    rows = conn.execute("select id, name from yc_v3.accounts where id = any(%s)", (ids,)).fetchall()
    return {r[0]: r[1] for r in rows}
