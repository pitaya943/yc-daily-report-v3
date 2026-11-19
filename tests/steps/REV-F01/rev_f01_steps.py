"""REV-F01 確認或駁回回報的步驟（REV-R01、R02、R03；D-118 的路徑）。

設計：
- 動作一律走 `recorder.perform`，請求走真的 HTTP（TestClient），帶 session cookie 與 `X-CSRF-Token`（D-080）。
  路徑：`GET /review/queue/ordinary`、`POST /review/reports/confirm`、`POST /review/reports/reject`（表單帶一或多個 `id`）、
  `POST /review/reports/{id}/unconfirm`。
- Given 直接寫資料庫（CONFIRMED 的回報連份額一起寫入：份額是確認時存下來的，這裡模擬「已經確認過」）。
- 共用步驟（outcome、拒絕、稽核、登入）來自 tests/steps/common/，不重新定義（pitfall #26）。
  `the report state is …` 是 RPT-F02 定義的全域步驟，靠它的 `lifecycle` fixture 知道「那張回報」，所以這裡的 Given 也寫入 `lifecycle`。
- 本檔的輔助函式（insert_report、post…）也給同一個 feature 的 REV-F02 步驟使用（REV-F02 的 conftest 把本目錄加進 sys.path）。
- 本檔定義的步驟文字（全域註冊，新增前已 grep 過）：
  `exactly N audit row "X" is written` — 這個動作新增了恰 N 列該類型的稽核（REV-R02 兩個 scenario 共用）。
"""
from __future__ import annotations

import threading
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import given, parsers, then, when

from app.core import session as session_core
from app.core.clock import clock
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import session_rows, sign_in_with_correct_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)
from tests.steps.common.steps import claim_audit_row, new_audit_rows

CSRF_HEADER = "X-CSRF-Token"
SESSION_COOKIE = session_core.SESSION_COOKIE
TODAY = "2026-11-15"  # background 的「今天」
ITEM = "direct_13"  # WEST、SOUTH、BIG_METER 都有的工項


# ───────────────────────── 輔助（REV-F02 也用） ─────────────────────────


def account_row(db, name: str) -> tuple[int, str, bool]:
    with db.cursor() as cur:
        cur.execute("select id, zone, big_meter from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"背景資料裡沒有帳戶 {name}"
    return row


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
    """scenario 沒有寫 `"<name>" is signed in` 時，動作「之前」先登入；登入寫的 session 不算動作造成的變動。"""
    if not session_rows(db, name):
        response = sign_in_with_correct_password(client, db, name)
        assert response.status_code == 303, f"登入應成功（303），實際 {response.status_code}"


def form_request(fields: list[tuple[str, str]], token: str) -> dict:
    return {
        "content": urlencode(fields),
        "headers": {"Content-Type": "application/x-www-form-urlencoded", CSRF_HEADER: token},
        "follow_redirects": False,
    }


def post(client, db, name: str, path: str, fields: list[tuple[str, str]]):
    return client.post(path, **form_request(fields, csrf_token(db, name)))


def insert_report(
    db,
    submitter: str,
    date: str,
    status: str,
    *,
    items: dict[str, int] | None = None,
    crew: tuple[str, ...] = (),
    custom: tuple[str, int, int] | None = None,
    reviewer: str | None = None,
) -> int:
    """直接寫一張回報（含工項、共同作業者（不含提交者）、自訂工項 (名稱, tenths, 單價)）。reviewer 給了就同時記下審核者。"""
    now = clock.now()
    submitter_id, zone, big = account_row(db, submitter)  # 先查：account_row 會 rollback，不能夾在待提交的寫入中間
    crew_ids = [account_row(db, who)[0] for who in crew]
    reviewer_id = account_row(db, reviewer)[0] if reviewer else None
    catalogue = "BIG_METER" if big else zone
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at, "
            "custom_name, custom_tenths, custom_price, reviewer_id, reviewed_at) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (submitter_id, date, catalogue, status, now, now, *(custom or (None, None, None)), reviewer_id, now if reviewer_id else None),
        )
        rid = cur.fetchone()[0]
        for code, tenths in (items or {}).items():
            cur.execute("insert into yc_v3.report_items(report_id, item_code, tenths) values (%s, %s, %s)", (rid, code, tenths))
        for position, member_id in enumerate(crew_ids, start=1):
            cur.execute("insert into yc_v3.report_crew(report_id, position, account_id) values (%s, %s, %s)", (rid, position, member_id))
    db.commit()
    return rid


