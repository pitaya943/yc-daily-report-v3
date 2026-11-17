"""IAM-F04 帳戶生命週期與薪資設定的步驟（IAM-R13、R15～R19；IAM-R14 在 T-306）。

設計：
- 動作一律走 `recorder.perform`，請求走真的 HTTP（TestClient），帶 session cookie 與 `X-CSRF-Token`（D-080）。
  路徑（D-118）：`GET/POST /accounts`、`GET/POST /accounts/{id}`、`POST /accounts/{id}/archive|restore|delete|deactivate`。
- 誰在動作：scenario 常沒有寫 `"<name>" is signed in`（例如 IAM-R15 的固定薪資），所以動作之前先確保行為者登入。
  共用的 `client` 只有一份 cookie；`"Wen" is signed in` 之後又由 Admin1 動作（IAM-R17 的 AD-13）時，
  Admin1 用另一個 TestClient，Wen 的 cookie 留在 `client`，之後才能檢查「Wen 的 session 被拒絕」。
  FORBIDDEN 的資料斷言（共用步驟）以 `client` 的 cookie 認定行為者，所以行為者與 `client` 是同一人時一律用 `client`。
- 共用步驟（outcome、拒絕、稽核、登入）來自 tests/steps/common/，這裡不重新定義（pitfall #26）。
  `the outcome is <outcome> with message "<message>"`（D-117 S1）由 T-305 新增，這裡不定義。
- 本檔定義的步驟文字（全域註冊，新增前已 grep 過同文字）：見檔案內各個 @given／@when／@then。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core import session as session_core
from app.main import create_app
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, set_password, sign_in_with_correct_password
from tests.steps.common.spec_tables import outcome_http_table
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)
from tests.steps.common.steps import check_nothing_written

CSRF_HEADER = "X-CSRF-Token"
ACCOUNTS = "/accounts"


# ───────────────────────── 輔助（test_account_details.py 也用） ─────────────────────────


def account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return row[0]


def account_values(db, name: str) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "select role, zone, big_meter, archived, insured, insurance_deduction, uninsured_rate_bp, uninsured_exempt, "
            "fixed_salary, pays_fixed_salary_every_period, password_hash from yc_v3.accounts where name = %s",
            (name,),
        )
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    keys = ("role zone big_meter archived insured insurance_deduction uninsured_rate_bp uninsured_exempt "
            "fixed_salary pays_fixed_salary_every_period password_hash").split()
    return dict(zip(keys, row))


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


def cookie_owner(client, db) -> str | None:
    token = client.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    actor = session_core.actor_for_token(db, token)
    db.rollback()
    return None if actor is None else actor.name


@pytest.fixture
def others() -> dict:
    """共用 `client` 以外的行為者各自的 TestClient（名稱 → client）。"""
    return {}


def client_for(client, db, others: dict, name: str) -> TestClient:
    """以 `name` 登入的 client。動作「之前」呼叫；登入寫的 session 不算動作造成的資料變動。"""
    owner = cookie_owner(client, db)
    if owner == name:
        return client
    if owner is None:
        assert sign_in_with_correct_password(client, db, name).status_code == 303
        return client
    if name not in others:
        other = TestClient(create_app(), raise_server_exceptions=False)
        assert sign_in_with_correct_password(other, db, name).status_code == 303
        others[name] = other
    return others[name]


def post(c: TestClient, db, actor: str, path: str, fields: list[tuple[str, str]]):
    return c.post(
        path,
        content=urlencode(fields),
        headers={"Content-Type": "application/x-www-form-urlencoded", CSRF_HEADER: csrf_token(db, actor)},
        follow_redirects=False,
    )


@pytest.fixture
def last() -> dict:
    """scenario 內最近一次動作的資訊。"""
    return {}


class _Rows(HTMLParser):
    """帳戶清單頁：每個 `<tr data-account-name=…>` 一列。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "data-account-name" in a:
            self.rows.append({"name": a["data-account-name"], "role": a.get("data-role", ""), "zone": a.get("data-zone", "")})


def listed_names(html: str, *, option_text: bool = True) -> set[str]:
    """頁面上以 `>名稱<` 出現的文字（登入名單與共同作業者選單都是這種形狀）。"""
    return set(re.findall(r">\s*([^<>\s][^<>]*?)\s*<", html))


# ───────────────────────── Given ─────────────────────────


@given(parsers.re(r'"(?P<admin>[^"]+)" moved "(?P<name>[^"]+)" to zone (?P<zone>WEST|SOUTH)$'))
def _moved(client, db, others, admin, name, zone):
    """IAM-R16：由管理員透過產品改區域（不是直接改資料庫），然後讓 Wen 登入，之後的 `opens the daily report form` 才有 session。"""
    c = client_for(client, db, others, admin)
    r = post(c, db, admin, f"{ACCOUNTS}/{account_id(db, name)}", [("zone", zone)])
    assert r.status_code == 200, f"改區域應成功（200），實際 {r.status_code}：{r.text[:200]}"
    if cookie_owner(client, db) != name:
        assert sign_in_with_correct_password(client, db, name).status_code == 303


