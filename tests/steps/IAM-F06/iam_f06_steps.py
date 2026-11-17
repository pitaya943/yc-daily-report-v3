"""IAM-F06 密碼變更與重設的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

設計：
- 請求走真的 HTTP（TestClient）：`POST /account/password`（自己改）與 `POST /accounts/{id}/password`（管理員重設），
  帶 session cookie 與 `X-CSRF-Token`（D-080）。路徑固定（D-118）。表單欄位：current_password、new_password、password_confirm
  （重設只有 new_password：規格的 scenario 是「重設為 newpass1」，沒有確認欄）。
- 動作一律走 `recorder.perform`，「資料沒有變動」比對的是動作前後整個資料庫。
- `the outcome is <outcome> with message "<message>"`、`"<name>" is signed in`、`an audit row ... with actor ...` 都是
  tests/steps/common/ 的共用步驟，這裡不重新定義（pitfall #26）；只新增 IAM-F06 專屬的句子。
- 規格的密碼 "correct" 是共用的測試密碼（tests/steps/common/session.py 的 TEST_PASSWORD）；"wrong" 就是一個不對的字串。
- 「重設後可登入」用一個全新的 client（沒有 session cookie）走真正的 `POST /sign-in`，不碰 `set_password`（那會覆蓋掉被測的密碼）。
- `no such action exists`：規格說沒有自助找回密碼。步驟分兩層斷言：(1) 應用程式的路由表裡，名稱含 recover／forgot／reset 的
  只有規格授權的管理員重設端點；(2) 訪客對一組常見的找回路徑發出請求，每個都得不到成功的回應，而且資料庫完全沒有變動。
"""
from __future__ import annotations

import pytest
from pytest_bdd import parsers, then, when

from app.core import session as session_core
from app.main import create_app, discover_routers
from tests.steps.common.audit_description import *  # noqa: F401,F403
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ... with message ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, assert_signed_in, post_sign_in
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、稽核與資料變動的共用步驟)
from tests.steps.common.steps import check_nothing_written, new_audit_rows

CSRF_HEADER = "X-CSRF-Token"
OWN_PASSWORD_PATH = "/account/password"
RESET_PATH = "/accounts/{id}/password"  # D-118
# 訪客可能嘗試的「找回密碼」路徑；規格說沒有這個動作（IAM-R32）
RECOVERY_PATHS = (
    "/forgot-password",
    "/forgot_password",
    "/password/forgot",
    "/password/recover",
    "/password/reset",
    "/recover",
    "/recover-password",
    "/reset-password",
    "/sign-in/recover",
    "/sign-in/forgot",
    "/sign-in/reset",
    "/account/password/recover",
    "/account/password/forgot",
    "/account/password/reset",
    "/account/recover",
)


@pytest.fixture
def last() -> dict:
    """scenario 內最近一次密碼動作用到的舊密碼與新密碼（稽核說明不可含這兩者）。"""
    return {}


def app_routes() -> set[tuple[str, str]]:
    """應用程式註冊的所有（HTTP 方法, 路徑）；路徑用 `path_format`（`{account_id:int}` 轉換器會被去掉）。

    不用 `app.routes`：這個 FastAPI 版本把 include_router 的結果包成 `_IncludedRouter`，裡面看不到路徑，
    檢查會悄悄變成空轉。改展開 `discover_routers()`（app/main.py 的公開函式）每個 APIRouter 的路由。
    """
    return {(method, getattr(route, "path_format", route.path)) for router in discover_routers() for route in router.routes for method in getattr(route, "methods", ())}


def csrf_token(client, db) -> str:
    token = session_core.anti_forgery_token_for(db, client.cookies.get(SESSION_COOKIE))
    db.rollback()
    assert token, "動作的人必須已登入（沒有有效的 session）"
    return token


def account_id(db, name: str) -> int:
    row = db.execute("select id from yc_v3.accounts where name = %s", (name,)).fetchone()
    db.rollback()
    assert row is not None, f"背景資料裡沒有帳戶 {name}"
    return row[0]


