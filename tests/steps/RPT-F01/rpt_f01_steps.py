"""RPT-F01 送出日報的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

設計：
- 動作一律走 `recorder.perform`，所以「nothing is written」比對的是動作前後整個資料庫。
- 請求走真的 HTTP（TestClient）：`GET /reports` 取表單、`POST /reports` 送出，帶 session cookie 與 `X-CSRF-Token`
  （D-080：anti-forgery token 放標頭，不放表單欄位）。表單的欄位名稱是工項代碼（附錄 A）、`report_date`、`collaborator`（可重複，順序就是提交者選的順序）。
- 共用步驟 `the outcome is <OUTCOME>`、`"<name>" is signed in`、拒絕與稽核的步驟都在 tests/steps/common/，這裡不重新定義（pitfall #26）。
- 產品程式的 import 放在函式內：功能還不存在時只有 RPT 的 scenario 失敗，不會讓整個測試收集失敗。
- Given 步驟直接寫資料庫（任務 8）：T-202 的刪除端點與 CONFIRMED／REJECTED 的轉移還不存在。
- 「工項組的 32／37／25 項」從 spec/appendix-a-catalogues.md 解析後逐項（代碼、顯示名稱、預設單價、保留金）比對，不另抄一份清單。
"""
from __future__ import annotations

import re
import threading
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core.clock import clock
from tests.steps.common.audit_description import *  # noqa: F401,F403  (the audit description contains ... ，D-094)
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import SESSION_COOKIE, session_rows, sign_in_with_correct_password
from tests.steps.common.spec_tables import SPEC
from tests.steps.common.steps import audit_rows_matching
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)

CSRF_HEADER = "X-CSRF-Token"
REPORTS = "/reports"


# ───────────────────────── 輔助 ─────────────────────────


def today() -> str:
    return clock.now().date().isoformat()


def account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"背景資料裡沒有帳戶 {name}"
    return row[0]


def expected_catalogue(db, name: str) -> str:
    """AD-4：大表旗標開 → BIG_METER；否則依區域。獨立於產品程式再推導一次。"""
    with db.cursor() as cur:
        cur.execute("select zone, big_meter from yc_v3.accounts where name = %s", (name,))
        zone, big = cur.fetchone()
    db.rollback()
    return "BIG_METER" if big else zone


def csrf_token(db, name: str) -> str:
    with db.cursor() as cur:
        cur.execute(
            "select s.anti_forgery_token from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
            "where a.name = %s order by s.id desc limit 1",
            (name,),
        )
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"{name} 沒有 session，請先 `\"{name}\" is signed in`"
    return row[0]


def strip_quotes(raw: str) -> str:
    raw = raw.strip()
    return raw[1:-1] if len(raw) >= 2 and raw[0] == raw[-1] == '"' else raw


def ensure_signed_in(client, db, name: str) -> None:
    """RPT-R04 的 scenario 沒有 `"<name>" is signed in`：送出之前，這個人必須已登入（只有登入的人能送出）。
    在動作「之前」登入，所以登入寫的 session 不算動作造成的資料變動。"""
    if not session_rows(db, name):
        response = sign_in_with_correct_password(client, db, name)
        assert response.status_code == 303, f"登入應成功（303），實際 {response.status_code}"


def form_request(fields: list[tuple[str, str]], token: str) -> dict:
    """urlencoded 主體，欄位順序原樣保留（共同作業者的順序就是欄位出現的順序，RPT-R05）。
    不用 `data=`：httpx 的 `data` 是 dict，同名欄位的順序不由我們控制。"""
    return {
        "content": urlencode(fields),
        "headers": {"Content-Type": "application/x-www-form-urlencoded", CSRF_HEADER: token},
        "follow_redirects": False,
    }


def post_report(client, db, name: str, fields: list[tuple[str, str]]):
    return client.post(REPORTS, **form_request(fields, csrf_token(db, name)))


def report_rows(db) -> list[tuple]:
    with db.cursor() as cur:
        cur.execute(
            "select r.id, a.name, r.report_date::text, r.catalogue, r.status from yc_v3.reports r "
            "join yc_v3.accounts a on a.id = r.submitter_id order by r.id"
        )
        rows = cur.fetchall()
    db.rollback()
    return rows


def newest_report(db) -> tuple:
    rows = report_rows(db)
    assert rows, "資料庫裡沒有任何回報"
    return rows[-1]


def insert_report(db, submitter: str, date: str, status: str, crew: tuple[str, ...] = ()) -> int:
    """Given 步驟用：直接寫一張回報（含共同作業者），不經過產品的送出端點。"""
    now = clock.now()
    # 先查好 id：account_id／expected_catalogue 會 rollback，不能夾在待提交的寫入中間
    submitter_id, catalogue = account_id(db, submitter), expected_catalogue(db, submitter)
    crew_ids = [account_id(db, who) for who in crew]
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (submitter_id, date, catalogue, status, now, now),
        )
        rid = cur.fetchone()[0]
        for position, member_id in enumerate(crew_ids, start=1):
            cur.execute("insert into yc_v3.report_crew(report_id, position, account_id) values (%s, %s, %s)", (rid, position, member_id))
    db.commit()
    return rid


