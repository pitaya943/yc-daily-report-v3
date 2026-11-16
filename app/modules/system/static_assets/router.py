"""供應固定版本的 htmx.min.js（T-200；D-062）。

只有 `/static/htmx.min.js` 這一條路由，檔案路徑寫死在 `app.core.pages.HTMX_FILE`：
不掛載整個 static 目錄（StaticFiles），所以請求的路徑不會變成檔案系統路徑，沒有路徑穿越的問題。
不需要登入：登入頁以外的版型都載入它，登入前的頁面日後也可能用到。
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.pages import HTMX_FILE

router = APIRouter()


@router.get("/static/htmx.min.js", include_in_schema=False)
def htmx_min_js() -> FileResponse:
    return FileResponse(HTMX_FILE, media_type="text/javascript")
