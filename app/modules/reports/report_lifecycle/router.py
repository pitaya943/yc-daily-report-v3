"""回報的編輯與刪除（RPT-F02，D-057、D-090）。USER 與管理員用同一組端點，權限在伺服器依角色與回報狀態判斷。

    GET  /reports/{id}/edit     編輯頁（預先填入目前的內容）
    POST /reports/{id}          儲存編輯；成功回 200 與一小段 HTML，拒絕回結果類別的 status 與 JSON
    POST /reports/{id}/delete   永久刪除；成功回 200 與一小段 HTML

與 T-201 相同的做法：表單用 `parse_qs` 解析（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；
anti-forgery token 由版型的 hx-headers 帶上（D-080）；HTMX 2 不換進 4xx，所以模板自己處理（不修改 base.html）。
`{report_id:int}` 讓 `/reports/history` 這類固定路徑（T-203）不會被當成回報編號。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.actor import Actor
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError
from app.core.pages import render_page
from app.core.session import get_current_actor
from app.modules.reports.report_lifecycle import service
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo
from app.modules.reports.submit_a_daily_report import service as submit

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024  # 與 T-201 相同：37 個工項加 6 位共同作業者遠小於這個大小


async def _read_form(request: Request) -> dict[str, list[str]]:
    """請求主體 → {欄位: [值…]}（同名欄位保留全部值與順序）。空白值保留。"""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


def _tenths(value: int) -> str:
    return f"{value // 10}.{value % 10}"


@router.get("/reports/{report_id:int}/edit")
def edit_page(
    report_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)
):
    try:
        report = service.load_for_change(conn, actor, report_id, "open the report edit form")
    except service.ReportNotFound:
        raise HTTPException(status_code=404) from None
    submitter = repo.get_account(conn, report.submitter_id)
    slots = [account_id for account_id, _ in report.crew] + [None] * submit.MAX_COLLABORATORS
    context = {
        "report": report,
        "submitter": submitter,
        "rows": [(item, _tenths(report.items[item.code]) if item.code in report.items else "") for item in cat.catalogue(report.catalogue)],
        "collaborators": repo.eligible_collaborators(conn, submitter),
        "slots": slots[: submit.MAX_COLLABORATORS],
        "max_collaborators": submit.MAX_COLLABORATORS,
        "is_admin_edit": actor.id != report.submitter_id,
    }
    return render_page(request, conn, TEMPLATES, "report_edit.html", context)


@router.post("/reports/{report_id:int}")
def edit(
    report_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        edited = service.edit_report(conn, actor, report_id, form)
    except service.ReportNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "report_updated.html", {"edited": edited})


@router.post("/reports/{report_id:int}/delete")
def delete(
    report_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)
):
    try:
        deleted = service.delete_report(conn, actor, report_id)
    except service.ReportNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "report_deleted.html", {"deleted": deleted})
