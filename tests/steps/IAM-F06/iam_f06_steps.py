"""IAM-F06 密碼變更與重設的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

設計：
- 請求走真的 HTTP（TestClient）：`POST /account/password`（自己改）與 `POST /accounts/{id}/password`（管理員重設），
  帶 session cookie 與 `X-CSRF-Token`（D-080）。路徑固定（D-118）。表單欄位：current_password、new_password、password_confirm
  （重設送 new_password 與 password_confirm：D-127 要求管理員重設也有確認欄；規格的「重設為 newpass1」步驟把兩欄填同一個值）。
- 動作一律走 `recorder.perform`，「資料沒有變動」比對的是動作前後整個資料庫。
- `the outcome is <outcome> with message "<message>"`、`"<name>" is signed in`、`an audit row ... with actor ...` 都是
  tests/steps/common/ 的共用步驟，這裡不重新定義（pitfall #26）；只新增 IAM-F06 專屬的句子。
- 規格的密碼 "correct" 是共用的測試密碼（tests/steps/common/session.py 的 TEST_PASSWORD）；"wrong" 就是一個不對的字串。
- 「重設後可登入」用一個全新的 client（沒有 session cookie）走真正的 `POST /sign-in`，不碰 `set_password`（那會覆蓋掉被測的密碼）。
- IAM-R33（T-308）：「兩台裝置」是兩個各自帶 cookie 的獨立用戶端（`devices` fixture），不是同一個 client 換 cookie；
  「受保護的請求」是 `GET /account/password`（任何登入者都能開）。被拒絕的受保護請求同時斷言結果類別、沒有錯誤字串、資料沒有變動。
  「管理員重設」的 When 發現 `client` 還沒登入時，先以該管理員登入（登入發生在動作之前，不算動作的資料變動）。
- `no such action exists`：規格說沒有自助找回密碼。步驟分兩層斷言：(1) 應用程式的路由表裡，名稱含 recover／forgot／reset 的
  只有規格授權的管理員重設端點；(2) 訪客對一組常見的找回路徑發出請求，每個都得不到成功的回應，而且資料庫完全沒有變動。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core import session as session_core
from app.main import create_app, discover_routers
from tests.steps.common.audit_description import *  # noqa: F401,F403
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ... with message ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, assert_signed_in, post_sign_in, session_rows, set_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、稽核與資料變動的共用步驟)
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected, new_audit_rows

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
    if SESSION_COOKIE not in client.cookies:  # IAM-R33 的 scenario 沒有 `"Admin1" is signed in`：動作之前先登入
        set_password(db, who)
        assert post_sign_in(client, who, TEST_PASSWORD).status_code == 303
    last.update(old=TEST_PASSWORD, new=new)
    path = RESET_PATH.format(id=account_id(db, target))
    recorder.perform(lambda: post_form(client, db, path, {"new_password": new, "password_confirm": new}))
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


# ───────────────────────── IAM-R33：改密碼後的 session ─────────────────────────

PROTECTED_PATH = "/account/password"  # 任何登入者都能開；未登入為 UNAUTHENTICATED


@pytest.fixture
def devices() -> dict[str, TestClient]:
    """同一個帳戶的兩台裝置：兩個各自帶 cookie 的獨立用戶端（`first`、`second`）。"""
    return {}


@given(parsers.parse('"{name}" is signed in on two devices'))
def _signed_in_on_two_devices(db, devices, name):
    set_password(db, name)
    for label in ("first", "second"):
        device = TestClient(create_app(), raise_server_exceptions=False)
        response = post_sign_in(device, name, TEST_PASSWORD)
        assert response.status_code == 303, f"{label} 裝置登入應成功（303），實際 {response.status_code}"
        devices[label] = device
    tokens = {d.cookies.get(SESSION_COOKIE) for d in devices.values()}
    assert len(tokens) == 2 and None not in tokens, "兩台裝置應各自持有不同的 session 憑證"
    assert len(session_rows(db, name)) == 2, "資料庫裡這個帳戶應有 2 列 session"


@when(parsers.parse('"{who}" changes their password successfully on the first device'))
def _change_on_first_device(recorder, devices, db, last, who):
    change_own_password(recorder, devices["first"], db, last, TEST_PASSWORD, "newpass1", "newpass1")
    assert recorder.response.status_code == 200, f"應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"


def _protected_request(db, device: TestClient) -> Recorder:
    rec = Recorder(db)
    rec.perform(lambda: device.get(PROTECTED_PATH, follow_redirects=False))
    return rec


def assert_unauthenticated(db, device: TestClient, label: str) -> None:
    """受保護的請求被拒絕：結果類別、完整錯誤字串（規格沒寫字串，所以是 null）、資料沒有任何變動。"""
    rec = _protected_request(db, device)
    check_rejected(rec, "UNAUTHENTICATED", None)
    check_nothing_written(rec)
    assert label  # 失敗時 pytest 會顯示是哪一台


@then(parsers.parse('the first device of "{name}" can still make protected requests'))
def _first_device_still_works(db, devices, name):
    response = _protected_request(db, devices["first"]).response
    assert response.status_code == 200, f"目前這個 session 應保留，實際 {response.status_code}：{response.text[:200]}"


@then(parsers.parse('a protected request from the second device of "{name}" is rejected as UNAUTHENTICATED'))
def _second_device_rejected(db, devices, name):
    assert_unauthenticated(db, devices["second"], "second")


@then(parsers.parse('a protected request from either device of "{name}" is rejected as UNAUTHENTICATED'))
def _either_device_rejected(db, devices, name):
    for label, device in devices.items():
        assert_unauthenticated(db, device, label)


# ───────────────────────── IAM-R34：錯誤的目前密碼（D-140）─────────────────────────


def _failure_count_in(row: str) -> int:
    """`sign_in_failures` 一列的快照文字 `(account_id,fail_count,last_failed_at,locked_at)` → fail_count。"""
    return int(row.strip("()").split(",")[1])


@then(parsers.parse('the only change is one more failed sign-in for "{who}"'))
def _only_one_more_failed_sign_in(recorder, db, who):
    """D-140：恰好新增或更新一列 `sign_in_failures`（該帳戶失敗次數加 1）；其他資料表（含 `sign_in_attempts`、`audit_log`）完全不變。

    「更新」在快照裡是「舊的一列被移除、新的一列被加入」，所以比對的是那個帳戶的次數：新的 = 舊的 + 1（沒有舊的列就是 0 + 1）。
    """
    changes = recorder.changes()
    assert set(changes) == {"sign_in_failures"}, f"唯一的變動應是失敗次數表，實際：{changes}"
    added, removed = changes["sign_in_failures"]["added"], changes["sign_in_failures"]["removed"]
    assert len(added) == 1 and len(removed) <= 1, f"應恰好新增或更新一列失敗次數：{changes['sign_in_failures']}"
    account = account_id(db, who)
    assert int(added[0].strip("()").split(",")[0]) == account, f"那一列應屬於 {who}：{added[0]}"
    before = _failure_count_in(removed[0]) if removed else 0
    assert _failure_count_in(added[0]) == before + 1, f"失敗次數應從 {before} 加 1：{added[0]}"