@pytest.fixture
def last() -> dict:
    """scenario 內最近一次送出的資訊（誰、哪個工項、哪一天）。"""
    return {}


@pytest.fixture
def concurrent() -> dict:
    return {}


# ───────────────────────── 附錄 A 與表單的解析 ─────────────────────────

_SECTIONS = {"A.1": "WEST", "A.2": "SOUTH", "A.3": "BIG_METER"}


def spec_catalogue(name: str) -> list[tuple[str, str, int, bool]]:
    """spec/appendix-a-catalogues.md 的 A.1～A.3：[(代碼, 顯示名稱, 預設單價, 有保留金)]，依表中順序。"""
    rows: list[tuple[str, str, int, bool]] = []
    current = None
    for line in (SPEC / "appendix-a-catalogues.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (A\.\d)\b", line)
        if m:
            current = _SECTIONS.get(m.group(1))
            continue
        row = re.match(r"^\| `([a-z0-9_]+)` \| (.+?) \| (\d+) \| (是|—) \|$", line)
        if row and current == name:
            rows.append((row.group(1), row.group(2), int(row.group(3)), row.group(4) == "是"))
    return rows


class _FormParser(HTMLParser):
    """取出表單上的工項輸入（data-item-code／data-item-name）與回報日期的預設值。"""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str, str]] = []  # (輸入名稱, 代碼, 顯示名稱)
        self.report_date: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag != "input":
            return
        if "data-item-code" in a:
            self.items.append((a.get("name") or "", a["data-item-code"], a.get("data-item-name") or ""))
        if a.get("name") == "report_date":
            self.report_date = a.get("value")


def parse_form(html: str) -> _FormParser:
    parser = _FormParser()
    parser.feed(html)
    return parser


# ───────────────────────── Given ─────────────────────────

_CYCLE = ("PENDING", "CONFIRMED", "REJECTED")


@given(parsers.parse('"{name}" has {n:d} own reports dated "{date}"'))
def _has_own_reports(db, name, n, date):
    # 狀態輪流用 PENDING、CONFIRMED、REJECTED：每日上限不分狀態，只要「仍存在」就算（RPT-R04）
    for i in range(n):
        insert_report(db, name, date, _CYCLE[i % len(_CYCLE)])


@given(parsers.parse('"{name}" has {n:d} own reports dated "{date}", one of them PENDING'))
def _has_own_reports_one_pending(db, name, n, date):
    statuses = ["PENDING"] + [_CYCLE[1 + i % 2] for i in range(n - 1)]
    for status in statuses:
        insert_report(db, name, date, status)


@given(parsers.parse('"{name}" is a collaborator on {n:d} reports dated "{date}" submitted by "{submitter}"'))
def _is_collaborator(db, name, n, date, submitter):
    for _ in range(n):
        insert_report(db, submitter, date, "PENDING", crew=(name,))


@given(parsers.parse('"{name}" deleted that PENDING report'))
def _deleted_pending(db, name):
    # 任務 8：直接在資料庫刪除，不呼叫 T-202 的刪除端點（它還不存在）
    with db.cursor() as cur:
        cur.execute(
            "delete from yc_v3.reports where status = 'PENDING' and submitter_id = %s returning id",
            (account_id(db, name),),
        )
        deleted = cur.fetchall()
    db.commit()
    assert len(deleted) == 1, f"應該恰有 1 張 PENDING 回報被刪除，實際 {len(deleted)} 張"


# ───────────────────────── When ─────────────────────────


@when(parsers.parse('"{name}" opens the daily report form'))
def _opens_form(recorder, client, last, name):
    last["name"] = name
    recorder.perform(lambda: client.get(REPORTS))


def _submit(recorder, client, db, last, name, fields):
    last.update(name=name, fields=fields)
    ensure_signed_in(client, db, name)
    recorder.perform(lambda: post_report(client, db, name, fields))


@when(parsers.re(r'"(?P<name>[^"]+)" submits a report with "(?P<item>[^"]+)" = (?P<qty>.*?)(?: and "(?P<item2>[^"]+)" = (?P<qty2>.*))?$'))
def _submits_with_item(recorder, client, db, last, name, item, qty, item2, qty2):
    """RPT-R03：`… with "direct_13" = "<qty>" and "indirect_13" = 1.0`（D-096）：第二個工項讓這張回報至少有一個數量，
    表格只檢查第一個工項的邊界。`last["item"]` 仍是第一個工項（`the stored quantity of …` 看的是它）。"""
    last["item"] = item
    fields = [("report_date", today()), (item, strip_quotes(qty))]
    if item2 is not None:
        fields.append((item2, strip_quotes(qty2)))
    _submit(recorder, client, db, last, name, fields)


