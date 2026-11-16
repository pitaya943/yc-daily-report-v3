"""IAM-F01 登入的步驟。

這個檔案由同目錄的 conftest.py 以 plugin 註冊成「全域」步驟：scenario 是由 tests/test_spec.py 展開的，
步驟若只放在子目錄的 conftest，test_spec.py 看不到。檔名刻意帶 feature ID，避免與其他 feature 的步驟檔同名。
"""
from __future__ import annotations

from html.parser import HTMLParser

from pytest_bdd import parsers, then, when

from tests.steps.common.session import SESSION_COOKIE, post_sign_in, set_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕結果與資料變動的共用步驟)
from tests.steps.common.session import *  # noqa: F401,F403  (is signed in、signs in with the correct password)

# D-057：登入後的落地頁路徑。規格的頁名 → 路徑；頁面本身由 M2、M3 實作，這裡斷言轉址的目的地。
LANDING_PATHS = {"daily report": "/reports", "confirmation": "/review"}
# D-069：migration 0004 新增的表；登入失敗時一定會寫入，不屬於「資料沒有變動」的範圍
LOCKOUT_TABLES = frozenset({"sign_in_failures", "sign_in_attempts"})


class _Options(HTMLParser):
    """取出名單 <select name="name"> 底下有值的 <option>（沒有值的是「請選擇帳戶」提示列）。"""

    def __init__(self) -> None:
        super().__init__()
        self._in_select = False
        self._value: str | None = None
        self.names: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "select":
            self._in_select = a.get("name") == "name"
        elif tag == "option" and self._in_select:
            self._value = a.get("value") or None

    def handle_endtag(self, tag):
        if tag == "select":
            self._in_select = False
        elif tag == "option":
            self._value = None

    def handle_data(self, data):
        if self._in_select and self._value is not None and data.strip():
            self.names.append(data.strip())
            self._value = None


def listed_names(response) -> list[str]:
    assert response.status_code == 200, f"名單頁應回 200，實際 {response.status_code}：{response.text[:200]}"
    parser = _Options()
    parser.feed(response.text)
    return parser.names


@when(parsers.parse('a visitor chooses group "{group}"'))
def _choose_group(recorder, client, group):
    recorder.perform(lambda: client.get("/sign-in", params={"group": group}))


@then(parsers.parse('the name list is exactly "{names}"'))
def _names_exactly(recorder, names):
    expected = [n.strip() for n in names.split(",")]
    assert listed_names(recorder.response) == expected


@then(parsers.parse('the name list includes "{name}"'))
def _names_include(recorder, name):
    assert name in listed_names(recorder.response)


@when(parsers.parse('a visitor signs in as "{name}" with "{password}"'))
def _sign_in_as(recorder, client, db, name, password):
    # R03 要測「密碼對、但帳戶已封存」：所以先替存在的帳戶設好正確密碼（"correct"），
    # 再用規格給的密碼登入；"wrong" 就是密碼錯，"Nobody" 沒有帳戶。
    set_password(db, name)
    recorder.perform(lambda: post_sign_in(client, name, password))


@then(parsers.parse('the landing page is "{page}"'))
def _landing(recorder, page):
    assert page in LANDING_PATHS, f"規格的頁名 {page!r} 沒有對應的路徑"
    r = recorder.response
    assert r.status_code == 303, f"應轉址（303），實際 {r.status_code}"
    assert r.headers["location"] == LANDING_PATHS[page]


@then("nobody is signed in")
def _nobody(recorder, client, db):
    # 登入被拒絕：沒有 cookie、沒有 session 列，而且資料庫在動作前後完全一致（三斷言的第三項）
    assert SESSION_COOKIE not in client.cookies, "被拒絕的登入不應發出 session cookie"
    assert "set-cookie" not in recorder.response.headers, "被拒絕的登入不應設定任何 cookie"
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.sessions")
        assert cur.fetchone()[0] == 0, "被拒絕的登入不應建立 session"
    db.rollback()
    # 第三項斷言：資料沒有變動。D-069：只有 migration 0004 新增的兩張表可以有變動（IAM-R05 的失敗次數、IAM-R07 的嘗試次數），
    # 它們的寫入由 IAM-F02 明確斷言；其他所有表（accounts、sessions、audit_log…）仍須完全不變。
    changed = {t: c for t, c in recorder.changes().items() if t not in LOCKOUT_TABLES}
    assert not changed, f"資料庫在動作前後不一致（失敗次數與嘗試次數兩張表除外）：{changed}"
