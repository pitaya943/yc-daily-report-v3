"""提前解除鎖定（IAM-R08，D-126）。

    POST /accounts/{id}/unlock   沒有請求主體；成功回 200 與一小段 HTML，拒絕回結果類別的 status 與 JSON（outcomes.py）

只有端點：帳戶管理頁的「解除鎖定」按鈕由 T-304 加上。端點用 `def`（pitfall #28）；anti-forgery token 在標頭（D-080，`get_current_actor` 檢查）。
登入本身（`POST /sign-in`）在 `sign_in/router.py`；這個 feature 的其他規則是 service 裡的函式，沒有自己的頁面。
"""
from __future__ import annotations

from pathlib import Path

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.actor import Actor
from app.core.db import get_db
from app.core.pages import render_page
from app.core.session import get_current_actor
from app.modules.iam.sign_in_lockout_and_rate_limit import service

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"


@router.post("/accounts/{account_id:int}/unlock")
def unlock_account(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        name = service.unlock(conn, actor, account_id)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "unlocked.html", {"account_name": name})
