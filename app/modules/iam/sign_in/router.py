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
from app.core.session import SESSION_COOKIE, actor_for_token, landing_path_for, set_session_cookie
from app.modules.iam.sign_in import service

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# 群組的顯示名稱（規格沒有指定，這是 UI 用語）
GROUP_LABELS = {"admin": "管理員", "west": "西區", "south": "南區"}
_MAX_BODY_BYTES = 16 * 1024


@router.get("/sign-in")
def sign_in_page(request: Request, group: str | None = None, conn: psycopg.Connection = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE)
    actor = actor_for_token(conn, token) if token else None
    if actor is not None:  # IAM-R11：已登入的人打開登入頁，直接去落地頁
        return RedirectResponse(landing_path_for(actor.role), status_code=303)
    names = service.names_for_group(conn, group) if group else []
    return templates.TemplateResponse(
        request,
        "sign_in.html",
        {"groups": GROUP_LABELS, "group": group, "names": names, "pick_account": service.MSG_PICK_ACCOUNT},
    )


async def _read_form(request: Request) -> dict[str, str]:
    """只有這一步是 async（讀請求主體不阻塞）；後面的端點是同步函式，scrypt 與資料庫呼叫在 threadpool 執行。"""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return {k: v[-1] for k, v in parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True).items()}


@router.post("/sign-in")
def sign_in(request: Request, form: dict[str, str] = Depends(_read_form), conn: psycopg.Connection = Depends(get_db)):
    # `def` 不是 `async def`：scrypt（約零點幾秒的 CPU）與同步 DB 若直接跑在 event loop 上，會讓整個應用程式停住（完成條件 11）
    # 來源位址取自 ASGI 的 client（反向代理後面由 uvicorn 的 --proxy-headers 換成真實位址）；取不到時用固定字串，
    # 讓「取不到位址」的請求共用同一個額度，而不是不受限制
    address = request.client.host if request.client else "unknown"
    issued, landing = service.sign_in(conn, form.get("name"), form.get("password"), form.get("group") or None, client_address=address)
    response = RedirectResponse(landing, status_code=303)
    set_session_cookie(response, issued.token)
    return response
