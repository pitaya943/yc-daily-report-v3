"""RPT-R12 的細節測試（T-301 補，D-085）：編輯與刪除對份額、審核者的影響。每個測試只放一個錯誤原因。"""
from __future__ import annotations

import pytest
import rpt_f02_steps as h
from fastapi.testclient import TestClient

from app.main import create_app
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import diff, take_snapshot

DATE = "2026-11-15"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def sign_in(client, db, name):
    assert sign_in_with_correct_password(client, db, name).status_code == 303


def confirmed(db, *, custom=None):
    """CONFIRMED、有目錄工項與（選擇性）自訂工項的份額，審核者 Admin2。"""
    rid = h.insert_report(db, "Wen", DATE, "CONFIRMED", items={"direct_13": 20}, crew=("Wei",), custom=custom)
    with db.cursor() as cur:
        cur.execute("update yc_v3.reports set reviewer_id = (select id from yc_v3.accounts where name = 'Admin2'), reviewed_at = %s where id = %s", (h.clock.now(), rid))
        for position, name in enumerate(("Wen", "Wei")):
            cur.execute("insert into yc_v3.report_shares select %s, 'direct_13', id, %s, 10 from yc_v3.accounts where name = %s", (rid, position, name))
            if custom:
                cur.execute("insert into yc_v3.report_custom_shares select %s, id, %s, 5 from yc_v3.accounts where name = %s", (rid, position, name))
    db.commit()
    return rid


def counts(db, rid):
    with db.cursor() as cur:
        cur.execute(
            "select (select count(*) from yc_v3.report_shares where report_id = %s), (select count(*) from yc_v3.report_custom_shares where report_id = %s)",
            (rid, rid),
        )
        row = cur.fetchone()
    db.rollback()
    return row


def reviewer(db, rid):
    with db.cursor() as cur:
        cur.execute("select reviewer_id, reviewed_at from yc_v3.reports where id = %s", (rid,))
        row = cur.fetchone()
    db.rollback()
    return row


def test_admin_edit_of_a_confirmed_report_deletes_catalogue_and_custom_shares(client, db):
    rid = confirmed(db, custom=("Extra", 10, 100))
    assert counts(db, rid) == (2, 2)
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert counts(db, rid) == (0, 0)


def test_admin_edit_of_a_confirmed_report_clears_the_reviewer(client, db):
    rid = confirmed(db)
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert reviewer(db, rid) == (None, None)


def test_edit_of_a_rejected_report_clears_the_reviewer(client, db):
    rid = h.insert_report(db, "Wen", DATE, "REJECTED", items={"direct_13": 20})
    with db.cursor() as cur:
        cur.execute("update yc_v3.reports set reviewer_id = (select id from yc_v3.accounts where name = 'Admin2'), reviewed_at = %s where id = %s", (h.clock.now(), rid))
    db.commit()
    sign_in(client, db, "Wen")
    assert h.post(client, db, "Wen", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert reviewer(db, rid) == (None, None)


def test_the_edit_of_a_confirmed_report_writes_only_the_expected_tables(client, db):
    rid = confirmed(db)
    sign_in(client, db, "Admin1")
    before = take_snapshot(db)
    assert h.post(client, db, "Admin1", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert set(diff(before, take_snapshot(db))) == {"reports", "report_items", "report_crew", "report_shares", "audit_log"}


def test_a_pending_edit_leaves_other_reports_shares_alone(client, db):
    other = confirmed(db)
    mine = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    assert h.post(client, db, "Wen", f"/reports/{mine}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert counts(db, other) == (2, 0)


def test_deleting_a_confirmed_report_removes_its_shares(client, db):
    rid = confirmed(db, custom=("Extra", 10, 100))
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", f"/reports/{rid}/delete", []).status_code == 200
    assert counts(db, rid) == (0, 0)


def test_confirming_again_after_the_edit_stores_the_new_shares_once(client, db):
    rid = confirmed(db)
    sign_in(client, db, "Admin1")
    assert h.post(client, db, "Admin1", f"/reports/{rid}", [("report_date", DATE), ("direct_13", "5.0")]).status_code == 200
    assert h.post(client, db, "Admin1", "/review/reports/confirm", [("id", str(rid))]).status_code == 200
    with db.cursor() as cur:
        cur.execute("select a.name, s.tenths from yc_v3.report_shares s join yc_v3.accounts a on a.id = s.account_id where report_id = %s order by position", (rid,))
        assert cur.fetchall() == [("Wen", 50)]  # 編輯把共同作業者清掉了（表單沒帶 collaborator）
    db.rollback()