def insert_shares(db, report_id: int, item: str, shares: list[tuple[str, int]]) -> None:
    """模擬「已經確認過」：依 crew 順序（提交者第一）寫入 (人名, tenths)。"""
    ids = [account_row(db, who)[0] for who, _ in shares]
    with db.cursor() as cur:
        for position, ((_, tenths), account_id) in enumerate(zip(shares, ids)):
            cur.execute(
                "insert into yc_v3.report_shares(report_id, item_code, account_id, position, tenths) values (%s, %s, %s, %s, %s)",
                (report_id, item, account_id, position, tenths),
            )
    db.commit()


def report_row(db, report_id: int) -> tuple | None:
    """(status, reviewer 名稱, reviewed_at)；不存在回傳 None。"""
    with db.cursor() as cur:
        cur.execute(
            "select r.status, a.name, r.reviewed_at from yc_v3.reports r left join yc_v3.accounts a on a.id = r.reviewer_id where r.id = %s",
            (report_id,),
        )
        row = cur.fetchone()
    db.rollback()
    return row


def stored_shares(db, report_id: int, item: str) -> list[tuple[str, int]]:
    """這張回報某工項已存的份額：[(人名, tenths)]，依 position（提交者第一）。"""
    with db.cursor() as cur:
        cur.execute(
            "select a.name, s.tenths from yc_v3.report_shares s join yc_v3.accounts a on a.id = s.account_id "
            "where s.report_id = %s and s.item_code = %s order by s.position",
            (report_id, item),
        )
        rows = cur.fetchall()
    db.rollback()
    return rows


def tenths_text(value: int) -> str:
    return f"{value // 10}.{value % 10}"


def parse_tenths(text: str) -> int:
    whole, _, frac = text.strip().partition(".")
    return int(whole) * 10 + int(frac or "0")


@pytest.fixture
def rev() -> dict:
    """scenario 內的回報：{"R1": id, ...}，`current` 是「那張回報」。"""
    return {}


def _remember(rev: dict, lifecycle: dict, label: str, report_id: int, state: str, date: str = TODAY) -> int:
    rev[label] = report_id
    rev["current"] = report_id
    lifecycle.update(report_id=report_id, date=date, state=state)  # 給 RPT-F02 的 `the report state is …`
    return report_id


# ───────────────────────── Given ─────────────────────────


@given(parsers.re(r'PENDING reports by "(?P<a>[^"]+)", "(?P<b>[^"]+)", and "(?P<c>[^"]+)" dated within 30 days$'))
def _pending_reports_by_three(db, rev, a, b, c):
    for name in (a, b, c):
        rev[name] = insert_report(db, name, "2026-11-14", "PENDING", items={ITEM: 20})


@given(parsers.re(r"reports R1 PENDING, R2 CONFIRMED, R3 REJECTED$"))
def _reports_in_three_states(db, rev, lifecycle):
    _remember(rev, lifecycle, "R1", insert_report(db, "Wen", TODAY, "PENDING", items={ITEM: 20}, crew=("Wei",)), "PENDING")
    r2 = insert_report(db, "Wen", TODAY, "CONFIRMED", items={ITEM: 20}, crew=("Wei",), reviewer="Admin2")
    insert_shares(db, r2, ITEM, [("Wen", 10), ("Wei", 10)])
    rev["R2"] = r2
    rev["R3"] = insert_report(db, "Wen", TODAY, "REJECTED", items={ITEM: 20}, crew=("Wei",), reviewer="Admin2")


@given(parsers.re(r'a PENDING report by "(?P<name>[^"]+)" with "(?P<item>[^"]+)" = (?P<qty>[0-9.]+) dated "(?P<date>[^"]+)"$'))
def _pending_report_with_item(db, rev, lifecycle, name, item, qty, date):
    _remember(rev, lifecycle, "R1", insert_report(db, name, date, "PENDING", items={item: parse_tenths(qty)}), "PENDING", date)


@given(parsers.re(r"a (?P<state>PENDING|CONFIRMED) report R1$"))
def _a_report_r1(db, rev, lifecycle, state):
    """Wen 與 Wei、Wan 共同作業，direct_13 = 7.0。CONFIRMED 的連份額一起寫入（2.4、2.3、2.3）。"""
    rid = insert_report(
        db, "Wen", TODAY, state, items={ITEM: 70}, crew=("Wei", "Wan"), reviewer="Admin2" if state == "CONFIRMED" else None
    )
    if state == "CONFIRMED":
        insert_shares(db, rid, ITEM, [("Wen", 24), ("Wei", 23), ("Wan", 23)])
    _remember(rev, lifecycle, "R1", rid, state)


# ───────────────────────── When ─────────────────────────


def _ids(rev: dict, labels: list[str]) -> list[tuple[str, str]]:
    return [("id", str(rev[label])) for label in labels]