def form_body(fields: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(fields)


def post_form(client, db, path: str, fields: dict[str, str]):
    return client.post(
        path,
        content=form_body(fields),
        headers={"content-type": "application/x-www-form-urlencoded", CSRF_HEADER: csrf_token(client, db)},
    )


def change_own_password(recorder, client, db, last, current: str, new: str, confirm: str) -> None:
    last.update(old=current, new=new)
    fields = {"current_password": current, "new_password": new, "password_confirm": confirm}
    recorder.perform(lambda: post_form(client, db, OWN_PASSWORD_PATH, fields))


# ───────────────────────── IAM-R30 ─────────────────────────


@when(parsers.parse('"{who}" changes their password with current "{current}", new "{new}", confirmation "{confirm}"'))
def _change(recorder, client, db, last, who, current, new, confirm):
    change_own_password(recorder, client, db, last, current, new, confirm)


@when(parsers.parse('"{who}" changes their password with a wrong current password'))
def _change_wrong_current(recorder, client, db, last, who):
    change_own_password(recorder, client, db, last, "wrong", "newpass1", "newpass1")


@when(parsers.parse('"{who}" changes their password successfully'))
def _change_successfully(recorder, client, db, last, who):
    change_own_password(recorder, client, db, last, TEST_PASSWORD, "newpass1", "newpass1")
    assert recorder.response.status_code == 200, f"應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"


@then("the audit description contains neither the old nor the new password")
def _audit_has_no_password(recorder, db, last):
    added = new_audit_rows(recorder)
    assert len(added) == 1, f"這個動作應該恰新增 1 列稽核，實際 {len(added)} 列：{added}"
    with db.cursor() as cur:
        cur.execute("select x::text, type, description from yc_v3.audit_log x")
        rows = [r for r in cur.fetchall() if r[0] == added[0]]
    db.rollback()
    assert len(rows) == 1, f"新增的稽核列在資料庫裡找不到：{added}"
    row_text, type_, description = rows[0]
    assert type_ == "PASSWORD_CHANGE", f"新增的稽核應是 PASSWORD_CHANGE，實際 {type_}"
    assert last.get("old") and last.get("new"), "這個 scenario 沒有先執行密碼變更"
    # 整列文字（含 actor_name、type 等所有欄位）都不能出現密碼，不只看 description
    for label, password in (("舊密碼", last["old"]), ("新密碼", last["new"])):
        assert password not in description, f"稽核說明不可含{label}：{description!r}"
        assert password not in row_text, f"稽核列不可含{label}：{row_text!r}"


# ───────────────────────── IAM-R31 ─────────────────────────


@when(parsers.parse('"{who}" resets the password of "{target}" to "{new}"'))
def _reset(recorder, client, db, last, who, target, new):
    last.update(old=TEST_PASSWORD, new=new)
    path = RESET_PATH.format(id=account_id(db, target))
    recorder.perform(lambda: post_form(client, db, path, {"new_password": new}))
    assert recorder.response.status_code == 200, f"重設應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"


@then(parsers.parse('"{name}" can sign in with "{password}"'))
def _can_sign_in(db, name, password):
    from fastapi.testclient import TestClient

    fresh = TestClient(create_app(), raise_server_exceptions=False)  # 沒有任何 cookie：不是沿用管理員的 session
    response = post_sign_in(fresh, name, password)
    assert_signed_in(fresh, db, name, response)


# ───────────────────────── IAM-R32 ─────────────────────────


@when(parsers.parse('a visitor asks to recover the password of "{name}"'))
def _recover(recorder, client, name):
    """訪客（沒有 session）對每一條常見的找回路徑發出 GET 與 POST；結果存在 recorder 的回應清單。"""
    recorder.recovery_responses = []

    def probe():
        for path in RECOVERY_PATHS:
            recorder.recovery_responses.append((path, "GET", client.get(path, follow_redirects=False)))
            recorder.recovery_responses.append((path, "POST", client.post(path, data={"name": name}, follow_redirects=False)))
        return recorder.recovery_responses[-1][2]

    recorder.perform(probe)


@then("no such action exists")
def _no_such_action(recorder, client):
    # (1) 路由表：名稱含 recover／forgot／reset 的路徑，只有規格授權的「管理員重設」（D-118）
    routes = app_routes()
    assert ("POST", RESET_PATH.replace("{id}", "{account_id}")) in routes, "路由表是空的或展開失敗：找不到規格授權的重設端點，這項檢查會空轉"
    suspicious = {(m, p) for m, p in routes if any(w in p.lower() for w in ("recover", "forgot", "reset"))}
    assert suspicious == set(), f"規格沒有自助找回密碼，但路由表有：{sorted(suspicious)}"
    # (2) 探測：每一條路徑都得不到成功或轉址的回應（只可能是 404／405）
    assert recorder.recovery_responses, "沒有探測任何路徑"
    for path, method, response in recorder.recovery_responses:
        assert response.status_code in (404, 405), f"{method} {path} 不該存在，實際回 {response.status_code}：{response.text[:120]}"
    # (3) 資料沒有任何變動：沒有寄信、沒有 token、沒有密碼被改
    check_nothing_written(recorder)
    assert SESSION_COOKIE not in client.cookies
