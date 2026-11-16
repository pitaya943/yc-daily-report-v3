"""目前 session 與登出（IAM-F03）。

    GET  /session    回傳目前的行為者與 anti-forgery token（T-103 的「protected action」）
    POST /sign-out   登出：立刻結束這個 session，清掉 cookie，轉址到登入頁（T-103 的「state-changing request」）

兩個端點都經由 `get_current_actor`，所以閒置逾時與 anti-forgery 的檢查一致（見 app/core/session.py）。
規則簡單，直接寫在這裡，沒有另外拆 service／repo。
"""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.actor import Actor
from app.core.db import get_db
from app.core.session import SESSION_COOKIE, anti_forgery_token_for, clear_session_cookie, end_session, get_current_actor

router = APIRouter()


@router.get("/session")
def current_session(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    token = anti_forgery_token_for(conn, request.cookies[SESSION_COOKIE])
    return JSONResponse({"name": actor.name, "role": actor.role.value, "anti_forgery_token": token}, headers={"Cache-Control": "no-store"})


@router.post("/sign-out")
def sign_out(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    end_session(conn, request.cookies[SESSION_COOKIE])
    conn.commit()
    response = RedirectResponse("/sign-in", status_code=303)
    clear_session_cookie(response)
    return response
