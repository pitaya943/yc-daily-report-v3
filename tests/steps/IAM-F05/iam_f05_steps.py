"""IAM-F05 Owner 管理管理員的步驟（IAM-R20、R21、R22；T-304）。

設計：
- 動作一律走 `recorder.perform`，請求走真的 HTTP（TestClient），帶 session cookie 與 `X-CSRF-Token`（D-080）。
  路徑（D-118）：`POST /accounts/{id}/archive|restore`、`POST /accounts/{id}`（改區域）、`POST /accounts/{id}/password`（重設密碼）、
  `POST /accounts/{id}/role`（切換角色，T-304 新增）。
- 行為者就是共用 `client` 的 session 主人（scenario 的 Given 已登入）；動作之前若還沒登入才登入，登入寫的 session 不算動作造成的變動。
- 「tries to …」的請求內容都是**合法的**（新密碼、新區域、新角色都合規），所以拒絕的唯一原因是權限或自我保護。
- 步驟文字在新增前已 `grep -rn` 過全部步驟檔（pitfall #26）：`tries to <action> "<target>"`、`switches "<name>" to role "<role>"`、
  `"<name>" has role "<role>"` 是這個檔案新增的；其餘（`creates an account with role`、`archives`、`cannot sign in`、
  `the request is rejected as …`、`nothing is written …`）沿用 IAM-F04 與 tests/steps/common/ 的定義。
- `an audit row "X" is written`（不帶 actor）由 tests/steps/common/audit_row.py 提供（D-117 S2）。
"""
from __future__ import annotations

from urllib.parse import urlencode

from pytest_bdd import parsers, then, when

from tests.steps.common.audit_row import *  # noqa: F401,F403  (an audit row "X" is written)
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import session_rows, sign_in_with_correct_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)

CSRF_HEADER = "X-CSRF-Token"
NEW_PASSWORD = "newsecret"  # 6–30 字，合規


def account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return row[0]


def account_role(db, name: str) -> str:
    with db.cursor() as cur:
        cur.execute("select role from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return row[0]


def account_values(db, name: str) -> dict:
    with db.cursor() as cur:
        cur.execute("select role, archived, big_meter, zone, password_hash from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return dict(zip(("role", "archived", "big_meter", "zone", "password_hash"), row))


def csrf_token(db, name: str) -> str:
    with db.cursor() as cur:
        cur.execute(
            "select s.anti_forgery_token from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
            "where a.name = %s order by s.id desc limit 1",
            (name,),
        )
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"{name} 沒有 session，請先登入"
    return row[0]


def ensure_signed_in(client, db, name: str) -> None:
    if not session_rows(db, name):
        assert sign_in_with_correct_password(client, db, name).status_code == 303


def post(client, db, actor: str, path: str, fields: list[tuple[str, str]]):
    return client.post(
        path,
        content=urlencode(fields),
        headers={"Content-Type": "application/x-www-form-urlencoded", CSRF_HEADER: csrf_token(db, actor)},
        follow_redirects=False,
    )


# 「tries to <action>」→ (路徑尾巴, 表單欄位)；內容全部合法，拒絕只能是因為權限或自我保護
_ACTIONS = {
    "archive": ("/archive", []),
    "restore": ("/restore", []),
    "reset the password of": ("/password", [("new_password", NEW_PASSWORD), ("password_confirm", NEW_PASSWORD)]),
    "change the zone of": ("", [("zone", "SOUTH")]),
    "change the role of": ("/role", [("role", "USER")]),
}


@when(parsers.re(r'"(?P<actor>[^"]+)" tries to (?P<action>archive|restore|reset the password of|change the zone of|change the role of) "(?P<target>[^"]+)"$'))
def _tries_to(recorder, client, db, actor, action, target):
    ensure_signed_in(client, db, actor)
    tail, fields = _ACTIONS[action]
    path = f"/accounts/{account_id(db, target)}{tail}"
    recorder.perform(lambda: post(client, db, actor, path, fields))


@when(parsers.re(r'"(?P<actor>[^"]+)" switches "(?P<target>[^"]+)" to role "(?P<role>[^"]*)"$'))
def _switches(recorder, client, db, actor, target, role):
    ensure_signed_in(client, db, actor)
    path = f"/accounts/{account_id(db, target)}/role"
    recorder.perform(lambda: post(client, db, actor, path, [("role", role)]))


@then(parsers.parse('"{name}" has role "{role}"'))
def _has_role(recorder, db, name, role):
    assert recorder.response.status_code == 200, f"切換應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"
    assert account_role(db, name) == role, f"{name} 的角色應為 {role}，實際 {account_role(db, name)}"
