"""REV-F01 的細節測試：規格 scenario 沒有逐一寫出、但完成條件要求的行為（比規格更嚴格的斷言見 PR 說明）。

直接走 HTTP（TestClient）。輔助函式來自同目錄的 rev_f01_steps（由 conftest 載入）。每個測試只放一個錯誤原因。
"""
from __future__ import annotations

import threading
import time

import pytest
import rev_f01_steps as h
from fastapi.testclient import TestClient

from app.core.db import connect
from app.main import create_app
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import diff, take_snapshot

DATE = "2026-11-15"
CONFIRM = "/review/reports/confirm"
REJECT = "/review/reports/reject"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def sign_in(client, db, name):
    assert sign_in_with_correct_password(client, db, name).status_code == 303


def ids(*values):
    return [("id", str(v)) for v in values]


def audit(db):
    with db.cursor() as cur:
        cur.execute("select type, actor_name, description from yc_v3.audit_log order by id")
        rows = cur.fetchall()
    db.rollback()
    return rows


def run_and_diff(db, action):
    before = take_snapshot(db)
    response = action()
    return response, diff(before, take_snapshot(db))


# ───────────────────────── 確認與駁回寫了什麼 ─────────────────────────


def test_confirm_records_reviewer_time_shares_and_exactly_one_audit_row(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 70, "direct_20": 10}, crew=("Wei", "Wan"))
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", CONFIRM, ids(rid)))
    assert response.status_code == 200, response.text
    assert set(changes) == {"reports", "report_shares", "audit_log"}, f"只該動這三張表：{changes.keys()}"
    assert len(changes["report_shares"]["added"]) == 6, "2 個工項 × 3 人"
    rows = audit(db)
    assert [(t, a) for t, a, _ in rows] == [("REPORT_CONFIRM", "Admin1")]
    assert f"#{rid}" in rows[0][2] and "共 3 人作業" in rows[0][2], rows[0][2]
    assert h.report_row(db, rid)[:2] == ("CONFIRMED", "Admin1")


def test_reject_records_reviewer_and_stores_no_shares(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 70}, crew=("Wei",))
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", REJECT, ids(rid)))
    assert response.status_code == 200, response.text
    assert set(changes) == {"reports", "audit_log"}, f"駁回不存份額：{changes.keys()}"
    assert [(t, a) for t, a, _ in audit(db)] == [("REPORT_REJECT", "Admin1")]
    assert h.report_row(db, rid)[:2] == ("REJECTED", "Admin1")


def test_owner_can_confirm_like_an_administrator(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 70})
    sign_in(client, db, "Kuei")
    assert h.post(client, db, "Kuei", CONFIRM, ids(rid)).status_code == 200
    assert h.report_row(db, rid)[:2] == ("CONFIRMED", "Kuei")


def test_batch_reject_skips_non_pending_rows_and_writes_one_audit_row(client, db):
    pending = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    confirmed = h.insert_report(db, "Wen", DATE, "CONFIRMED", items={"direct_13": 20}, reviewer="Admin2")
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", REJECT, ids(pending, confirmed)))
    assert response.status_code == 200, response.text
    assert [t for t, _, _ in audit(db)] == ["REPORT_REJECT"]
    assert h.report_row(db, confirmed)[:2] == ("CONFIRMED", "Admin2"), "已確認的回報不被批次駁回碰到"
    assert h.report_row(db, pending)[:2] == ("REJECTED", "Admin1")


def test_batch_skips_an_id_that_no_longer_exists(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    response = h.post(client, db, "Admin1", CONFIRM, ids(rid, 999999))
    assert response.status_code == 200, response.text
    assert h.report_row(db, rid)[0] == "CONFIRMED"
    assert [t for t, _, _ in audit(db)] == ["REPORT_CONFIRM"], "不存在的 id 不寫稽核"


def test_confirming_twice_stores_shares_once_and_writes_one_audit_row(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 70}, crew=("Wei", "Wan"))
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", CONFIRM, ids(rid)).status_code == 200
    _, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", CONFIRM, ids(rid)))
    assert changes == {}, f"第二次確認（略過）不該改任何東西：{changes}"
    assert len(h.stored_shares(db, rid, "direct_13")) == 3


def test_confirm_does_not_store_shares_for_a_zero_quantity_item(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 0, "direct_20": 10}, crew=("Wei",))
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", CONFIRM, ids(rid)).status_code == 200
    assert h.stored_shares(db, rid, "direct_13") == []
    assert h.stored_shares(db, rid, "direct_20") == [("Wen", 5), ("Wei", 5)]


# ───────────────────────── 拒絕案例：類別、完整字串、資料不變 ─────────────────────────

ENDPOINTS = [
    ("GET", "/review"),
    ("GET", "/review/queue/ordinary"),
    ("GET", "/review/queue/big-meter"),
    ("POST", CONFIRM),
    ("POST", REJECT),
    ("POST", "/review/reports/1/unconfirm"),
]


