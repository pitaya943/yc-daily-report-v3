"""登入的共用步驟（T-101 完成條件 10）：之後每個 feature 都會用到。

其他 feature 的步驟檔這樣使用（與 tests/steps/common/steps.py 的用法相同）：

    from tests.steps.common.session import *   # noqa: F401,F403

提供的步驟：
    Given/Then  "<name>" is signed in
    When        "<name>" signs in with the correct password

設計：
- 測試用的密碼在這個檔案**定義一次**（`TEST_PASSWORD`）。background 的帳戶沒有密碼（不修改 tests/support/background.py），
  所以步驟在動作前，用產品的 `hash_password` 把它寫進該帳戶；不是直接塞一個寫死的雜湊，
  這樣「密碼怎麼雜湊」仍然只有產品程式一個定義。
- 只替「這個動作要登入的那個帳戶」設定密碼：每次 scrypt 要約零點幾秒，替所有帳戶設定會讓每個 scenario 慢好幾秒。
- 登入動作走 `recorder.perform`，所以「資料有沒有變動」的斷言看得到登入本身寫了什麼。
"""
from __future__ import annotations

from pytest_bdd import given, parsers, then, when

from app.core import session as session_core
from app.core.clock import clock

# 所有 scenario 共用的測試密碼；規格 R03 的 "correct" 就是這個值。
TEST_PASSWORD = "correct"
SESSION_COOKIE = session_core.SESSION_COOKIE


def set_password(db, name: str, password: str = TEST_PASSWORD) -> None:
    """把密碼寫進帳戶（沒有這個帳戶就什麼都不做：「查無帳戶」本身是要測的情況）。"""
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set password_hash = %s where name = %s", (session_core.hash_password(password), name))
    db.commit()


def post_sign_in(client, name: str, password: str):
    """送出登入表單。不跟隨轉址：落地頁是由轉址的目的地斷言的（D-057）。"""
    return client.post("/sign-in", data={"name": name, "password": password}, follow_redirects=False)


def sign_in_with_correct_password(client, db, name: str):
    set_password(db, name)
    return post_sign_in(client, name, TEST_PASSWORD)


def session_rows(db, name: str) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            "select s.id, s.created_at, s.last_used_at from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
            "where a.name = %s order by s.id",
            (name,),
        )
        rows = cur.fetchall()
    db.rollback()
    return rows


def assert_signed_in(client, db, name: str, response) -> None:
    """登入成功的樣子：回應是轉址並帶 session cookie、cookie 對得到這個帳戶、資料庫有一列剛發出的 session。"""
    assert response.status_code == 303, f"登入成功應轉址（303），實際 {response.status_code}：{response.text[:200]}"
    token = client.cookies.get(SESSION_COOKIE)
    assert token, "登入成功後應收到 session cookie"
    with db.cursor() as cur:
        cur.execute("select a.id from yc_v3.accounts a where a.name = %s", (name,))
        account_id = cur.fetchone()[0]
    actor = session_core.actor_for_token(db, token)
    db.rollback()
    assert actor is not None, "session cookie 在資料庫裡找不到對應的 session"
    assert (actor.id, actor.name) == (account_id, name), f"session 屬於 {actor.name}，不是 {name}"
    rows = session_rows(db, name)
    assert len(rows) == 1, f"應該只有 1 列 session，實際 {len(rows)} 列"
    _, created_at, last_used_at = rows[0]
    assert created_at == last_used_at == clock.now(), "新 session 的建立時間與最後使用時間都應是現在"


@given(parsers.parse('"{name}" is signed in'))
def _given_signed_in(client, db, name):
    response = sign_in_with_correct_password(client, db, name)
    assert_signed_in(client, db, name, response)


@when(parsers.parse('"{name}" signs in with the correct password'))
def _when_signs_in(recorder, client, db, name):
    set_password(db, name)  # 動作「之前」寫入，不算動作造成的資料變動
    recorder.perform(lambda: post_sign_in(client, name, TEST_PASSWORD))


@then(parsers.parse('"{name}" is signed in'))
def _then_signed_in(recorder, client, db, name):
    assert_signed_in(client, db, name, recorder.response)
