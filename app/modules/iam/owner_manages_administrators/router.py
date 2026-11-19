"""OWNER 管理管理員（IAM-F05，D-118）。

    POST /accounts/{id}/role   切換角色（IAM-R21）：`role`（ADMIN 或 USER）；只有 OWNER

「只有 OWNER 能動 ADMIN」與自我保護（IAM-R20、R22）加在既有端點上，規則寫在 `access.py`：
`POST /accounts`（新增）、`/accounts/{id}`（改區域）、`/archive`、`/restore`、`/accounts/{id}/password`（重設密碼）。

做法與 T-303 相同：表單用 `parse_qs`（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；anti-forgery token 在標頭（D-080）；
成功回 200 與一小段 HTML，拒絕回結果類別的 status 與 JSON（app/core/outcomes.py）。
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
from app.modules.iam.owner_manages_administrators import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 1024  # 一個最長 5 字的欄位


async def _read_form(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.post("/accounts/{account_id:int}/role")
def switch_role(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        changed = service.switch_role(conn, actor, account_id, form)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "role_changed.html", {"changed": changed})
