"""IAM-F01 的 scenario 沒有逐字涵蓋、但 T-101 的完成條件要求的行為：

- 密碼雜湊（D-056）：格式、salt、比對、被竄改的參數。
- 缺少或不合法的欄位（完成條件 4：伺服器重新驗證每個欄位，缺少的值不補預設值）；每個拒絕都檢查
  結果類別、完整錯誤字串、資料沒有任何變動（不可違反 #5）。
- session 與 `get_current_actor`（完成條件 9）；session cookie 的屬性。
"""
import hashlib

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.core import session as session_core
from app.core.actor import Actor
from app.core.outcomes import Outcome
from app.main import create_app
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, set_password
from tests.steps.common.steps import Recorder, check_rejected, diff

# ───────────────────────── 密碼雜湊 ─────────────────────────


def test_hash_has_algorithm_and_parameter_prefix_and_random_salt():
    a, b = session_core.hash_password("secret1"), session_core.hash_password("secret1")
    assert a.startswith("scrypt$n=131072,r=8,p=1$")  # D-056：N=2^17、r=8、p=1
    assert a != b, "同一個密碼兩次雜湊必須因為隨機 salt 而不同"
    assert "secret1" not in a


def test_verify_accepts_the_right_password_and_rejects_others():
    stored = session_core.hash_password("secret1")
    assert session_core.verify_password("secret1", stored) is True
    assert session_core.verify_password("secret2", stored) is False
    assert session_core.verify_password("", stored) is False


@pytest.mark.parametrize(
    "stored",
    [None, "", "plain-text", "bcrypt$x$y$z", "scrypt$n=3,r=8,p=1$AAAA$AAAA", "scrypt$n=1073741824,r=8,p=1$AAAA$AAAA", "scrypt$n=131072$AAAA$AAAA", "scrypt$n=131072,r=8,p=1$!!$!!"],
)
def test_verify_rejects_missing_or_malformed_hashes_without_raising(stored):
    assert session_core.verify_password("secret1", stored) is False


def test_verify_uses_the_parameters_stored_in_the_string():
    # 日後調整成本時，舊的雜湊仍要能驗證：用較小的 N 手動組一個雜湊
    import base64

    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(b"secret1", salt=salt, n=2**10, r=8, p=1, dklen=32)
    stored = f"scrypt$n=1024,r=8,p=1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    assert session_core.verify_password("secret1", stored) is True
    assert session_core.verify_password("secret2", stored) is False


def test_stored_password_is_a_hash_not_the_password(db):
    set_password(db, "Wen")
    with db.cursor() as cur:
        cur.execute("select password_hash from yc_v3.accounts where name = 'Wen'")
        stored = cur.fetchone()[0]
    assert stored.startswith("scrypt$") and TEST_PASSWORD not in stored


# ───────────────────────── 缺少或不合法的欄位 ─────────────────────────


def _rejected(client, db, send, outcome, message):
    recorder = Recorder(db)
    recorder.perform(send)
    check_rejected(recorder, outcome, message)
    assert diff(recorder.before, recorder.after) == {}, "被拒絕的請求不得改變任何資料"
    assert SESSION_COOKIE not in client.cookies


def test_missing_name_is_invalid_with_the_exact_message(client, db):
    set_password(db, "Wen")
    for body in ({"password": TEST_PASSWORD}, {"name": "", "password": TEST_PASSWORD}, {"name": "   ", "password": TEST_PASSWORD}):
        _rejected(client, db, lambda body=body: client.post("/sign-in", data=body, follow_redirects=False), "INVALID", "請選擇帳戶")


def test_missing_password_is_indistinguishable_from_a_wrong_password(client, db):
    set_password(db, "Wen")
    for body in ({"name": "Wen"}, {"name": "Wen", "password": ""}):
        _rejected(client, db, lambda body=body: client.post("/sign-in", data=body, follow_redirects=False), "UNAUTHENTICATED", "密碼錯誤，請重試")


def test_empty_request_body_is_invalid(client, db):
    _rejected(client, db, lambda: client.post("/sign-in", follow_redirects=False), "INVALID", "請選擇帳戶")


def test_account_outside_the_chosen_group_is_invalid(client, db):
    set_password(db, "Wen")
    # Wen 在 west；選了 south 卻送出 Wen（也包含已封存的 Old：不在名單內，不能因此分辨出它存在）
    for name in ("Wen", "Old"):
        _rejected(
            client, db,
            lambda name=name: client.post("/sign-in", data={"group": "south", "name": name, "password": TEST_PASSWORD}, follow_redirects=False),
            "INVALID", "請選擇帳戶",
        )