def call(client, db, name, method, path):
    if method == "GET":
        return client.get(path)
    return h.post(client, db, name, path, ids(1))


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_a_user_is_forbidden_and_only_access_denied_is_written(client, db, method, path):
    h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    response, changes = run_and_diff(db, lambda: call(client, db, "Wen", method, path))
    assert response.status_code == 403 and response.json() == {"outcome": "FORBIDDEN", "message": None}
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1, changes
    assert [(t, a) for t, a, _ in audit(db)] == [("ACCESS_DENIED", "Wen")]
    assert h.report_row(db, 1)[0] == "PENDING"


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_signed_out_requests_are_unauthenticated_and_write_nothing(client, db, method, path):
    h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    response, changes = run_and_diff(db, lambda: client.request(method, path))
    assert response.status_code == 401 and response.json() == {"outcome": "UNAUTHENTICATED", "message": None}
    assert changes == {}


@pytest.mark.parametrize("bad", [[], [("id", "abc")], [("id", "0")], [("id", "-1")], [("id", "1.5")], [("id", "")], [("other", "1")], [("id", "01")]])
def test_ids_that_are_missing_or_malformed_are_invalid_and_write_nothing(client, db, bad):
    h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", CONFIRM, bad))
    assert response.status_code == 422 and response.json() == {"outcome": "INVALID", "message": None}
    assert changes == {}


def test_one_bad_id_rejects_the_whole_batch_and_confirms_nothing(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", CONFIRM, ids(rid) + [("id", "abc")]))
    assert response.status_code == 422 and changes == {}


def test_too_many_ids_are_invalid_and_write_nothing(client, db):
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", CONFIRM, ids(*range(1, 202))))
    assert response.status_code == 422 and response.json() == {"outcome": "INVALID", "message": None} and changes == {}


@pytest.mark.parametrize("state", ["PENDING", "CONFIRMED", "REJECTED"])
def test_unconfirm_is_always_a_conflict_without_a_message_and_writes_nothing(client, db, state):
    rid = h.insert_report(db, "Wen", DATE, state, items={"direct_13": 20}, reviewer="Admin2" if state != "PENDING" else None)
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", f"/review/reports/{rid}/unconfirm", []))
    assert response.status_code == 409 and response.json() == {"outcome": "CONFLICT", "message": None}
    assert changes == {}


def test_unconfirm_of_a_missing_report_is_also_a_conflict(client, db):
    sign_in(client, db, "Admin1")
    response, changes = run_and_diff(db, lambda: h.post(client, db, "Admin1", "/review/reports/999999/unconfirm", []))
    assert response.status_code == 409 and response.json() == {"outcome": "CONFLICT", "message": None} and changes == {}


# ───────────────────────── 鎖（完成條件 8） ─────────────────────────


def test_confirm_locks_each_report_with_the_lifecycle_lock_in_ascending_id_order(client, db, monkeypatch):
    from app.modules.reports.report_lifecycle import repo as lifecycle_repo

    created = [h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}) for _ in range(3)]
    seen: list[int] = []
    real = lifecycle_repo.lock_report

    def spy(conn, report_id):
        seen.append(report_id)
        return real(conn, report_id)

    monkeypatch.setattr(lifecycle_repo, "lock_report", spy)  # service 以 lifecycle_repo.lock_report 呼叫：換掉屬性即換掉它用的函式
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", CONFIRM, ids(created[2], created[0], created[1], created[0])).status_code == 200
    assert seen == sorted(created), f"應依 id 由小到大、每張只鎖一次：{seen}"


def test_reject_also_uses_the_lifecycle_lock(client, db, monkeypatch):
    from app.modules.reports.report_lifecycle import repo as lifecycle_repo

    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    seen: list[int] = []
    real = lifecycle_repo.lock_report
    monkeypatch.setattr(lifecycle_repo, "lock_report", lambda conn, report_id: (seen.append(report_id), real(conn, report_id))[1])
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", REJECT, ids(rid)).status_code == 200
    assert seen == [rid]


@pytest.mark.parametrize("path", [CONFIRM, REJECT])
def test_a_review_waits_for_a_row_lock_held_by_another_transaction(client, db, path):
    """另一個 transaction 持有這張回報的列鎖（例如 T-202 的編輯做到一半）：確認／駁回必須等它，不能插隊。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    token = h.csrf_token(db, "Admin1")
    holder = connect()
    holder.execute("select id from yc_v3.reports where id = %s for update", (rid,))
    done: dict = {}

    def worker():
        done["response"] = client.post(path, **h.form_request(ids(rid), token))

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(1.0)
    still_waiting = thread.is_alive()
    state_while_locked = h.report_row(db, rid)[0]
    holder.commit()
    holder.close()
    thread.join(timeout=30)
    assert still_waiting, "持有列鎖時，確認／駁回應該在等待"
    assert state_while_locked == "PENDING"
    assert done["response"].status_code == 200 and h.report_row(db, rid)[0] in ("CONFIRMED", "REJECTED")


def test_confirm_after_the_submitter_edit_stores_shares_for_the_new_content(client, db):
    """先編輯、後確認的順序：份額依編輯後的數量與小組存下。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, crew=("Wei",))
    sign_in(client, db, "Wen")
    wan = h.account_row(db, "Wan")[0]
    edit = h.post(client, db, "Wen", f"/reports/{rid}", [("report_date", DATE), ("collaborator", str(wan)), ("direct_13", "5.0")])
    assert edit.status_code == 200, edit.text
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", CONFIRM, ids(rid)).status_code == 200
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 25), ("Wan", 25)]


