"""登入頁與登入動作（IAM-F01）。

    GET  /sign-in            登入頁；?group=west 時列出該群組的名單（IAM-R01）
    POST /sign-in            name、password（、group）→ 303 轉址到落地頁並設定 session cookie（IAM-R02）；失敗見 service.py

表單用標準庫解析（不用 `Form()`）：FastAPI 的 Form 需要 python-multipart，那不在專案依賴內（D-056：不新增依賴）。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError
from app.core.session import set_session_cookie
from app.modules.iam.sign_in import service

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# 群組的顯示名稱（規格沒有指定，這是 UI 用語）
GROUP_LABELS = {"admin": "管理員", "west": "西區", "south": "南區"}
_MAX_BODY_BYTES = 16 * 1024


@router.get("/sign-in")
def sign_in_page(request: Request, group: str | None = None, conn: psycopg.Connection = Depends(get_db)):
    names = service.names_for_group(conn, group) if group else []
    return templates.TemplateResponse(
        request,
        "sign_in.html",
        {"groups": GROUP_LABELS, "group": group, "names": names, "pick_account": service.MSG_PICK_ACCOUNT},
    )


@router.post("/sign-in")
async def sign_in(request: Request, conn: psycopg.Connection = Depends(get_db)):
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    form = {k: v[-1] for k, v in parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True).items()}
    issued, landing = service.sign_in(conn, form.get("name"), form.get("password"), form.get("group") or None)
    response = RedirectResponse(landing, status_code=303)
    set_session_cookie(response, issued.token)
    return response
