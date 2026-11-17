"""小組分配與份額保存（REV-F02：REV-R10、REV-R11；D-111）。

## 給 T-302、T-402 用的介面（D-111）

    confirmed_quantities(conn, date_from, date_to) -> dict[int, dict[str, int]]

「計算薪資」取得已確認數量的**唯一**入口：只讀份額表（`yc_v3.report_shares`），不看目前的作業小組、不重算。
- 參數：`date_from`、`date_to` 是 `datetime.date`，含頭尾；以回報日期（`reports.report_date`）判斷，不是確認的日期。
- 回傳：`{account_id: {item_code: tenths}}`。
  * `account_id`：`accounts.id`（含已封存的帳戶：封存前送出、封存後確認仍計薪，AD-7、PAY-F03）。
  * `item_code`：附錄 A 的工項代碼（目錄工項）；`tenths`：該帳戶在期間內這個工項的總數量，**0.1 只的整數**（2.3 只 = 23）。
  * 期間內沒有任何已確認份額的帳戶不會出現（駁回或尚未確認的回報不計）；份額為 0 的工項會出現、值為 0。
- 不含自訂工項：T-302 會加上（份額 × 自訂單價，資料在 `yc_v3.report_custom_shares`）。T-402 的薪資數量只能經由這個函式取得。
- 只讀、不提交。沿用呼叫端的連線與 transaction。

## 為什麼存份額（REV-R11）

份額會因為小組成員被封存、改區域、回報被編輯而「算出」不同的數字；存下來才能保證確認時的數字就是薪資用的數字。
確認時不重新檢查成員資格：小組在送出時凍結（AD-7），封存的共同作業者仍然拿份額。
所有數量用 tenth 的整數；分配用 `app.domain.split.split`（餘數先給提交者，再依小組順序，REV-R10）。
"""
from __future__ import annotations

from datetime import date

import psycopg

from app.domain.split import split
from app.modules.reports.submit_a_daily_report.repo import Report
from app.modules.review.crew_split_and_stored_shares import repo


def store_shares(conn: psycopg.Connection, report: Report) -> None:
    """為一張回報存下份額（確認的那個 transaction 內呼叫，呼叫端已鎖住這張回報）。

    小組 = 提交者（position 0）加共同作業者（依 report_crew 的順序）。數量為 0 的工項不存（沒有列 = 0）；
    有數量的工項，每個人一列，包含份額為 0 的人。自訂工項（有的話）用同一個規則分配。
    """
    crew = [report.submitter_id] + [account_id for account_id, _ in report.crew]
    for code, tenths in sorted(report.items.items()):
        if tenths > 0:
            repo.insert_shares(conn, report.id, code, _assign(crew, split(tenths, len(crew))))
    if report.custom_tenths:
        repo.insert_custom_shares(conn, report.id, _assign(crew, split(report.custom_tenths, len(crew))))


def _assign(crew: list[int], shares: list[int]) -> list[tuple[int, int, int]]:
    return [(account_id, position, tenths) for position, (account_id, tenths) in enumerate(zip(crew, shares))]


def confirmed_quantities(conn: psycopg.Connection, date_from: date, date_to: date) -> dict[int, dict[str, int]]:
    """見模組開頭：期間內每個帳戶在已確認回報上的各工項數量（tenths）。"""
    return repo.quantities_between(conn, date_from, date_to)