@when(parsers.re(r'"(?P<name>[^"]+)" submits a report with every quantity blank$'))
def _submits_all_blank(recorder, client, db, last, name):
    """RPT-R08：表單上這個人的每一個工項都送出空白（不是什麼都不送）。"""
    from app.modules.reports.submit_a_daily_report import catalogue as product

    catalogue_name = expected_catalogue(db, name)
    fields = [("report_date", today())] + [(code, "") for code in product.item_codes(catalogue_name)]
    _submit(recorder, client, db, last, name, fields)


@when(parsers.re(r'"(?P<name>[^"]+)" submits a report dated "(?P<date>[^"]*)" with "(?P<item>[^"]+)" = (?P<qty>.*)$'))
def _submits_dated(recorder, client, db, last, name, date, item, qty):
    last["item"] = item
    _submit(recorder, client, db, last, name, [("report_date", date), (item, strip_quotes(qty))])


# 沒有指定數量的情況（共同作業者、管理員）：送出一個普通的數量，讓「這張回報本身合法」不成為變因
_BASELINE = ("direct_13", "1.0")


@when(parsers.re(r'"(?P<name>[^"]+)" submits a report naming collaborator "(?P<who>[^"]+)"$'))
def _names_one(recorder, client, db, last, name, who):
    _submit(recorder, client, db, last, name, [("report_date", today()), _BASELINE, ("collaborator", str(account_id(db, who)))])


@when(parsers.re(r'"(?P<name>[^"]+)" submits a report naming collaborators "(?P<first>[^"]+)" then "(?P<second>[^"]+)"$'))
def _names_two(recorder, client, db, last, name, first, second):
    fields = [("report_date", today()), _BASELINE, ("collaborator", str(account_id(db, first))), ("collaborator", str(account_id(db, second)))]
    _submit(recorder, client, db, last, name, fields)


@when(parsers.re(r'"(?P<name>[^"]+)" submits a daily report$'))
def _submits_daily_report(recorder, client, db, last, name):
    _submit(recorder, client, db, last, name, [("report_date", today()), _BASELINE])


@when(parsers.parse('"{name}" submits {n:d} reports dated "{date}" at the same instant'))
def _submits_concurrently(recorder, client, db, last, concurrent, name, n, date):
    ensure_signed_in(client, db, name)
    token = csrf_token(db, name)
    session_cookie = client.cookies.get(SESSION_COOKIE)
    fields = [("report_date", date), _BASELINE]
    barrier = threading.Barrier(n)
    responses: list = [None] * n
    errors: list = []

    def worker(i: int) -> None:
        try:
            c = TestClient(client.app, raise_server_exceptions=False, cookies={SESSION_COOKIE: session_cookie})
            barrier.wait(timeout=30)  # 全部就緒後同時送出
            responses[i] = c.post(REPORTS, **form_request(fields, token))
        except Exception as e:  # noqa: BLE001  執行緒裡的例外要帶回測試，不能默默消失
            errors.append(e)

    def run():
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, f"平行請求失敗：{errors}"
        concurrent["responses"] = responses
        return responses[0]

    last.update(name=name, fields=fields)
    recorder.perform(run)


# ───────────────────────── Then ─────────────────────────


@then(parsers.parse('the form offers the {count:d} items of catalogue "{catalogue}"'))
def _form_offers(recorder, count, catalogue):
    from app.modules.reports.submit_a_daily_report import catalogue as product

    r = recorder.response
    assert r.status_code == 200, f"表單應為 200，實際 {r.status_code}：{r.text[:200]}"
    form = parse_form(r.text)
    spec = spec_catalogue(catalogue)
    assert len(spec) == count, f"spec 附錄 A 的 {catalogue} 有 {len(spec)} 項，scenario 寫 {count}"
    shown = [(code, display) for _, code, display in form.items]
    assert shown == [(code, display) for code, display, _, _ in spec], "表單提供的工項（代碼與顯示名稱，含順序）與附錄 A 不一致"
    assert all(input_name == code for input_name, code, _ in form.items), "輸入欄位的 name 必須就是工項代碼"
    # 產品的目錄資料（之後的 ticket 會 import）也要與附錄 A 完全一致：代碼、名稱、預設單價、保留金
    assert [(i.code, i.display_name, i.default_price, i.retention) for i in product.catalogue(catalogue)] == spec


@then(parsers.parse('the report date defaults to "{date}"'))
def _date_default(recorder, date):
    assert parse_form(recorder.response.text).report_date == date