@given(parsers.parse('"{name}" has {n:d} reports'))
def _has_reports(db, name, n):
    submitter = account_id(db, name)
    with db.cursor() as cur:
        cur.execute("select zone, big_meter from yc_v3.accounts where id = %s", (submitter,))
        zone, big = cur.fetchone()
        for i in range(n):
            cur.execute(
                "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at) "
                "values (%s, %s, %s, 'PENDING', now(), now())",
                (submitter, f"2026-11-{10 + i:02d}", "BIG_METER" if big else zone),
            )
    db.commit()


@given(parsers.parse('"{name}" is archived'))
def _is_archived(db, name):
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = %s", (name,))
        assert cur.rowcount == 1
    db.commit()


# ───────────────────────── When ─────────────────────────

_CREATE_DEFAULTS = {"name": "NewHire", "password": "secret1", "zone": "SOUTH", "role": "USER"}
_VALUES = {"(empty)": ""}


def _create_value(field: str, value: str) -> str:
    if value in _VALUES:
        return _VALUES[value]
    m = re.fullmatch(r"(\d+) characters", value)
    if m:
        return ("字" if field == "name" else "p") * int(m.group(1))
    return value


def _create(recorder, client, db, others, last, admin, fields):
    c = client_for(client, db, others, admin)
    last.update(created=fields.get("name"))
    recorder.perform(lambda: post(c, db, admin, ACCOUNTS, list(fields.items())))


@when(parsers.re(r'"(?P<admin>[^"]+)" creates account "(?P<name>[^"]+)" with role (?P<role>\w+), zone (?P<zone>\w+), and a (?P<n>\d+)-character password$'))
def _creates(recorder, client, db, others, last, admin, name, role, zone, n):
    _create(recorder, client, db, others, last, admin, {"name": name, "password": "p" * int(n), "zone": zone, "role": role})


@when(parsers.re(r'"(?P<admin>[^"]+)" creates an account with (?P<field>display name|password|zone|role) "(?P<value>[^"]*)"$'))
def _creates_with(recorder, client, db, others, last, admin, field, value):
    key = {"display name": "name"}.get(field, field)
    fields = dict(_CREATE_DEFAULTS)
    fields[key] = _create_value(key, value)
    _create(recorder, client, db, others, last, admin, fields)


@when(parsers.re(r'"(?P<admin>[^"]+)" opens account management$'))
def _opens_management(recorder, client, db, others, admin):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: c.get(ACCOUNTS))


_CHOICES = {
    "enrolled": lambda v: [("insurance", "enrolled"), ("deduction", v)],
    "not enrolled, rate": lambda v: [("insurance", "not_enrolled_rate"), ("rate", v)],
    "not enrolled, exempt": lambda v: [("insurance", "not_enrolled_exempt")],
}


@when(parsers.re(r'"(?P<admin>[^"]+)" sets "(?P<name>[^"]+)" to (?P<choice>enrolled|not enrolled, rate|not enrolled, exempt) with value "(?P<value>[^"]*)"$'))
def _sets_insurance(recorder, client, db, others, admin, name, choice, value):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: post(c, db, admin, f"{ACCOUNTS}/{account_id(db, name)}", _CHOICES[choice](value)))


@when(parsers.re(r'"(?P<admin>[^"]+)" sets the fixed salary of "(?P<name>[^"]+)" to "(?P<value>[^"]*)"$'))
def _sets_fixed_salary(recorder, client, db, others, admin, name, value):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: post(c, db, admin, f"{ACCOUNTS}/{account_id(db, name)}", [("fixed_salary", value)]))


@when(parsers.re(r'"(?P<admin>[^"]+)" turns on the big-meter flag for "(?P<name>[^"]+)"$'))
def _turns_on_big_meter(recorder, client, db, others, admin, name):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: post(c, db, admin, f"{ACCOUNTS}/{account_id(db, name)}", [("big_meter", "on")]))


@when(parsers.re(r'"(?P<admin>[^"]+)" (?P<verb>archives|restores) "(?P<name>[^"]+)"$'))
def _archives_or_restores(recorder, client, db, others, admin, verb, name):
    c = client_for(client, db, others, admin)
    path = f"{ACCOUNTS}/{account_id(db, name)}/{'archive' if verb == 'archives' else 'restore'}"
    recorder.perform(lambda: post(c, db, admin, path, []))


@when(parsers.re(r'"(?P<admin>[^"]+)" tries to (?P<action>permanently delete|deactivate) the account "(?P<name>[^"]+)"$'))
def _tries_forbidden_action(recorder, client, db, others, admin, action, name):
    c = client_for(client, db, others, admin)
    path = f"{ACCOUNTS}/{account_id(db, name)}/{'delete' if action == 'permanently delete' else 'deactivate'}"
    recorder.perform(lambda: post(c, db, admin, path, []))


# ───────────────────────── Then ─────────────────────────


