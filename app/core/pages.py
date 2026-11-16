"""共用頁面版型與 `render_page`（T-200；D-062、D-078、D-080、D-088）。

## 給 feature router 的介面

    from app.core.pages import render_page

    TEMPLATES = Path(__file__).parent / "templates"

    @router.get("/reports")
    def reports_page(request: Request, conn=Depends(get_db)):
        return render_page(request, conn, TEMPLATES, "reports.html", {"rows": rows})

模板 `{% extends "base.html" %}`，填 `title` 與 `content` 兩個 block。已登入時 `<body>` 會帶
`hx-headers='{"X-CSRF-Token": "<token>"}'`，頁面內所有 HTMX 請求自動帶上 anti-forgery token（D-080），
各 feature 不必自己處理 CSRF。

## 設計選擇

- token 取自 `anti_forgery_token_for`（只讀）。頁面渲染**不算使用**，不延長閒置計時（D-078：
  只有 `get_current_actor` 算）；所以這裡不呼叫 `get_current_actor`，也不寫任何東西。
  代價：頁面本身不做權限檢查，需要登入的頁面仍要自己依 `get_current_actor` 判斷；
  這個函式只負責「把已登入者的 token 放進頁面」。
- token 用 Jinja 的 `tojson` 放進單引號屬性：`tojson` 把 `<`、`>`、`&`、`'` 轉成 `\\uXXXX`，
  值裡不可能出現會提早結束屬性的字元。
- Jinja 環境依 `template_dir` 各建一份並快取；搜尋路徑是 `[feature 的 templates/, app/core/templates/]`，
  同名時 feature 的優先。autoescape 對所有模板開啟。
- 呼叫端傳入的 context 不能蓋掉 `csrf_token`、`csrf_header`、`request`。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import psycopg
from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.session import CSRF_HEADER, SESSION_COOKIE, anti_forgery_token_for

# 固定版本的 HTMX（D-062、D-088）：npm 套件 htmx.org@2.0.11 的 dist/htmx.min.js，一個位元組都沒有改。
# 檔案被換掉或改動時，tests/unit/core/test_static_assets.py 會失敗。
HTMX_VERSION = "2.0.11"
HTMX_SHA256 = "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"

CORE_DIR = Path(__file__).resolve().parent
CORE_TEMPLATES = CORE_DIR / "templates"
HTMX_FILE = CORE_DIR / "static" / "htmx.min.js"


@lru_cache(maxsize=None)
def _environment(template_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader([str(template_dir), str(CORE_TEMPLATES)]),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )


def render_page(
    request: Request,
    conn: psycopg.Connection,
    template_dir: Path | str,
    name: str,
    context: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """渲染 `template_dir/name`（可 extends `base.html`），回傳 HTML 回應。只讀，不延長 session。"""
    cookie = request.cookies.get(SESSION_COOKIE)
    token = anti_forgery_token_for(conn, cookie) if cookie else None
    values = dict(context or {})
    values.update(request=request, csrf_token=token, csrf_header=CSRF_HEADER)
    html = _environment(Path(template_dir).resolve()).get_template(name).render(values)
    return HTMLResponse(html, status_code=status_code)