@when(parsers.re(r'"(?P<name>[^"]+)" opens the ordinary confirmation queue$'))
def _opens_ordinary_queue(recorder, client, db, name):
    ensure_signed_in(client, db, name)
    recorder.perform(lambda: client.get("/review/queue/ordinary"))


@when(parsers.re(r'"(?P<name>[^"]+)" batch-confirms R1, R2, R3$'))
def _batch_confirms(recorder, client, db, rev, name):
    ensure_signed_in(client, db, name)
    fields = _ids(rev, ["R1", "R2", "R3"])
    recorder.perform(lambda: post(client, db, name, "/review/reports/confirm", fields))


@when(parsers.re(r'"(?P<name>[^"]+)" rejects it$'))
def _rejects_it(recorder, client, db, rev, name):
    ensure_signed_in(client, db, name)
    recorder.perform(lambda: post(client, db, name, "/review/reports/reject", [("id", str(rev["current"]))]))


@when(parsers.re(r'"(?P<a>[^"]+)" and "(?P<b>[^"]+)" confirm R1 at the same instant$'))
def _confirm_concurrently(recorder, client, db, rev, a, b):
    """兩位管理員各用自己的 session，同時送出同一張回報的確認（threading.Barrier 讓兩邊都就緒後才送）。"""
    clients, tokens = {}, {}
    for who in (a, b):
        c = TestClient(client.app, raise_server_exceptions=False)
        response = sign_in_with_correct_password(c, db, who)
        assert response.status_code == 303
        clients[who], tokens[who] = c, csrf_token(db, who)  # token 在動作之前讀好：連線不跨執行緒共用
    barrier = threading.Barrier(2)
    responses: dict[str, object] = {}
    errors: list = []

    def worker(who: str) -> None:
        try:
            barrier.wait(timeout=30)
            responses[who] = clients[who].post("/review/reports/confirm", **form_request([("id", str(rev["R1"]))], tokens[who]))
        except Exception as e:  # noqa: BLE001  執行緒裡的例外要帶回測試
            errors.append(e)

    def run():
        threads = [threading.Thread(target=worker, args=(who,)) for who in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        assert not errors, f"平行請求失敗：{errors}"
        rev["responses"] = responses
        return responses[a]

    recorder.perform(run)


@when(parsers.re(r'"(?P<name>[^"]+)" tries to unconfirm R1 from the confirmation queue$'))
def _tries_to_unconfirm(recorder, client, db, rev, name):
    ensure_signed_in(client, db, name)
    recorder.perform(lambda: post(client, db, name, f"/review/reports/{rev['R1']}/unconfirm", []))


# ───────────────────────── Then ─────────────────────────


class _QueueParser(HTMLParser):
    """佇列頁的結構：`<section data-zone="WEST">` 底下的 `<tr data-report-id="…">`，帳戶在 `td.account`。"""

    def __init__(self) -> None:
        super().__init__()
        self.zone: str | None = None
        self.rows: list[tuple[str | None, int, str]] = []  # (zone, report id, account)
        self._row: list | None = None
        self._cell: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and "data-zone" in a:
            self.zone = a["data-zone"]
        elif tag == "tr" and "data-report-id" in a:
            self._row = [self.zone, int(a["data-report-id"]), ""]
        elif tag == "td" and self._row is not None:
            self._cell = a.get("class", "")

    def handle_endtag(self, tag):
        if tag == "section":
            self.zone = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(tuple(self._row))
            self._row = None
        elif tag == "td":
            self._cell = None

    def handle_data(self, data):
        if self._row is not None and self._cell == "account":
            self._row[2] += data.strip()


def queue_rows(recorder) -> list[tuple[str | None, int, str]]:
    r = recorder.response
    assert r.status_code == 200, f"佇列應為 200，實際 {r.status_code}：{r.text[:200]}"
    parser = _QueueParser()
    parser.feed(r.text)
    return parser.rows


@then(parsers.re(r'the queue lists the reports of "(?P<a>[^"]+)" and "(?P<b>[^"]+)" grouped by zone$'))
def _queue_lists(recorder, db, rev, a, b):
    rows = queue_rows(recorder)
    expected = {(account_row(db, who)[1], rev[who], who) for who in (a, b)}  # 區域 = 他們各自的 zone（WEST、SOUTH）
    listed = {r for r in rows if r[2] in (a, b)}
    assert listed == expected, f"佇列應依區域列出 {sorted(expected)}，實際 {rows}"
    assert len(rows) == len([r for r in rows if r[1] in {rev[a], rev[b]}]) + len([r for r in rows if r[2] == "Big"]), "佇列有多餘的列"


@then(parsers.re(r'the queue does not list the report of "(?P<name>[^"]+)"$'))
def _queue_not_list(recorder, rev, name):
    rows = queue_rows(recorder)
    assert all(r[1] != rev[name] and r[2] != name for r in rows), f"佇列不該列出 {name} 的回報：{rows}"


@then(parsers.re(r'(?P<label>R[0-9]) is CONFIRMED with reviewer "(?P<name>[^"]+)"$'))
def _confirmed_with_reviewer(db, rev, label, name):
    status, reviewer, reviewed_at = report_row(db, rev[label])
    assert (status, reviewer) == ("CONFIRMED", name), f"{label} 應為 CONFIRMED、審核者 {name}，實際 {(status, reviewer)}"
    assert reviewed_at == clock.now(), "審核時間應是現在（app/core/clock.py）"


@then(parsers.re(r"R1 is CONFIRMED with exactly one reviewer$"))
def _confirmed_one_reviewer(recorder, db, rev):
    status, reviewer, _ = report_row(db, rev["R1"])
    assert status == "CONFIRMED" and reviewer in {"Admin1", "Admin2"}, f"R1 應被其中一位管理員確認，實際 {(status, reviewer)}"
    assert all(r.status_code == 200 for r in rev["responses"].values()), "兩個請求都應被接受（後到的略過，不是錯誤）"
    # 稽核的行為者就是那位審核者：只有一個人真的確認了
    rows = [r for r in new_audit_rows(recorder)]
    with db.cursor() as cur:
        cur.execute("select x::text, actor_name from yc_v3.audit_log x where type = 'REPORT_CONFIRM'")
        actors = [r[1] for r in cur.fetchall() if r[0] in rows]
    db.rollback()
    assert actors == [reviewer], f"REPORT_CONFIRM 的行為者應是審核者 {reviewer}，實際 {actors}"


@then(parsers.re(r"(?P<a>R[0-9]) and (?P<b>R[0-9]) are unchanged$"))
def _unchanged(recorder, rev, a, b):
    """這兩張回報（reports、report_items、report_crew、report_shares…每個以 report_id 開頭的列）在動作前後完全相同。"""
    ids = {rev[a], rev[b]}
    for table, change in recorder.changes().items():
        for row in change["added"] + change["removed"]:
            head = row.lstrip("(").split(",", 1)[0]
            assert not (table != "audit_log" and head.isdigit() and int(head) in ids), f"{a}、{b} 應不變，但 {table} 有變動：{row}"


@then(parsers.re(r'exactly (?P<n>[0-9]+) audit rows? "(?P<type_>[A-Z_]+)" is written$'))
def _exactly_n_audit_rows(recorder, db, n, type_):
    added = set(new_audit_rows(recorder))
    with db.cursor() as cur:
        cur.execute("select x::text, actor_name from yc_v3.audit_log x where type = %s", (type_,))
        rows = [r for r in cur.fetchall() if r[0] in added]
    db.rollback()
    assert len(rows) == int(n), f'應恰新增 {n} 列 "{type_}"，實際 {len(rows)} 列'
    for _, actor in rows:
        claim_audit_row(recorder, db, type_, actor)  # 記為已斷言，之後的 `nothing else is written` 可以扣掉


@then(parsers.re(r"shares for R1 are stored exactly once$"))
def _shares_once(db, rev):
    with db.cursor() as cur:
        cur.execute("select count(*), count(distinct (item_code, account_id)), coalesce(sum(tenths), 0) from yc_v3.report_shares where report_id = %s", (rev["R1"],))
        total, distinct, tenths = cur.fetchone()
    db.rollback()
    assert (total, distinct) == (3, 3), f"1 個工項 × 3 人 = 3 列，每人一列；實際 {total} 列、{distinct} 個不同的 (工項, 人)"
    assert tenths == 70, f"份額加總應等於 7.0（70 tenths），實際 {tenths}"


@then(parsers.re(r"(?P<label>R[0-9]) is CONFIRMED$"))
def _is_confirmed(db, rev, label):
    assert report_row(db, rev[label])[0] == "CONFIRMED", f"{label} 應仍為 CONFIRMED"


@then(parsers.re(r'payroll for "(?P<date_from>[^"]+)" to "(?P<date_to>[^"]+)" has no gross for "(?P<name>[^"]+)"$'))
def _payroll_has_no_gross(db, date_from, date_to, name):
    from datetime import date

    from app.modules.review.crew_split_and_stored_shares import service as shares

    account_id = account_row(db, name)[0]
    quantities = shares.confirmed_quantities(db, date.fromisoformat(date_from), date.fromisoformat(date_to))
    db.rollback()
    assert account_id not in quantities, f"{name} 在 {date_from} 到 {date_to} 不該有任何已確認的數量，實際 {quantities.get(account_id)}"