@then(parsers.parse('account "{name}" exists with role {role}, zone {zone}, and big-meter off'))
def _account_exists(recorder, db, name, role, zone):
    assert recorder.response.status_code == 200, f"建立應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"
    values = account_values(db, name)
    assert (values["role"], values["zone"], values["big_meter"], values["archived"]) == (role, zone, False, False), values
    assert values["password_hash"] and values["password_hash"].startswith("scrypt$"), "密碼必須以雜湊儲存"


@then("the account is created")
def _account_created(recorder, db, last):
    assert recorder.response.status_code == 200, f"建立應成功（200），實際 {recorder.response.status_code}：{recorder.response.text[:200]}"
    added = recorder.changes().get("accounts", {}).get("added", [])
    assert len(added) == 1, f"應新增 1 個帳戶，實際 {len(added)}：{added}"
    assert account_values(db, last["created"])["role"] == "USER"


@then("no account is created")
def _no_account_created(recorder):
    assert "accounts" not in recorder.changes(), f"不該有帳戶變動：{recorder.changes().get('accounts')}"
    check_nothing_written(recorder)  # 比規格更嚴格：整個資料庫都沒有變動（AGENTS.md 不可違反 #5），列在 PR 說明


@then("the list contains only USER accounts, West before South")
def _list_contains_users(recorder, db):
    r = recorder.response
    assert r.status_code == 200, f"清單應為 200，實際 {r.status_code}：{r.text[:200]}"
    parser = _Rows()
    parser.feed(r.text)
    with db.cursor() as cur:
        cur.execute("select name from yc_v3.accounts where role = 'USER'")
        expected = {row[0] for row in cur.fetchall()}
    db.rollback()
    assert {row["role"] for row in parser.rows} == {"USER"}, parser.rows
    assert {row["name"] for row in parser.rows} == expected, f"清單應列出全部 USER（含已封存，才能復原）：{parser.rows}"
    zones = [row["zone"] for row in parser.rows]
    assert zones == sorted(zones, key=["WEST", "SOUTH"].index), f"西區必須排在南區之前：{zones}"


def _fresh() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _sign_in_names(db, group: str) -> set[str]:
    r = _fresh().get("/sign-in", params={"group": group})
    assert r.status_code == 200, r.status_code
    return listed_names(r.text)


def _picker_names(db, viewer: str) -> set[str]:
    c = _fresh()
    assert sign_in_with_correct_password(c, db, viewer).status_code == 303
    r = c.get("/reports")
    assert r.status_code == 200, r.status_code
    return listed_names(r.text)


@then(parsers.parse('"{name}" cannot sign in'))
def _cannot_sign_in(db, name):
    set_password(db, name)
    c = _fresh()
    r = post_sign_in(c, name, TEST_PASSWORD)
    assert r.status_code == 401 and SESSION_COOKIE not in c.cookies, f"封存的帳戶不能登入：{r.status_code}"


@then(parsers.parse('"{name}" can sign in'))
def _can_sign_in(db, name):
    set_password(db, name)
    c = _fresh()
    r = post_sign_in(c, name, TEST_PASSWORD)
    assert r.status_code == 303 and SESSION_COOKIE in c.cookies, f"應能登入：{r.status_code}"


@then(parsers.parse('"{name}" is absent from the sign-in name list and the collaborator picker'))
def _absent(db, name):
    # 先確認同組的其他人看得到（否則「看不到」可能只是頁面壞了）
    assert "Wan" in _sign_in_names(db, "west") and "Wei" in _picker_names(db, "Wan")
    assert name not in _sign_in_names(db, "west"), "登入名單不該有封存的帳戶"
    assert name not in _picker_names(db, "Wan"), "共同作業者選單不該有封存的帳戶"


@then(parsers.parse('"{name}" is in the sign-in name list and the collaborator picker'))
def _present(db, name):
    assert name in _sign_in_names(db, "west"), "登入名單應有復原的帳戶"
    assert name in _picker_names(db, "Wan"), "共同作業者選單應有復原的帳戶"


@then(parsers.parse('"{name}" still has {n:d} reports'))
def _still_has(recorder, db, name, n):
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.reports where submitter_id = %s", (account_id(db, name),))
        count = cur.fetchone()[0]
    db.rollback()
    assert count == n, f"應仍有 {n} 張回報，實際 {count}"
    touched = {t for t in recorder.changes() if t in {"reports", "report_items", "report_crew", "report_shares"}}
    assert not touched, f"封存不得動到回報資料：{touched}"  # 比規格更嚴格：回報相關表完全不變


@then(parsers.parse('a later protected request from the session of "{name}" is rejected as UNAUTHENTICATED'))
def _later_request_rejected(client, db, name):
    r = client.get("/session")
    assert r.status_code == outcome_http_table()["UNAUTHENTICATED"], f"應為 401，實際 {r.status_code}"
    body = r.json()
    assert (body["outcome"], body["message"]) == ("UNAUTHENTICATED", None), body


@then(parsers.parse('"{name}" and all records of "{name2}" are unchanged'))
def _unchanged(recorder, name, name2):
    check_nothing_written(recorder)
