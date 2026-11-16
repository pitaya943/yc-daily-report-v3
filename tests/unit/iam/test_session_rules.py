"""IAM-F03 的單元測試：閒置邊界（IAM-R10，D-058）、登出（IAM-R11）、anti-forgery 與 cookie（IAM-R12）。

IAM-R10 不在 tests/implemented.txt（等 T-201 補回報步驟），所以 CI 不會跑那條規則的 scenario；
這裡讓 M1 的 CI 仍驗證到逾時。直接用 `issue_session` 發 session，不經過 scrypt，所以很快。

每個拒絕案例斷言三件事：結果類別、完整錯誤字串（spec 沒寫字串的情況是 None）、資料沒有任何變動。
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.core.session import SESSION_COOKIE, issue_session
from app.main import create_app
from tests.steps.common.steps import diff, take_snapshot

CSRF = "X-CSRF-Token"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def wen(db):
    """Wen 的 session（現在發出）。回傳 (cookie 標頭, anti-forgery token)。"""
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = 'Wen'")
        account_id = cur.fetchone()[0]
    issued = issue_session(db, account_id)
    db.commit()
    return {"Cookie": f"{SESSION_COOKIE}={issued.token}"}, issued.anti_forgery_token


def assert_rejected(response, status: int, outcome: str):
    assert response.status_code == status
    assert response.json() == {"outcome": outcome, "message": None}


@pytest.mark.parametrize(
    ("idle", "accepted"),
    [
        (timedelta(0), True),
        (timedelta(minutes=29, seconds=59), True),
        (timedelta(minutes=30), False),  # 剛好 30 分鐘就算逾時
        (timedelta(minutes=30, seconds=1), False),
        (timedelta(hours=40), False),
    ],
)
def test_idle_boundary(client, db, wen, idle, accepted):
    headers, _ = wen
    clock.advance(idle)
    before = take_snapshot(db)
    response = client.get("/session", headers=headers)
    changes = diff(before, take_snapshot(db))
    if accepted:
        assert response.status_code == 200
        assert response.json()["name"] == "Wen"
    else:
        assert_rejected(response, 401, "UNAUTHENTICATED")
        assert changes == {}, f"被拒絕的請求不可改動資料：{changes}"  # 連 session 列都不刪、不更新


def test_use_restarts_the_idle_window(client, db, wen):
    headers, _ = wen
    for _ in range(3):  # 每次都在 29:59 使用；總共已超過 30 分鐘仍有效
        clock.advance(timedelta(minutes=29, seconds=59))
        assert client.get("/session", headers=headers).status_code == 200
    clock.advance(timedelta(minutes=30))  # 最後一次使用後閒置滿 30 分鐘
    assert_rejected(client.get("/session", headers=headers), 401, "UNAUTHENTICATED")


def test_a_session_is_not_capped_by_its_age(client, wen):
    """Activity restarts the idle window：登入 40 分鐘、10 分鐘前用過，仍有效（沒有絕對存活上限）。"""
    headers, _ = wen
    clock.advance(timedelta(minutes=30))
    clock.advance(timedelta(minutes=-20))  # 回到「登入後 10 分鐘」，用一次
    assert client.get("/session", headers=headers).status_code == 200
    clock.advance(timedelta(minutes=30))  # 登入後 40 分鐘，距離上次使用 30 分鐘 → 逾時
    assert_rejected(client.get("/session", headers=headers), 401, "UNAUTHENTICATED")


def test_no_cookie_or_unknown_token_is_unauthenticated(client, db):
    before = take_snapshot(db)
    assert_rejected(client.get("/session"), 401, "UNAUTHENTICATED")
    assert_rejected(client.get("/session", headers={"Cookie": f"{SESSION_COOKIE}=nope"}), 401, "UNAUTHENTICATED")
    assert diff(before, take_snapshot(db)) == {}


def test_archived_account_session_is_rejected(client, db, wen):
    headers, _ = wen
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = 'Wen'")
    db.commit()
    before = take_snapshot(db)
    assert_rejected(client.get("/session", headers=headers), 401, "UNAUTHENTICATED")
    assert diff(before, take_snapshot(db)) == {}


def test_sign_out_ends_the_session_immediately(client, db, wen):
    headers, csrf = wen
    response = client.post("/sign-out", headers={**headers, CSRF: csrf}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/sign-in"
    assert f"{SESSION_COOKIE}=" in response.headers["set-cookie"]  # 清掉瀏覽器端的 cookie
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.sessions")
        assert cur.fetchone()[0] == 0
    db.rollback()
    before = take_snapshot(db)
    assert_rejected(client.get("/session", headers=headers), 401, "UNAUTHENTICATED")
    assert diff(before, take_snapshot(db)) == {}


def test_sign_out_only_ends_that_session(client, db, wen):
    headers, csrf = wen
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = 'Wen'")
        other = issue_session(db, cur.fetchone()[0])
    db.commit()
    client.post("/sign-out", headers={**headers, CSRF: csrf})
    assert client.get("/session", headers={"Cookie": f"{SESSION_COOKIE}={other.token}"}).status_code == 200


@pytest.mark.parametrize("token", [None, "", "wrong", "x" * 43])
def test_state_changing_request_needs_a_valid_anti_forgery_token(client, db, wen, token):
    headers, csrf = wen
    assert token != csrf
    if token is not None:
        headers = {**headers, CSRF: token}
    before = take_snapshot(db)
    response = client.post("/sign-out", headers=headers, follow_redirects=False)
    assert_rejected(response, 403, "FORBIDDEN")
    changes = diff(before, take_snapshot(db))
    assert list(changes) == ["audit_log"], f"只能新增一列 ACCESS_DENIED：{changes}"
    assert changes["audit_log"]["removed"] == [] and len(changes["audit_log"]["added"]) == 1
    with db.cursor() as cur:
        cur.execute("select type, actor_name from yc_v3.audit_log")
        assert cur.fetchall() == [("ACCESS_DENIED", "Wen")]
    db.rollback()
    assert client.get("/session", headers=wen[0]).status_code == 200  # session 沒被登出


def test_read_requests_do_not_need_a_token(client, wen):
    assert client.get("/session", headers=wen[0]).status_code == 200


def test_an_expired_session_is_unauthenticated_before_forbidden(client, db, wen):
    """檢查順序：先看 session（閒置逾時 → UNAUTHENTICATED，不寫稽核），才看 anti-forgery。"""
    headers, _ = wen
    clock.advance(timedelta(minutes=30))
    before = take_snapshot(db)
    assert_rejected(client.post("/sign-out", headers=headers), 401, "UNAUTHENTICATED")
    assert diff(before, take_snapshot(db)) == {}


def test_cookie_is_http_only_lax_and_has_no_lifetime(client, db, monkeypatch):
    from tests.steps.common.session import TEST_PASSWORD, post_sign_in, set_password

    set_password(db, "Wen")
    header = post_sign_in(client, "Wen", TEST_PASSWORD).headers.get_list("set-cookie")[0].lower()
    attrs = {p.strip().split("=")[0] for p in header.split(";")[1:]}
    assert "httponly" in attrs and "samesite=lax" in header.replace(" ", "")
    assert not attrs & {"max-age", "expires", "secure"}
    monkeypatch.setenv("APP_ENV", "production")
    assert "secure" in post_sign_in(client, "Wen", TEST_PASSWORD).headers.get_list("set-cookie")[0].lower()


def test_signed_in_person_opening_the_sign_in_page_is_redirected(client, db, wen):
    headers, _ = wen
    before = take_snapshot(db)
    response = client.get("/sign-in", headers=headers, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/reports"
    assert diff(before, take_snapshot(db)) == {}


def test_expired_session_still_sees_the_sign_in_page(client, wen):
    headers, _ = wen
    clock.advance(timedelta(minutes=30))
    assert client.get("/sign-in", headers=headers, follow_redirects=False).status_code == 200
