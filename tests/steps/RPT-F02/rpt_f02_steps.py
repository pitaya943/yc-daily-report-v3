"""RPT-F02 回報生命週期的步驟（RPT-R10、R11、R13；RPT-R12 由 T-301 補，D-085）。

設計：
- 動作一律走 `recorder.perform`，所以「nothing is written」比對的是動作前後整個資料庫。
- 請求走真的 HTTP（TestClient），路徑依 D-090：`POST /reports/{id}`（編輯）、`POST /reports/{id}/delete`（刪除），
  帶 session cookie 與 `X-CSRF-Token`（D-080）。表單欄位：`report_date`、`collaborator`（可重複）、各工項代碼。
- Given 直接寫資料庫（CONFIRMED、REJECTED 的狀態轉移由 M3 實作；任務 7）。
- 共用步驟（outcome、拒絕、稽核、登入）來自 tests/steps/common/，這裡不重新定義（pitfall #26）；
  RPT-F01 的 `"<name>" has N own reports dated ..., one of them PENDING` 也直接沿用。
- 本檔的輔助函式刻意不 import `rpt_f01_steps`：兩個步驟檔都是以「目錄在 sys.path 上」的方式載入，
  載入順序不是 T-202 能控制的；每個輔助函式都只有幾行。
- 不定義 `the audit description contains "…"`：同文字的步驟已由 T-201 定義（只看 REPORT_CREATE），
  RPT-R11「An edit with no change says so」要等 issue #30 的決定（pitfall #26、#29）。
"""
from __future__ import annotations

from urllib.parse import urlencode

import pytest
from pytest_bdd import given, parsers, then, when

from app.core.clock import clock
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import session_rows, sign_in_with_correct_password
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕與資料變動的共用步驟)
from tests.steps.common.steps import claim_audit_row

CSRF_HEADER = "X-CSRF-Token"

# 編輯時送出的內容：scenario 沒有指定數量時，用這個工項（WEST、SOUTH、BIG_METER 都有 direct_13）
EDIT_ITEM = "direct_13"


# ───────────────────────── 輔助 ─────────────────────────


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


def insert_report(db, submitter: str, date: str, status: str, *, items: dict[str, int] | None = None, crew: tuple[str, ...] = ()) -> int:
    """Given 用：直接寫一張回報（含工項數量與共同作業者），不經過任何產品端點。"""
    now = clock.now()
    submitter_id, zone, big = account_row(db, submitter)  # 先查：account_row 會 rollback，不能夾在待提交的寫入中間
    crew_ids = [account_row(db, who)[0] for who in crew]
    catalogue = "BIG_METER" if big else zone
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (submitter_id, date, catalogue, status, now, now),
        )
        rid = cur.fetchone()[0]
        for code, tenths in (items or {}).items():
            cur.execute("insert into yc_v3.report_items(report_id, item_code, tenths) values (%s, %s, %s)", (rid, code, tenths))
        for position, member_id in enumerate(crew_ids, start=1):
            cur.execute("insert into yc_v3.report_crew(report_id, position, account_id) values (%s, %s, %s)", (rid, position, member_id))
    db.commit()
    return rid


def report_state(db, report_id: int) -> str | None:
    """回報目前的狀態；已不存在回傳 None。"""
    with db.cursor() as cur:
        cur.execute("select status from yc_v3.reports where id = %s", (report_id,))
        row = cur.fetchone()
    db.rollback()
    return None if row is None else row[0]


def report_snapshot(db, report_id: int) -> dict:
    """回報的全部內容（日期、工項組、工項、共同作業者），用來比對「編輯前後哪些沒變」。"""
    with db.cursor() as cur:
        cur.execute("select report_date::text, catalogue, submitter_id from yc_v3.reports where id = %s", (report_id,))
        head = cur.fetchone()
        cur.execute("select item_code, tenths from yc_v3.report_items where report_id = %s order by item_code", (report_id,))
        items = cur.fetchall()
        cur.execute("select account_id from yc_v3.report_crew where report_id = %s order by position", (report_id,))
        crew = [r[0] for r in cur.fetchall()]
    db.rollback()
    return {"head": head, "items": items, "crew": crew}


def quantity_text(raw: str) -> str:
    return raw.strip()


def post(client, db, name: str, path: str, fields: list[tuple[str, str]]):
    """urlencoded 主體，欄位順序原樣保留。不用 `data=`（pitfall：同名欄位的順序不由我們控制）。"""
    return client.post(
        path,
        content=urlencode(fields),
        headers={"Content-Type": "application/x-www-form-urlencoded", CSRF_HEADER: csrf_token(db, name)},
        follow_redirects=False,
    )


@pytest.fixture
def lifecycle() -> dict:
    """scenario 內「那張回報」的資訊：id、誰在動作、原本的日期與狀態。fixture 名稱不用 `last`（RPT-F01 已定義）。"""
    return {}


def _remember(lifecycle: dict, report_id: int, date: str, state: str) -> int:
    lifecycle.update(report_id=report_id, date=date, state=state)
    return report_id


# ───────────────────────── Given ─────────────────────────

_DATE = "2026-11-15"  # background 的「今天」


@given(parsers.re(r'"(?P<name>[^"]+)" has an own report in state (?P<state>PENDING|CONFIRMED|REJECTED)$'))
def _has_own_report_in_state(db, lifecycle, name, state):
    _remember(lifecycle, insert_report(db, name, _DATE, state, items={EDIT_ITEM: 20}), _DATE, state)


@given(parsers.re(r'"(?P<name>[^"]+)" is a collaborator on a (?P<state>PENDING|CONFIRMED|REJECTED) report submitted by "(?P<submitter>[^"]+)"$'))
def _is_collaborator_on(db, lifecycle, name, state, submitter):
    rid = insert_report(db, submitter, _DATE, state, items={EDIT_ITEM: 20}, crew=(name,))
    _remember(lifecycle, rid, _DATE, state)


