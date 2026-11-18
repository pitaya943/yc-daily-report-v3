"""IAM-F07 銀行帳號遮罩與顯示的步驟，以及 IAM-F04 的 IAM-R14（銀行帳號格式、改為轉帳前須有帳號）。

設計：
- 動作一律走 `recorder.perform`，請求走真的 HTTP（TestClient），帶 session cookie 與 `X-CSRF-Token`（D-080）。
  路徑（D-118）：`GET /accounts/{id}/bank-number`、`POST /accounts/{id}/bank-number/reveal`、
  `POST /accounts/{id}/bank-number`、`POST /accounts/{id}/payment-method`。
- 金鑰只在測試裡設定：`bank_key` fixture 產生一把隨機的測試金鑰放進環境變數（`monkeypatch`，scenario 結束就還原）。
  repo 裡沒有任何真的金鑰，也沒有寫死的測試金鑰。`the encryption key is missing` 把它從環境拿掉。
  需要金鑰的步驟（Background 的 `has bank number`、設定銀行帳號）才要求這個 fixture，所以其他 feature 的測試不受影響。
- 共用步驟（outcome、拒絕、稽核、登入）來自 tests/steps/common/，這裡不重新定義（pitfall #26）。
  `the stored value does not contain` 之類只屬於這個 feature 的步驟，新增前已 grep 過同文字。
- 誰在動作：與 IAM-F04 的步驟相同的做法（`client_for`）。共用的 `client` 只有一份 cookie；FORBIDDEN 的資料斷言以 `client` 的
  cookie 認定行為者，所以行為者與 `client` 是同一人時一律用 `client`。
- Given 步驟直接寫資料庫，但密文由「產品的 crypto 模組」產生，所以 Background 與產品用同一個加密格式。
"""
from __future__ import annotations

import base64
import html
import os
import re
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core import session as session_core
from app.main import create_app
from tests.steps.common.audit_description import *  # noqa: F401,F403  (the audit description contains ...)
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import SESSION_COOKIE, sign_in_with_correct_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)
from tests.steps.common.steps import claim_audit_row

CSRF_HEADER = "X-CSRF-Token"
KEY_ENV = "BANK_NUMBER_KEY"


# ───────────────────────── 輔助（test_bank_number_details.py 也用） ─────────────────────────


def bank_path(account_id: int, suffix: str = "") -> str:
    return f"/accounts/{account_id}/bank-number{suffix}"


def account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return row[0]


def stored(db, name: str) -> tuple[bytes | None, str]:
    """(銀行帳號密文, 發薪方式)。"""
    with db.cursor() as cur:
        cur.execute("select bank_number_cipher, payment_method from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"沒有帳戶 {name}"
    return (None if row[0] is None else bytes(row[0])), row[1]


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


_VALUE = re.compile(r'<span id="bank-value" class="bank-value" data-state="([a-z]+)">([^<]*)</span>')


def value_shown(response) -> tuple[str, str]:
    """回應裡顯示的銀行帳號：(data-state, 顯示的文字)。整頁與 reveal 的片段都有同一段。"""
    assert response.status_code == 200, f"應為 200，實際 {response.status_code}：{response.text[:200]}"
    found = _VALUE.findall(response.text)
    assert len(found) == 1, f"回應裡應該恰有 1 個銀行帳號的值，實際 {len(found)} 個"
    state, text = found[0]
    return state, html.unescape(text)


def new_test_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def bank_key(monkeypatch) -> str:
    """測試用的金鑰：每個 scenario 隨機產生，只放在這個 scenario 的環境變數裡。"""
    key = new_test_key()
    monkeypatch.setenv(KEY_ENV, key)
    return key


def store_bank_number(db, name: str, number: str, key: str | None = None) -> None:
    """用產品的 crypto 模組加密後直接寫進資料庫（Given 步驟；不經過 HTTP）。"""
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    raw_key = base64.b64decode(key or os.environ[KEY_ENV])
    account = account_id(db, name)
    with db.cursor() as cur:
        cur.execute(
            "update yc_v3.accounts set bank_number_cipher = %s where id = %s",
            (crypto.encrypt(raw_key, number, crypto.aad_for(account)), account),
        )
        assert cur.rowcount == 1
    db.commit()


# ───────────────────────── Given ─────────────────────────


@given(parsers.parse('"{name}" has bank number "{number}"'))
def _has_bank_number(db, bank_key, name, number):
    store_bank_number(db, name, number, bank_key)


@given("the encryption key is missing")
def _key_missing(bank_key, monkeypatch):
    # 先要求 bank_key：Background 已經把金鑰放進環境；這裡把它拿掉，之後的請求就像部署時沒有設定金鑰
    monkeypatch.delenv(KEY_ENV, raising=False)


@given(parsers.parse('"{name}" is paid by CASH and has no bank number'))
def _cash_no_number(db, name):
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set payment_method = 'CASH', bank_number_cipher = null where name = %s", (name,))
        assert cur.rowcount == 1
    db.commit()


# ───────────────────────── When ─────────────────────────


@when(parsers.re(r'"(?P<viewer>[^"]+)" views the bank number of "(?P<name>[^"]+)"$'))
def _views(recorder, client, db, others, viewer, name):
    c = client_for(client, db, others, viewer)
    recorder.perform(lambda: c.get(bank_path(account_id(db, name))))


@when(parsers.re(r'"(?P<viewer>[^"]+)" reveals the bank number of "(?P<name>[^"]+)"$'))
def _reveals(recorder, client, db, others, viewer, name):
    c = client_for(client, db, others, viewer)
    recorder.perform(lambda: post(c, db, viewer, bank_path(account_id(db, name), "/reveal"), []))


@when(parsers.re(r'"(?P<admin>[^"]+)" sets the bank number of "(?P<name>[^"]+)" to "(?P<number>[^"]*)"$'))
def _sets_number(recorder, client, db, others, bank_key, admin, name, number):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: post(c, db, admin, bank_path(account_id(db, name)), [("bank_number", number)]))


