"""密碼變更與重設（IAM-F06，D-118）。

    GET  /account/password         自己改密碼的頁面（所有登入者）
    POST /account/password         自己改密碼（IAM-R30）：current_password、new_password、password_confirm
    POST /accounts/{id}/password   管理員重設（IAM-R31）：new_password、password_confirm（D-127）；USER → FORBIDDEN

沒有任何找回密碼的端點（IAM-R32）。做法與 T-201 相同：表單用 `parse_qs`（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；
anti-forgery token 由版型的 hx-headers 帶上（D-080）；成功回 200 與一小段 HTML，拒絕回結果類別的 status 與 JSON（outcomes.py）。
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
from app.core.session import SESSION_COOKIE, get_current_actor
from app.modules.iam.password_change_and_reset import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 4 * 1024  # 三個最長 30 字的欄位遠小於這個大小


async def _read_form(request: Request) -> dict[str, list[str]]:
    """請求主體 → {欄位: [值…]}。空白值保留；同名欄位保留全部（service 把重複視為不合格）。"""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.get("/account/password")
def password_page(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    return render_page(
        request,
        conn,
        TEMPLATES,
        "password.html",
        {"account_name": actor.name, "min_length": service.MIN_LENGTH, "max_length": service.MAX_LENGTH},
    )


@router.post("/account/password")
def change_password(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    # 目前這個 session 的憑證：成功後保留它、結束同帳戶的其他 session（IAM-R33）。get_current_actor 已確認它有效
    service.change_own_password(conn, actor, form, request.cookies[SESSION_COOKIE])
    return render_page(request, conn, TEMPLATES, "password_changed.html")


@router.post("/accounts/{account_id:int}/password")
def reset_password(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        done = service.reset_password(conn, actor, account_id, form)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "password_reset.html", {"done": done})