def test_unknown_group_is_invalid_on_page_and_on_sign_in(client, db):
    _rejected(client, db, lambda: client.get("/sign-in", params={"group": "everyone"}), "INVALID", None)
    _rejected(client, db, lambda: client.post("/sign-in", data={"group": "everyone", "name": "Wen", "password": "x"}, follow_redirects=False), "INVALID", "請選擇帳戶")


def test_sign_in_with_matching_group_succeeds(client, db):
    set_password(db, "Wen")
    r = client.post("/sign-in", data={"group": "west", "name": "Wen", "password": TEST_PASSWORD}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/reports"


def test_account_without_a_password_cannot_sign_in(client, db):
    # background 的帳戶沒有密碼：不能用空字串、也不能用任何字串登入
    for password in ("", "anything"):
        _rejected(client, db, lambda password=password: post_sign_in(client, "Wen", password), "UNAUTHENTICATED", "密碼錯誤，請重試")


# ───────────────────────── session ─────────────────────────


def test_session_cookie_attributes_and_stored_token(client, db):
    set_password(db, "Wen")
    r = post_sign_in(client, "Wen", TEST_PASSWORD)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie, cookie
    assert "max-age" not in cookie and "expires" not in cookie, "不得發出能活過瀏覽器關閉的憑證（沒有記住我）"
    assert "secure" not in cookie, "只在 APP_ENV=production 時加 Secure"
    token = client.cookies.get(SESSION_COOKIE)
    with db.cursor() as cur:
        cur.execute("select token_hash, anti_forgery_token from yc_v3.sessions")
        (token_hash, anti_forgery), = cur.fetchall()
    db.rollback()
    assert token_hash == hashlib.sha256(token.encode()).hexdigest() and token_hash != token, "資料庫只存憑證的雜湊"
    assert anti_forgery and anti_forgery != token


def test_session_cookie_is_secure_in_production(client, db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    set_password(db, "Wen")
    assert "secure" in post_sign_in(client, "Wen", TEST_PASSWORD).headers["set-cookie"].lower().split("; ")


def test_each_sign_in_gets_a_new_independent_session(client, db):
    set_password(db, "Wen")
    first = post_sign_in(client, "Wen", TEST_PASSWORD).cookies.get(SESSION_COOKIE) or client.cookies.get(SESSION_COOKIE)
    other = TestClient(create_app(), raise_server_exceptions=False)
    post_sign_in(other, "Wen", TEST_PASSWORD)
    assert first != other.cookies.get(SESSION_COOKIE)
    assert session_core.actor_for_token(db, first).name == "Wen"
    db.rollback()


def _app_with_protected_route() -> TestClient:
    router = APIRouter()

    @router.get("/__t__/whoami")
    def whoami(actor: Actor = Depends(session_core.get_current_actor)):
        return {"name": actor.name, "role": actor.role.value}

    app = create_app()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_get_current_actor_rejects_requests_without_a_valid_session(db):
    client = _app_with_protected_route()
    for cookie in (None, "not-a-real-session", ""):
        client.cookies.clear()
        if cookie is not None:
            client.cookies.set(SESSION_COOKIE, cookie)
        r = client.get("/__t__/whoami")
        assert r.status_code == 401 and r.json() == {"outcome": Outcome.UNAUTHENTICATED.value, "message": None}


def test_get_current_actor_returns_the_signed_in_actor(db):
    client = _app_with_protected_route()
    set_password(db, "Admin1")
    post_sign_in(client, "Admin1", TEST_PASSWORD)
    r = client.get("/__t__/whoami")
    assert r.status_code == 200 and r.json() == {"name": "Admin1", "role": "ADMIN"}


def test_an_archived_account_has_no_valid_session(db):
    client = _app_with_protected_route()
    set_password(db, "Wen")
    post_sign_in(client, "Wen", TEST_PASSWORD)
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = 'Wen'")
    db.commit()
    assert client.get("/__t__/whoami").status_code == 401


def test_landing_path_by_role():
    from app.core.actor import Role

    assert session_core.landing_path_for(Role.USER) == "/reports"
    assert session_core.landing_path_for(Role.ADMIN) == "/review"
    assert session_core.landing_path_for(Role.OWNER) == "/review"
    with pytest.raises(ValueError):
        session_core.landing_path_for(Role.SYSTEM)
