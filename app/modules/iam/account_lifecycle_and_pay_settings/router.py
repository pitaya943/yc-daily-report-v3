"""帳戶管理（IAM-F04，D-118）。路徑固定：

    GET  /accounts                     清單（USER，西區在前）與建立表單
    POST /accounts                     建立 USER 帳戶（IAM-R13）
    GET  /accounts/{id}                資料與薪資設定（USER 讀取 → FORBIDDEN，D-114）
    POST /accounts/{id}                修改區域、大表旗標、勞健保、固定薪資（IAM-R15、R16）
    POST /accounts/{id}/archive        封存（IAM-R17）
    POST /accounts/{id}/restore        復原（IAM-R18）
    POST /accounts/{id}/delete         沒有這個動作：一律 INVALID（IAM-R19）
    POST /accounts/{id}/deactivate     沒有這個動作：一律 INVALID（IAM-R19）

與 T-201 相同的做法：表單用 `parse_qs`（不用 `Form()`，pitfall #27）；端點用 `def`（pitfall #28）；
anti-forgery token 由版型的 hx-headers 帶上（D-080）；HTMX 2 不換進 4xx，所以模板自己處理（pitfall #31），不修改 base.html。
成功回 200 與一小段 HTML；拒絕回結果類別的 status 與 JSON（app/core/outcomes.py）。
`{account_id:int}` 讓不是數字的路徑 404，而不是 422。
權限一律在 service 內經 access.py 判斷；router 只負責取得行為者、解析表單、渲染。
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
from app.modules.iam.account_lifecycle_and_pay_settings import repo, service
from app.modules.iam.account_lifecycle_and_pay_settings.access import authorize_account_action

router = APIRouter()
TEMPLATES = Path(__file__).parent / "templates"
_MAX_BODY_BYTES = 16 * 1024


async def _read_form(request: Request) -> dict[str, list[str]]:
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise OutcomeError(Outcome.INVALID)
    return parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)


@router.get("/accounts")
def accounts_page(request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    authorize_account_action(actor, "open account management")
    return render_page(request, conn, TEMPLATES, "accounts.html", {"accounts": repo.list_users(conn), "zones": service.ZONES})


@router.post("/accounts")
def create(
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    account_id = service.create_account(conn, actor, form)
    return render_page(request, conn, TEMPLATES, "account_saved.html", {"message": "已建立帳戶", "account_id": account_id})


@router.get("/accounts/{account_id:int}")
def account_page(account_id: int, request: Request, actor: Actor = Depends(get_current_actor), conn: psycopg.Connection = Depends(get_db)):
    try:
        account = service.load_authorized(conn, actor, account_id, "open an account page", lock=False)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    rate = "" if account.uninsured_rate_bp is None else service.format_rate(account.uninsured_rate_bp)
    return render_page(request, conn, TEMPLATES, "account.html", {"account": account, "rate": rate, "zones": service.ZONES})


@router.post("/accounts/{account_id:int}")
def update(
    account_id: int,
    request: Request,
    actor: Actor = Depends(get_current_actor),
    form: dict[str, list[str]] = Depends(_read_form),
    conn: psycopg.Connection = Depends(get_db),
):
    try:
        changed = service.update_account(conn, actor, account_id, form)
    except service.AccountNotFound:
        raise HTTPException(status_code=404) from None
    return render_page(request, conn, TEMPLATES, "account_saved.html", {"message": "已儲存" if changed else "沒有變動", "account_id": account_id})


def _lifecycle(action, message: str):
    def endpoint(
        account_id: int,
        request: Request,
        actor: Actor = Depends(get_current_actor),
        conn: psycopg.Connection = Depends(get_db),
    ):
        try:
            action(conn, actor, account_id)
        except service.AccountNotFound:
            raise HTTPException(status_code=404) from None
        response = render_page(request, conn, TEMPLATES, "account_saved.html", {"message": message, "account_id": account_id})
        response.headers["HX-Refresh"] = "true"  # 狀態改變：讓 HTMX 重新載入頁面，按鈕與狀態標示跟著換
        return response

    return endpoint


router.add_api_route("/accounts/{account_id:int}/archive", _lifecycle(service.archive_account, "已封存"), methods=["POST"], name="archive_account")
router.add_api_route("/accounts/{account_id:int}/restore", _lifecycle(service.restore_account, "已復原"), methods=["POST"], name="restore_account")


def _no_such_action(account_id: int, actor: Actor = Depends(get_current_actor)):
    """IAM-R19：帳戶永遠不刪除、不停用（附錄 C 沒有這兩種稽核類型）。沒有這個動作 → INVALID，不論誰來問、帳戶存不存在。"""
    raise OutcomeError(Outcome.INVALID)


router.add_api_route("/accounts/{account_id:int}/delete", _no_such_action, methods=["POST"], name="delete_account_is_not_an_action")
router.add_api_route("/accounts/{account_id:int}/deactivate", _no_such_action, methods=["POST"], name="deactivate_account_is_not_an_action")