@when(parsers.re(r'"(?P<admin>[^"]+)" sets the payment method of "(?P<name>[^"]+)" to (?P<method>TRANSFER|CASH)$'))
def _sets_method(recorder, client, db, others, admin, name, method):
    c = client_for(client, db, others, admin)
    recorder.perform(lambda: post(c, db, admin, f"/accounts/{account_id(db, name)}/payment-method", [("payment_method", method)]))


# ───────────────────────── Then ─────────────────────────


@then(parsers.parse('the value shown ends with "{tail}" and shows no other digit'))
def _value_masked(recorder, tail):
    state, text = value_shown(recorder.response)
    assert state == "masked", f"預設應顯示遮罩，實際狀態 {state}：{text!r}"
    assert text.endswith(tail), f"應以 {tail!r} 結尾，實際 {text!r}"
    assert re.findall(r"[0-9]", text) == list(tail), f"除了末四碼不得顯示任何其他數字，實際 {text!r}"


@then(parsers.parse('the value shown is "{value}"'))
def _value_is(recorder, value):
    _, text = value_shown(recorder.response)
    assert text == value, f"應顯示 {value!r}，實際 {text!r}"


@then(parsers.re(r'an audit row "(?P<type_>[A-Z_]+)" is written with actor "(?P<actor>[^"]+)" naming "(?P<named>[^"]+)"$'))
def _audit_row_naming(recorder, db, type_, actor, named):
    claim_audit_row(recorder, db, type_, actor)
    row_text = recorder.claimed[-1]
    with db.cursor() as cur:
        cur.execute("select x::text, description from yc_v3.audit_log x")
        descriptions = [r[1] for r in cur.fetchall() if r[0] == row_text]
    db.rollback()
    assert len(descriptions) == 1, f"找不到剛認領的稽核列：{row_text}"
    assert named in descriptions[0], f"稽核說明應點名「{named}」，實際「{descriptions[0]}」"


@then(parsers.parse('the stored value does not contain "{plain}"'))
def _stored_not_plain(recorder, db, plain):
    """整個資料庫（所有資料表的所有欄位，含稽核說明）都找不到明文，而且密文確實存進去了（不是因為什麼都沒存才通過）。"""
    digits = plain.replace("-", "")
    cipher, _ = stored(db, "Wen")
    assert cipher is not None, "應該存了密文"
    assert digits.encode("ascii") not in cipher, "密文內含明文位元組"
    from tests.steps.common.steps import take_snapshot

    for table, rows in take_snapshot(db).items():
        for row in rows:
            assert plain not in row and digits not in row, f"{table} 的資料列含明文：{row[:80]}"
            assert digits.encode("ascii").hex() not in row, f"{table} 的資料列含明文的十六進位"
