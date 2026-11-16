"""歷史與匯出（RPT-F03，D-057、D-090）。

    GET /reports/history                      USER：自己送出與共同作業的回報
    GET /reports/history/export               同上的 .xlsx
    GET /review/history/ordinary              管理員：一般（WEST、SOUTH）回報
    GET /review/history/ordinary/export
    GET /review/history/big-meter             管理員：大表回報
    GET /review/history/big-meter/export

篩選條件放在查詢字串（date_from、date_to、zone、account、has_custom）；匯出用同一組條件，所以「匯出」恰是
畫面上看到的那些列。權限先於驗證：沒有權限的人不會因為篩選值而得到不同的回應。
拒絕仍是 JSON（結果類別的單一出口，outcomes.py）；HTMX 2 不換進 4xx，由 templates/history.html 取出
`message` 顯示完整字串，不修改 base.html。端點用 `def`（pitfall #28）；讀查詢字串不需要 `Form()`（pitfall #27）。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from app.core import audit
from app.core.actor import Actor
from app.core.clock import clock
from app.core.db import get_db
from app.core.pages import render_page
from app.core.permissions import authorize
from app.core.session import get_current_actor
from app.modules.reports.history_and_export import export, service
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo
from app.modules.reports.submit_a_daily_report.repo import Report

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"

_TITLES = {"user": "我的日報歷史", "ordinary": "一般日報歷史", "big-meter": "大表日報歷史"}
_PATHS = {"user": "/reports/history", "ordinary": "/review/history/ordinary", "big-meter": "/review/history/big-meter"}


def _authorize_and_filter(request: Request, actor: Actor, conn: psycopg.Connection, page: str) -> service.Filters:
    if page == "user":
        authorize(actor, "open my report history", service.USER_RULE)
        allowed = service.USER_PARAMS
    else:
        authorize(actor, f"open the {page} report history", service.ADMIN_RULE)
        allowed = service.ADMIN_PARAMS
    return service.parse_filters(conn, list(request.query_params.multi_items()), allowed)


def _reports(conn: psycopg.Connection, actor: Actor, page: str, f: service.Filters) -> list[Report]:
    return service.user_history(conn, actor, f) if page == "user" else service.admin_history(conn, page, f)


def _show(request: Request, conn: psycopg.Connection, actor: Actor, page: str):
    f = _authorize_and_filter(request, actor, conn, page)
    reports = _reports(conn, actor, page, f)
    viewer = actor if page == "user" else None
    rows = [
        {
            "id": r.id,
            "date": r.report_date.isoformat(),
            "account": r.submitter_name,
            "label": service.role_label(r, viewer),
            "crew": "、".join(name for _, name in r.crew),
            "items": service.item_texts(r),
            "custom": service.custom_text(r),
            "status": service.STATUS_WORDING[r.status],
        }
        for r in reports
    ]
    query = f.query()
    context = {
        "page": page,
        "title": _TITLES[page],
        "path": _PATHS[page],
        "is_admin": page != "user",
        "rows": rows,
        "filters": query,
        "export_url": _PATHS[page] + "/export" + (("?" + urlencode(query)) if query else ""),
        "nav": [(k, _TITLES[k], _PATHS[k]) for k in (("ordinary", "big-meter") if page != "user" else ())],
        "zones": sorted(service.ZONES),
        "status_wording": service.STATUS_WORDING,
    }
    return render_page(request, conn, TEMPLATES, "history.html", context)


def _catalogues_for_export(conn: psycopg.Connection, actor: Actor, page: str, reports: list[Report]) -> list[str]:
    """匯出的工項欄位。管理員頁是該頁涵蓋的工項組；USER 是自己目前的工項組，加上看得到的回報所屬的其他工項組
    （帳戶換過區域時，舊回報的工項才不會在匯出裡消失）。"""
    if page != "user":
        return list(service.ADMIN_PAGES[page])
    account = repo.get_account(conn, actor.id)
    present = {cat.catalogue_name_for(account.zone, account.big_meter)} | {r.catalogue for r in reports}
    return [n for n in cat.CATALOGUE_NAMES if n in present]


def _export(request: Request, conn: psycopg.Connection, actor: Actor, page: str):
    f = _authorize_and_filter(request, actor, conn, page)
    reports = _reports(conn, actor, page, f)
    body = export.build_workbook(reports, _catalogues_for_export(conn, actor, page, reports))
    # 稽核在檔案組好之後、回應之前寫入並提交：失敗的匯出不留稽核；篩選無效時前面已丟出 INVALID，不會走到這裡
    condition = urlencode(f.query()) or "無篩選"
    audit.write(actor, "EXPORT", f"匯出日報歷史（{_TITLES[page]}，{len(reports)} 列；{condition}）", conn=conn)
    conn.commit()
    filename = f"report-history-{clock.now().date().isoformat()}.xlsx"
    return Response(
        body,
        media_type=export.CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


@router.get("/reports/history")
def user_history(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _show(request, conn, actor, "user")


@router.get("/reports/history/export")
def user_history_export(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _export(request, conn, actor, "user")


@router.get("/review/history/ordinary")
def ordinary_history(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _show(request, conn, actor, "ordinary")


@router.get("/review/history/ordinary/export")
def ordinary_history_export(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _export(request, conn, actor, "ordinary")


@router.get("/review/history/big-meter")
def big_meter_history(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _show(request, conn, actor, "big-meter")


@router.get("/review/history/big-meter/export")
def big_meter_history_export(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return _export(request, conn, actor, "big-meter")
