"""銀行帳號遮罩與顯示（IAM-F07）與銀行帳號、發薪方式的設定（IAM-R14）。路徑固定（D-118）：

    GET  /accounts/{id}/bank-number           遮罩（只有末四碼）；不寫稽核
    POST /accounts/{id}/bank-number/reveal    顯示全碼；寫 BANK_REVEAL。用 POST：T-200 要求「渲染頁面時整個資料庫不變」
    POST /accounts/{id}/bank-number           設定銀行帳號（IAM-R14、R43）
    POST /accounts/{id}/payment-method        設定發薪方式（IAM-R14）

做法與 T-303 相同：表單用 `parse_qs`（pitfall #27）；端點用 `def`（pitfall #28）；anti-forgery token 由版型的 hx-headers 帶上（D-080）；
HTMX 2 不換進 4xx，所以模板自己處理（pitfall #31），不修改 base.html。
成功回 200 與一小段 HTML；拒絕回結果類別的 status 與 JSON（app/core/outcomes.py）。
全碼只出現在 reveal 的回應內文，並且 `Cache-Control: no-store`：瀏覽器與中間的快取都不留。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.actor import Actor, Role
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError
from app.core.pages import render_page
from app.core.session import get_current_actor
from app.modules.iam.bank_number_masking_and_reveal import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024
NO_STORE = {"Cache-Control": "no-store"}


async def _read_form(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


def _fragment(request: Request, conn: psycopg.Connection, shown: service.Shown):
    response = render_page(request, conn, TEMPLATES, "bank_value.html", {"shown": shown})
    response.headers.update(NO_STORE)
    return response


@router.get("/accounts/{account_id:int}/bank-number")
def bank_number_page(account_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    try:
        holder, shown = service.show_masked(conn, actor, account_id)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    context = {
        "holder": holder,
        "shown": shown,
        "can_edit": actor.role in (Role.ADMIN, Role.OWNER),
        "methods": service.PAYMENT_METHODS,
    }
    response = render_page(request, conn, TEMPLATES, "bank_number.html", context)
    response.headers.update(NO_STORE)
    return response


@router.post("/accounts/{account_id:int}/bank-number/reveal")
def reveal(account_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    try:
        _, shown = service.reveal(conn, actor, account_id)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    return _fragment(request, conn, shown)


@router.post("/accounts/{account_id:int}/bank-number")
def set_bank_number(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        service.set_bank_number(conn, actor, account_id, form)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    response = render_page(request, conn, TEMPLATES, "saved.html", {"message": "已儲存"})
    response.headers["HX-Refresh"] = "true"  # 遮罩的值與發薪方式的選項跟著更新
    return response


@router.post("/accounts/{account_id:int}/payment-method")
def set_payment_method(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        changed = service.set_payment_method(conn, actor, account_id, form)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    response = render_page(request, conn, TEMPLATES, "saved.html", {"message": "已儲存" if changed else "沒有變動"})
    response.headers["HX-Refresh"] = "true"
    return response
