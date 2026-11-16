"""IAM-F03 Session 與登出的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

「protected action」是 `GET /session`（回傳目前行為者），「state-changing request」是 `POST /sign-out`
——兩者都是 T-103 自己的端點（完成條件 9）。anti-forgery token 放在 `X-CSRF-Token` 標頭。

IAM-R10 的步驟寫在這裡，但 IAM-R10 不在 tests/implemented.txt（D-058：「Saved data survives a timeout」
要等 M2 的回報；T-201 補上那個步驟後才加入規則 ID），所以 CI 不會執行它們；
閒置邊界由 tests/unit/iam/ 的單元測試驗證。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_bdd import parsers, then, when
from pytest_bdd import given

from app.core.clock import clock
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, set_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、共用的拒絕與資料變動步驟)
from tests.steps.common.steps import check_nothing_written, check_rejected
from tests.steps.common.session import *  # noqa: F401,F403  (is signed in)

PROTECTED = "/session"
STATE_CHANGING = "/sign-out"
CSRF_HEADER = "X-CSRF-Token"
# D-057：規格的頁名 → 落地頁路徑
PAGES = {"daily report": "/reports", "confirmation": "/review"}


def sign_in_at(client, db, name: str, when_: object) -> str:
    """在時鐘為 `when_` 時登入（session 的建立與最後使用時間都是那一刻），再把時鐘還原。回傳 session 憑證。"""
    now = clock.now()
    clock.set(when_)
    set_password(db, name)
    response = post_sign_in(client, name, TEST_PASSWORD)
    clock.set(now)
    assert response.status_code == 303, f"登入應成功（303），實際 {response.status_code}"
    return client.cookies.get(SESSION_COOKIE)


def anti_forgery_token(db, name: str) -> str:
    with db.cursor() as cur:
        cur.execute(
            "select s.anti_forgery_token from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
            "where a.name = %s order by s.id desc limit 1",
            (name,),
        )
        token = cur.fetchone()[0]
    db.rollback()
    return token


def set_last_used(db, name: str, last_used) -> None:
    with db.cursor() as cur:
        cur.execute(
            "update yc_v3.sessions set last_used_at = %s where account_id = (select id from yc_v3.accounts where name = %s)",
            (last_used, name),
        )
    db.commit()


@pytest.fixture
def issued_token() -> dict:
    """scenario 內前面步驟留下的 session 憑證，供「登出之後用同一個憑證再請求」使用。"""
    return {}


# ───────────────────────── IAM-R10 ─────────────────────────


@given(parsers.re(r'"(?P<name>[^"]+)" signed in and last used the system (?P<minutes>\d+) min (?P<seconds>\d+) sec ago'))
def _signed_in_idle(client, db, name, minutes, seconds):
    sign_in_at(client, db, name, clock.now())
    # 建立時間不得晚於最後使用時間（資料表的 check 約束），所以兩者一起往前推
    last_used = clock.now() - timedelta(minutes=int(minutes), seconds=int(seconds))
    with db.cursor() as cur:
        cur.execute("update yc_v3.sessions set created_at = %s, last_used_at = %s", (last_used, last_used))
    db.commit()


@given(parsers.re(r'"(?P<name>[^"]+)" signed in (?P<signed>\d+) minutes ago and last used the system (?P<used>\d+) minutes ago'))
def _signed_in_ago_used_ago(client, db, name, signed, used):
    sign_in_at(client, db, name, clock.now() - timedelta(minutes=int(signed)))
    set_last_used(db, name, clock.now() - timedelta(minutes=int(used)))


@when(parsers.parse('"{name}" requests a protected action'))
def _protected(recorder, client, name):
    recorder.perform(lambda: client.get(PROTECTED))


@then("the outcome is accepted")
def _accepted(recorder):
    r = recorder.response
    assert r.status_code == 200, f"應被接受（200），實際 {r.status_code}：{r.text[:200]}"


@then(parsers.re(r"the outcome is (?P<outcome>[A-Z_]+)"))
def _outcome(recorder, outcome):
    # spec 沒有為閒置逾時寫錯誤字串，所以斷言沒有字串；被拒絕的請求不可改動任何資料
    check_rejected(recorder, outcome, None)
    check_nothing_written(recorder)


@when(parsers.parse('"{name}" signs in'))
def _signs_in(recorder, client, db, name):
    set_password(db, name)
    recorder.perform(lambda: post_sign_in(client, name, TEST_PASSWORD))


def _set_cookie_headers(response) -> list[str]:
    return response.headers.get_list("set-cookie")


@then("no credential is issued that outlives the 30-minute idle window")
def _no_remember_me(recorder):
    cookies = _set_cookie_headers(recorder.response)
    assert cookies, "登入應發出 session cookie"
    for header in cookies:
        attrs = {a.split("=")[0].strip().lower() for a in header.split(";")[1:]}
        assert "max-age" not in attrs and "expires" not in attrs, f"cookie 不可有存活期限（會在關閉瀏覽器後仍存在）：{header}"


# ───────────────────────── IAM-R11 ─────────────────────────


@when(parsers.parse('"{name}" signs out'))
def _signs_out(recorder, client, db, issued_token, name):
    issued_token["token"] = client.cookies.get(SESSION_COOKIE)
    csrf = anti_forgery_token(db, name)
    recorder.perform(lambda: client.post(STATE_CHANGING, headers={CSRF_HEADER: csrf}, follow_redirects=False))


@then("a later protected request from that session is rejected as UNAUTHENTICATED")
def _later_rejected(recorder, client, db, issued_token):
    # 登出本身：回應成功、那個 session 在資料庫裡已不存在
    assert recorder.response.status_code == 303, f"登出應轉址（303），實際 {recorder.response.status_code}"
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.sessions")
        assert cur.fetchone()[0] == 0, "登出後資料庫不該還有這個 session"
    db.rollback()
    # 用「登出前的那個憑證」再請求（不靠 cookie jar，因為登出會清掉瀏覽器端的 cookie）
    recorder.perform(lambda: client.get(PROTECTED, headers={"Cookie": f"{SESSION_COOKIE}={issued_token['token']}"}))
    check_rejected(recorder, "UNAUTHENTICATED", None)
    check_nothing_written(recorder)


@when(parsers.parse('"{name}" opens the sign-in page'))
def _opens_sign_in(recorder, client, name):
    recorder.perform(lambda: client.get("/sign-in", follow_redirects=False))


@then(parsers.re(r'"(?P<name>[^"]+)" is sent to the (?P<page>[a-z ]+) page'))
def _sent_to(recorder, page):
    assert page in PAGES, f"規格的頁名 {page!r} 沒有對應的路徑"
    r = recorder.response
    assert r.status_code == 303, f"應轉址（303），實際 {r.status_code}"
    assert r.headers["location"] == PAGES[page]


# ───────────────────────── IAM-R12 ─────────────────────────


def _session_cookie_header(response) -> str:
    headers = [h for h in _set_cookie_headers(response) if h.startswith(f"{SESSION_COOKIE}=")]
    assert len(headers) == 1, f"應該恰有 1 個 {SESSION_COOKIE} cookie，實際 {headers}"
    return headers[0]


def _attrs(header: str) -> dict[str, str]:
    out = {}
    for part in header.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        out[key.lower()] = value
    return out


@then("the session cookie is HttpOnly")
def _httponly(recorder):
    assert "httponly" in _attrs(_session_cookie_header(recorder.response))


@then("its SameSite attribute is Lax or Strict")
def _samesite(recorder):
    assert _attrs(_session_cookie_header(recorder.response)).get("samesite", "").lower() in ("lax", "strict")


@then("it is Secure in production")
def _secure_in_production(recorder, client, db, monkeypatch):
    # 非正式環境（本機與測試用 http）不加 Secure，否則瀏覽器不會送回 cookie；正式環境一定要加
    assert "secure" not in _attrs(_session_cookie_header(recorder.response))
    monkeypatch.setenv("APP_ENV", "production")
    response = post_sign_in(client, "Wen", TEST_PASSWORD)
    assert "secure" in _attrs(_session_cookie_header(response)), "APP_ENV=production 時 session cookie 必須有 Secure"


@when("a state-changing request arrives with the session but without a valid anti-forgery token")
def _without_token(recorder, client):
    recorder.perform(lambda: client.post(STATE_CHANGING, follow_redirects=False))