@given(parsers.re(r'"(?P<name>[^"]+)" has an own PENDING report dated "(?P<date>[^"]+)"$'))
def _has_own_pending_dated(db, lifecycle, name, date):
    _remember(lifecycle, insert_report(db, name, date, "PENDING", items={EDIT_ITEM: 20}), date, "PENDING")


@given(parsers.re(r'"(?P<name>[^"]+)" has an own PENDING report$'))
def _has_own_pending(db, lifecycle, name):
    _remember(lifecycle, insert_report(db, name, _DATE, "PENDING", items={EDIT_ITEM: 20}), _DATE, "PENDING")


@given(parsers.re(r'a CONFIRMED report by "(?P<name>[^"]+)"$'))
def _a_confirmed_report_by(db, lifecycle, name):
    _remember(lifecycle, insert_report(db, name, _DATE, "CONFIRMED", items={EDIT_ITEM: 20}), _DATE, "CONFIRMED")


# ───────────────────────── When ─────────────────────────


def _the_report(db, lifecycle, name: str | None = None) -> int:
    """scenario 的「那張回報」；R11 第一個 scenario 有 3 張，只有一張 PENDING，就取那一張。"""
    if "report_id" in lifecycle:
        return lifecycle["report_id"]
    assert name is not None
    with db.cursor() as cur:
        cur.execute(
            "select r.id, r.report_date::text from yc_v3.reports r join yc_v3.accounts a on a.id = r.submitter_id "
            "where a.name = %s and r.status = 'PENDING' order by r.id",
            (name,),
        )
        rows = cur.fetchall()
    db.rollback()
    assert len(rows) == 1, f"{name} 應恰有 1 張 PENDING 回報，實際 {rows}"
    lifecycle.update(report_id=rows[0][0], date=rows[0][1], state="PENDING")
    return rows[0][0]


def _edit(recorder, client, db, lifecycle, name, fields):
    rid = _the_report(db, lifecycle, name)
    ensure_signed_in(client, db, name)
    lifecycle["actor"] = name
    recorder.perform(lambda: post(client, db, name, f"/reports/{rid}", fields))


def _delete(recorder, client, db, lifecycle, name):
    rid = _the_report(db, lifecycle, name)
    ensure_signed_in(client, db, name)
    lifecycle["actor"] = name
    recorder.perform(lambda: post(client, db, name, f"/reports/{rid}/delete", []))


@when(parsers.re(r'"(?P<name>[^"]+)" tries to (?P<action>edit|delete) it$'))
def _tries_to(recorder, client, db, lifecycle, name, action):
    if action == "edit":
        _edit(recorder, client, db, lifecycle, name, [("report_date", lifecycle["date"]), (EDIT_ITEM, "5.0")])
    else:
        _delete(recorder, client, db, lifecycle, name)


@when(parsers.re(r'"(?P<name>[^"]+)" edits the PENDING report to "(?P<item>[^"]+)" = (?P<qty>.+)$'))
def _edits_pending_to(recorder, client, db, lifecycle, name, item, qty):
    _the_report(db, lifecycle, name)  # 先找出「那張 PENDING 回報」並記下它的日期，才能組出表單
    _edit(recorder, client, db, lifecycle, name, [("report_date", lifecycle["date"]), (item, quantity_text(qty))])


@when(parsers.re(r'"(?P<name>[^"]+)" edits it with report date "(?P<date>[^"]*)"$'))
def _edits_with_date(recorder, client, db, lifecycle, name, date):
    _edit(recorder, client, db, lifecycle, name, [("report_date", date), (EDIT_ITEM, "2.0")])


@when(parsers.re(r'"(?P<name>[^"]+)" saves it unchanged$'))
def _saves_unchanged(recorder, client, db, lifecycle, name):
    snap = report_snapshot(db, lifecycle["report_id"])
    fields = [("report_date", lifecycle["date"])] + [(code, f"{t // 10}.{t % 10}") for code, t in snap["items"]]
    _edit(recorder, client, db, lifecycle, name, fields)


@when(parsers.re(r'"(?P<name>[^"]+)" deletes it$'))
def _deletes_it(recorder, client, db, lifecycle, name):
    _delete(recorder, client, db, lifecycle, name)


# ───────────────────────── Then ─────────────────────────


@then(parsers.re(r"the report state is (?P<after>PENDING|CONFIRMED|REJECTED|gone)$"))
def _report_state_is(db, lifecycle, after):
    actual = report_state(db, lifecycle["report_id"])
    expected = None if after == "gone" else after
    assert actual == expected, f"回報的狀態應為 {after}，實際 {'gone' if actual is None else actual}"


@then(parsers.re(r'"(?P<name>[^"]+)" still has (?P<n>\d+) own reports dated "(?P<date>[^"]+)"$'))
def _still_has(db, name, n, date):
    with db.cursor() as cur:
        cur.execute(
            "select count(*) from yc_v3.reports r join yc_v3.accounts a on a.id = r.submitter_id where a.name = %s and r.report_date = %s",
            (name, date),
        )
        count = cur.fetchone()[0]
    db.rollback()
    assert count == int(n), f"{name} 在 {date} 應仍有 {n} 張自己的回報（編輯不佔額度），實際 {count}"


@then(parsers.re(r'an audit row "(?P<type_>[A-Z_]+)" is written$'))
def _audit_row_written(recorder, db, lifecycle, type_):
    claim_audit_row(recorder, db, type_, lifecycle["actor"])


@then("the report no longer exists")
def _report_gone(db, lifecycle):
    assert report_state(db, lifecycle["report_id"]) is None, "回報應已不存在"
