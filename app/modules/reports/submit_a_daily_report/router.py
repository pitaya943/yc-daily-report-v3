"""日報頁與送出（RPT-F01，D-057、D-090）。

    GET  /reports    USER 登入後的落地頁：日報表單（USER 以外 → FORBIDDEN）
    POST /reports    送出；成功回 200 與一小段 HTML（HTMX 換進頁面）；拒絕回結果類別的 status 與
                     `{"outcome": ..., "message": ...}`（app/core/outcomes.py），畫面由模板內的 htmx:beforeSwap 顯示

為什麼拒絕仍是 JSON 而不是 HTML 片段：結果類別 → status → 回應格式只有一個出口（outcomes.py），測試與 T-202 都依賴它。
HTMX 2 預設不會把 4xx 換進畫面，所以模板自己處理（templates/reports.html），不修改 app/core/templates/base.html。

表單用標準庫解析（不用 `Form()`）：FastAPI 的 Form 需要 python-multipart，那不在專案依賴內（pitfall #27）。
端點用 `def`（pitfall #28）：同步的資料庫呼叫在 threadpool 執行；只有「讀請求主體」是 async。
anti-forgery token 由版型的 hx-headers 帶上（D-080），`get_current_actor` 檢查，所以表單內沒有隱藏欄位。
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, Depends, Request

from app.core.actor import Actor
from app.core.clock import clock
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError
from app.core.pages import render_page
from app.core.permissions import authorize
from app.core.session import get_current_actor
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo, service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024  # 37 個工項加 6 位共同作業者遠小於這個大小


async def _read_form(request: Request) -> dict[str, list[str]]:
    """請求主體 → {欄位: [值…]}（同名欄位保留全部值與順序，共同作業者的順序就是這樣來的）。空白值保留。"""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.get("/reports")
def reports_page(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    authorize(actor, "open the daily report form", service.SUBMITTER_RULE)  # RPT-R06：ADMIN、OWNER 不填日報
    account = repo.get_account(conn, actor.id)
    catalogue_name = cat.catalogue_name_for(account.zone, account.big_meter)
    today = clock.now().date()
    context = {
        "account": account,
        "catalogue_name": catalogue_name,
        "items": cat.catalogue(catalogue_name),
        "collaborators": repo.eligible_collaborators(conn, account),
        "max_collaborators": service.MAX_COLLABORATORS,
        "today": today.isoformat(),
        "earliest": (today - timedelta(days=service.MAX_BACK_DAYS)).isoformat(),
    }
    return render_page(request, conn, TEMPLATES, "reports.html", context)


@router.post("/reports")
def submit(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    submitted = service.submit_report(conn, actor, form)
    return render_page(request, conn, TEMPLATES, "report_saved.html", {"submitted": submitted})
