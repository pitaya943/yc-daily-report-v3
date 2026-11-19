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
    確認／駁回（M3 的 REV-F01，`review/confirm_or_reject_reports/service.py`）呼叫的就是這個函式：兩邊用同一把鎖。
    """
    locked = conn.execute("select id from yc_v3.reports where id = %s for update", (report_id,)).fetchone()
    return None if locked is None else reports_repo.get_report(conn, report_id)


def account_names(conn: psycopg.Connection, ids: list[int]) -> dict[int, str]:
    """帳戶 id → 名稱（稽核說明要寫共同作業者的名稱）。"""
    if not ids:
        return {}
    rows = conn.execute("select id, name from yc_v3.accounts where id = any(%s)", (ids,)).fetchall()
    return {r[0]: r[1] for r in rows}


def discard_review(conn: psycopg.Connection, report_id: int) -> None:
    """回報回到 PENDING 時，丟掉上一次審核的結果（RPT-R12；T-301，D-085）：刪除已存的份額，並清掉審核者與審核時間。

    CONFIRMED 的回報被管理員編輯時，份額必須作廢：份額是依「確認當下」的數量與小組算的，內容改了就不再成立；
    不刪就會留下與內容不符的份額，薪資也會讀到它（份額是已確認數量的唯一來源）。
    REJECTED 的回報被編輯時沒有份額，但審核者也要清掉：PENDING 的回報沒有審核者。
    呼叫端已用 `lock_report` 鎖住這張回報；不自己提交。
    """
    conn.execute("delete from yc_v3.report_shares where report_id = %s", (report_id,))
    conn.execute("delete from yc_v3.report_custom_shares where report_id = %s", (report_id,))
    conn.execute("update yc_v3.reports set reviewer_id = null, reviewed_at = null where id = %s", (report_id,))
