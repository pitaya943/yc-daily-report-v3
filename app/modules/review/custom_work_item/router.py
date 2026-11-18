"""自訂工項（REV-F03，D-118）。只有 ADMIN、OWNER。

    GET  /review/reports/{id}/custom-item   附加／取代／移除的頁面（預先填入目前的自訂工項）
    POST /review/reports/{id}/custom-item   儲存；成功回 200 與一小段 HTML，拒絕回結果類別的 status 與 JSON

做法與 T-201、T-202、T-301 相同：表單用 `parse_qs`（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；
anti-forgery token 由版型帶上（D-080）；HTMX 2 不換進 4xx，由模板自己處理（pitfall #31）。
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
from app.core.permissions import authorize
from app.core.session import get_current_actor
from app.modules.reports.submit_a_daily_report import repo as reports_repo
from app.modules.review.custom_work_item import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024


async def _read_form(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.get("/review/reports/{report_id:int}/custom-item")
def custom_item_page(
    report_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)
):
    authorize(actor, f"open the custom item form of report #{report_id}", service.ADMIN_RULE)
    report = reports_repo.get_report(conn, report_id)
    if report is None:
        raise HTTPException(status_code=404)
    item = service.current_item(report)
    context = {
        "report": report,
        "name": item.name if item else "",
        "quantity": f"{item.tenths // 10}.{item.tenths % 10}" if item else "",
        "price": str(item.price) if item else "",
        "fields": {"name": service.FIELD_NAME, "quantity": service.FIELD_QUANTITY, "price": service.FIELD_PRICE},
    }
    return render_page(request, conn, TEMPLATES, "custom_item.html", context)


@router.post("/review/reports/{report_id:int}/custom-item")
def save_custom_item(
    report_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        saved = service.save_custom_item(conn, actor, report_id, form)
    except service.ReportNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "custom_item_saved.html", {"saved": saved})