@then(parsers.parse('the stored quantity of "{item}" is {tenths} tenths'))
def _stored_quantity(db, last, item, tenths):
    """D-096 之後規格的步驟文字寫明工項（表格只檢查 direct_13；另一個工項只是讓回報成立）。"""
    assert item == last["item"], f"步驟檢查的工項 {item} 應是送出時被檢查的工項 {last['item']}"
    with db.cursor() as cur:
        cur.execute("select tenths from yc_v3.report_items where item_code = %s order by report_id", (item,))
        rows = [r[0] for r in cur.fetchall()]
    db.rollback()
    if tenths.strip() == "-":
        assert rows == [], f"被拒絕的送出不該留下數量，實際 {rows}"  # 資料沒有變動由 `the outcome is INVALID` 斷言
    else:
        assert rows == [int(tenths)], f"{item} 存下的數量應為 [{tenths}]（0.1 只），實際 {rows}"


@then("the report is saved as PENDING")
def _saved_pending(recorder, db, last):
    r = recorder.response
    assert r.status_code == 200, f"應被接受（200），實際 {r.status_code}：{r.text[:200]}"
    added = recorder.changes().get("reports", {}).get("added", [])
    assert len(added) == 1, f"應該恰新增 1 張回報，實際 {len(added)} 張：{added}"
    rid, submitter, report_date, catalogue, status = newest_report(db)
    assert status == "PENDING", f"新回報的狀態應為 PENDING，實際 {status}"
    assert submitter == last["name"], f"提交者應為 {last['name']}，實際 {submitter}"
    assert catalogue == expected_catalogue(db, submitter), f"回報要記下送出當時的工項組（AD-4）：{catalogue}"
    submitted_date = dict(last["fields"])["report_date"]
    assert report_date == submitted_date, f"回報日期應為 {submitted_date}，實際 {report_date}"


@then(parsers.re(r'the saved crew is "(?P<crew>[^"]+)"(?P<ordered> in that order)?$'))
def _saved_crew(recorder, db, crew, ordered):
    r = recorder.response
    assert r.status_code == 200, f"應被接受（200），實際 {r.status_code}：{r.text[:200]}"
    rid, submitter, *_ = newest_report(db)
    with db.cursor() as cur:
        cur.execute(
            "select a.name from yc_v3.report_crew c join yc_v3.accounts a on a.id = c.account_id where c.report_id = %s order by c.position",
            (rid,),
        )
        collaborators = [x[0] for x in cur.fetchall()]
    db.rollback()
    actual = [submitter, *collaborators]
    assert actual == crew.split(", "), f"存下的作業小組（提交者在前，其後依提交者選的順序）應為 {crew.split(', ')}，實際 {actual}"


@then(parsers.re(r'nothing is written except an audit row "(?P<type_>[A-Z_]+)"$'))
def _nothing_except_audit_row(recorder, db, last, type_):
    """R06 的拒絕：只多一列稽核。規格沒寫 actor，這裡斷言它是被拒絕的那個人（比規格嚴：見 PR 說明）。"""
    changes = recorder.changes()
    others = {t: c for t, c in changes.items() if t != "audit_log"}
    assert not others, f"稽核以外的資料表有變動：{others}"
    audit = changes.get("audit_log", {"added": [], "removed": []})
    assert audit["removed"] == [], "稽核紀錄不可被刪除或修改"
    assert len(audit["added"]) == 1, f"應該只新增 1 列稽核，實際 {len(audit['added'])} 列：{audit['added']}"
    assert audit_rows_matching(recorder, db, type_, last["name"]), f'新增的稽核列不是 "{type_}" / "{last["name"]}"：{audit["added"]}'


@then(parsers.parse("exactly {n:d} is saved"))
def _exactly_saved(recorder, db, last, concurrent, n):
    responses = concurrent["responses"]
    ok = [r for r in responses if r.status_code == 200]
    assert len(ok) == n, f"應恰有 {n} 個請求成功，實際 {[r.status_code for r in responses]}"
    added = recorder.changes().get("reports", {}).get("added", [])
    assert len(added) == n, f"應該恰新增 {n} 張回報，實際 {len(added)} 張"
    date = dict(last["fields"])["report_date"]
    own = [r for r in report_rows(db) if r[1] == last["name"] and r[2] == date]
    assert len(own) == 3, f"當日自己的回報不得超過 3 張，實際 {len(own)} 張"


@then(parsers.parse('the other is rejected as CONFLICT with message "{message}"'))
def _other_rejected(concurrent, message):
    others = [r for r in concurrent["responses"] if r.status_code != 200]
    assert len(others) == 1, f"應該恰有 1 個請求被拒絕，實際 {[r.status_code for r in concurrent['responses']]}"
    assert others[0].status_code == 409, f"CONFLICT 應為 409，實際 {others[0].status_code}"
    assert others[0].json() == {"outcome": "CONFLICT", "message": message}