def test_the_submitter_cannot_edit_after_the_confirmation_and_shares_stay(client, db):
    """先確認、後編輯的順序：提交者被擋（FORBIDDEN），份額與內容不變。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, crew=("Wei",))
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", CONFIRM, ids(rid)).status_code == 200
    sign_in(client, db, "Wen")
    edit = h.post(client, db, "Wen", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "9.0")])
    assert edit.status_code == 403
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 10), ("Wei", 10)]


@pytest.mark.parametrize("round_", range(6))
def test_a_concurrent_edit_and_confirm_behave_like_one_running_after_the_other(client, db, round_):
    """提交者的編輯與管理員的確認同時送出：結果等同依序執行其中一個。
    不變式：確認後的回報，份額 = 它「現在的」內容（工項數量與小組）的分配；不會是舊數量的份額。"""
    from app.domain.split import split

    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, crew=("Wei",))
    wen, admin = TestClient(client.app, raise_server_exceptions=False), TestClient(client.app, raise_server_exceptions=False)
    sign_in(wen, db, "Wen")
    sign_in(admin, db, "Admin1")
    wan = h.account_row(db, "Wan")[0]
    wen_token, admin_token = h.csrf_token(db, "Wen"), h.csrf_token(db, "Admin1")
    barrier = threading.Barrier(2)
    out: dict = {}

    def do_edit():
        barrier.wait(timeout=30)
        out["edit"] = wen.post(f"/reports/{rid}", **h.form_request([("report_date", DATE), ("collaborator", str(wan)), ("direct_13", "5.0")], wen_token))

    def do_confirm():
        barrier.wait(timeout=30)
        out["confirm"] = admin.post(CONFIRM, **h.form_request(ids(rid), admin_token))

    threads = [threading.Thread(target=do_edit), threading.Thread(target=do_confirm)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert out["confirm"].status_code == 200 and out["edit"].status_code in (200, 403), (out["edit"].text, out["confirm"].text)
    assert h.report_row(db, rid)[0] == "CONFIRMED"
    with db.cursor() as cur:
        cur.execute("select item_code, tenths from yc_v3.report_items where report_id = %s", (rid,))
        items = dict(cur.fetchall())
        cur.execute("select account_id from yc_v3.report_crew where report_id = %s order by position", (rid,))
        crew = [r[0] for r in cur.fetchall()]
    db.rollback()
    expected = split(items["direct_13"], 1 + len(crew))
    stored = h.stored_shares(db, rid, "direct_13")
    assert [t for _, t in stored] == expected, f"份額應是現在的內容（{items}、小組 {crew}）的分配 {expected}，實際 {stored}"


# ───────────────────────── 頁面（REV-R01、完成條件 9） ─────────────────────────


def test_landing_page_links_to_both_queues_and_both_history_pages(client, db):
    sign_in(client, db, "Admin1")
    response = client.get("/review")
    assert response.status_code == 200
    for href in ("/review/queue/ordinary", "/review/queue/big-meter", "/review/history/ordinary", "/review/history/big-meter"):
        assert f'href="{href}"' in response.text, href


def test_queue_lists_only_pending_reports(client, db):
    pending = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    h.insert_report(db, "Wen", DATE, "CONFIRMED", items={"direct_13": 20}, reviewer="Admin2")
    h.insert_report(db, "Wen", DATE, "REJECTED", items={"direct_13": 20}, reviewer="Admin2")

    class R:  # recorder 的最小替身：queue_rows 只讀 response
        response = None

    sign_in(client, db, "Admin1")
    R.response = client.get("/review/queue/ordinary")
    assert [row[1] for row in h.queue_rows(R)] == [pending]


def test_big_meter_queue_lists_only_big_meter_reports(client, db):
    h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    big = h.insert_report(db, "Big", DATE, "PENDING", items={"direct_13": 20})

    class R:
        response = None

    sign_in(client, db, "Admin1")
    R.response = client.get("/review/queue/big-meter")
    assert [(row[0], row[1]) for row in h.queue_rows(R)] == [("BIG_METER", big)]


def test_queue_groups_by_the_catalogue_recorded_at_submission_not_the_current_zone(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set zone = 'SOUTH' where name = 'Wen'")
    db.commit()

    class R:
        response = None

    sign_in(client, db, "Admin1")
    R.response = client.get("/review/queue/ordinary")
    assert [(row[0], row[1]) for row in h.queue_rows(R)] == [("WEST", rid)], "AD-4：工項組在送出時就記下了"
