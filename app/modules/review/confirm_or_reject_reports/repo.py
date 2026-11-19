"""確認、駁回與佇列的資料存取（reports 的 reviewer_id、reviewed_at 欄位來自 migration 0006）。

只有 SQL；用呼叫端的連線，**不自己提交**。鎖與回報本身的讀取用 `report_lifecycle.repo.lock_report`（不另寫一份）。
"""
from __future__ import annotations

from datetime import datetime

import psycopg

from app.modules.reports.submit_a_daily_report import repo as reports_repo


def mark_reviewed(conn: psycopg.Connection, report_id: int, status: str, reviewer_id: int, now: datetime) -> None:
    """確認或駁回：狀態、審核者、審核時間（同時更新 updated_at）。呼叫端已鎖住這張回報並確認它是 PENDING。"""
    conn.execute(
        "update yc_v3.reports set status = %s, reviewer_id = %s, reviewed_at = %s, updated_at = %s where id = %s",
        (status, reviewer_id, now, now, report_id),
    )


def pending_reports(conn: psycopg.Connection, catalogues: tuple[str, ...]) -> list[reports_repo.Report]:
    """這幾個工項組的 PENDING 回報，依工項組、日期（舊到新）、id 排序：先送出的先審。

    工項組是送出當時記下的（AD-4），所以大表與一般的分野不會因為帳戶後來改區域或大表旗標而變。
    """
    found = reports_repo.list_reports(conn, status="PENDING")
    wanted = [r for r in found if r.catalogue in catalogues]
    return sorted(wanted, key=lambda r: (catalogues.index(r.catalogue), r.report_date, r.id))
