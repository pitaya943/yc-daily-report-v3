"""確認或駁回回報（REV-F01，D-057、D-118）。只有 ADMIN、OWNER。

    GET  /review                         落地頁：兩個確認佇列與兩個歷史頁的連結
    GET  /review/queue/ordinary          一般（WEST、SOUTH）的 PENDING 回報，依區域分組
    GET  /review/queue/big-meter         大表的 PENDING 回報
    POST /review/reports/confirm         確認（單筆與批次共用：表單帶一或多個 id）
    POST /review/reports/reject          駁回（同上）
    POST /review/reports/{id}/unconfirm  一律 CONFLICT（REV-R03）

做法與 T-201、T-202 相同：表單用 `parse_qs`（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；
anti-forgery token 由版型帶上（D-080）；HTMX 2 不換進 4xx，由模板自己處理（pitfall #31）。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, Depends, Request

from app.core.actor import Actor
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError
from app.core.pages import render_page
from app.core.permissions import authorize
from app.core.session import get_current_actor
from app.modules.reports.history_and_export import service as history
from app.modules.review.confirm_or_reject_reports import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024  # 200 個 id 遠小於這個大小

_QUEUE_TITLES = {"ordinary": "一般確認佇列", "big-meter": "大表確認佇列"}
_ZONE_TITLES = {"WEST": "WEST", "SOUTH": "SOUTH", "BIG_METER": "大表"}


async def _read_form(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.get("/review")
def landing(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    authorize(actor, "open the review landing page", service.ADMIN_RULE)
    links = [
        ("一般確認佇列", "/review/queue/ordinary"),
        ("大表確認佇列", "/review/queue/big-meter"),
        ("一般日報歷史", "/review/history/ordinary"),
        ("大表日報歷史", "/review/history/big-meter"),
    ]
    return render_page(request, conn, TEMPLATES, "review.html", {"links": links})


def _show_queue(request: Request, conn: psycopg.Connection, actor: Actor, name: str):
    authorize(actor, f"open the {name} confirmation queue", service.ADMIN_RULE)
    groups = [
        {
            "key": catalogue,
            "title": _ZONE_TITLES[catalogue],
            "rows": [
                {
                    "id": r.id,
                    "date": r.report_date.isoformat(),
                    "account": r.submitter_name,
                    "crew": "、".join(n for _, n in r.crew),
                    "items": history.item_texts(r),
                    "custom": history.custom_text(r),
                }
                for r in reports
            ],
        }
        for catalogue, reports in service.queue(conn, name)
    ]
    context = {"name": name, "title": _QUEUE_TITLES[name], "groups": groups}
    return render_page(request, conn, TEMPLATES, "queue.html", context)


@router.get("/review/queue/ordinary")
def ordinary_queue(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _show_queue(request, conn, actor, "ordinary")


@router.get("/review/queue/big-meter")
def big_meter_queue(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _show_queue(request, conn, actor, "big-meter")


def _review(request: Request, actor: Actor, form: dict[str, list[str]], conn: psycopg.Connection, decision: str):
    service.authorize_review(actor, decision)  # 權限先於欄位驗證：沒有權限的人不論送什麼，只會得到 FORBIDDEN
    result = service.review_reports(conn, actor, service.parse_ids(form), decision)
    return render_page(request, conn, TEMPLATES, "review_result.html", {"result": result})


@router.post("/review/reports/confirm")
def confirm(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    return _review(request, actor, form, conn, "CONFIRMED")


@router.post("/review/reports/reject")
def reject(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    return _review(request, actor, form, conn, "REJECTED")


@router.post("/review/reports/{report_id:int}/unconfirm")
def unconfirm(report_id: int, actor: Actor = Depends(get_current_actor)):
    service.unconfirm(actor, report_id)
