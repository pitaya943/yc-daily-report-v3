"""REV-F02 的細節測試：份額的保存與「計算薪資」的讀取函式（D-111）。每個測試只放一個錯誤原因。"""
from __future__ import annotations

from datetime import date

import pytest
import rev_f01_steps as h
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.review.crew_split_and_stored_shares import service as shares
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import diff, take_snapshot

DAY = "2026-11-10"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def confirm(client, db, *report_ids, who="Admin1"):
    assert sign_in_with_correct_password(client, db, who).status_code == 303
    response = h.post(client, db, who, "/review/reports/confirm", [("id", str(r)) for r in report_ids])
    assert response.status_code == 200, response.text


def qty(db, d_from, d_to):
    result = shares.confirmed_quantities(db, d_from, d_to)
    db.rollback()
    return result


def account_ids(db, *names):
    return [h.account_row(db, n)[0] for n in names]


def test_a_single_person_crew_gets_the_whole_quantity(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 73})
    confirm(client, db, rid)
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 73)]


def test_a_remainder_smaller_than_the_crew_still_stores_a_row_with_zero(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 1}, crew=("Wei", "Wan"))
    confirm(client, db, rid)
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 1), ("Wei", 0), ("Wan", 0)]


def test_the_submitter_gets_the_remainder_first_then_crew_order(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 5}, crew=("Wan", "Wei", "Nan"))
    confirm(client, db, rid)
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 2), ("Wan", 1), ("Wei", 1), ("Nan", 1)]


def test_a_collaborator_who_changed_zone_before_approval_still_gets_a_share(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70}, crew=("Wei",))
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set zone = 'SOUTH' where name = 'Wei'")
    db.commit()
    confirm(client, db, rid)
    assert h.stored_shares(db, rid, "direct_13") == [("Wen", 35), ("Wei", 35)]


def test_a_custom_item_with_zero_quantity_stores_no_shares(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 10}, crew=("Wei",), custom=("Extra", 0, 100))
    confirm(client, db, rid)
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.report_custom_shares where report_id = %s", (rid,))
        assert cur.fetchone()[0] == 0
    db.rollback()


def test_custom_item_shares_follow_the_same_rule_and_keep_position(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", custom=("Extra", 7, 100), crew=("Wei", "Wan"))
    confirm(client, db, rid)
    with db.cursor() as cur:
        cur.execute(
            "select a.name, s.position, s.tenths from yc_v3.report_custom_shares s join yc_v3.accounts a on a.id = s.account_id where report_id = %s order by position",
            (rid,),
        )
        assert cur.fetchall() == [("Wen", 0, 3), ("Wei", 1, 2), ("Wan", 2, 2)]
    db.rollback()


# ───────────────────────── 薪資的讀取函式 ─────────────────────────


def test_quantities_have_the_documented_shape(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70, "direct_20": 10}, crew=("Wei",))
    confirm(client, db, rid)
    wen, wei = account_ids(db, "Wen", "Wei")
    assert qty(db, date(2026, 11, 10), date(2026, 11, 10)) == {wen: {"direct_13": 35, "direct_20": 5}, wei: {"direct_13": 35, "direct_20": 5}}


def test_the_period_includes_both_ends_and_excludes_the_days_around_it(client, db):
    days = ["2026-11-05", "2026-11-06", "2026-11-13", "2026-11-14"]
    made = [h.insert_report(db, "Wen", d, "PENDING", items={"direct_13": 10}) for d in days]
    confirm(client, db, *made)
    wen = h.account_row(db, "Wen")[0]
    assert qty(db, date(2026, 11, 6), date(2026, 11, 13)) == {wen: {"direct_13": 20}}, "只有 11-06 與 11-13 兩張（含頭尾）"


def test_quantities_add_up_across_reports_for_each_account(client, db):
    a = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70}, crew=("Wei",))
    b = h.insert_report(db, "Wei", DAY, "PENDING", items={"direct_13": 30}, crew=("Wen",))
    confirm(client, db, a, b)
    wen, wei = account_ids(db, "Wen", "Wei")
    assert qty(db, date(2026, 11, 10), date(2026, 11, 10)) == {wen: {"direct_13": 50}, wei: {"direct_13": 50}}


@pytest.mark.parametrize("state", ["PENDING", "REJECTED"])
def test_unconfirmed_reports_do_not_count(db, state):
    h.insert_report(db, "Wen", DAY, state, items={"direct_13": 70})
    assert qty(db, date(2026, 11, 1), date(2026, 11, 30)) == {}


def test_an_empty_period_returns_an_empty_mapping(db):
    assert qty(db, date(2026, 11, 1), date(2026, 11, 30)) == {}


def test_an_archived_account_is_still_in_the_quantities(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70}, crew=("Wan",))
    confirm(client, db, rid)
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = 'Wan'")
    db.commit()
    assert account_ids(db, "Wan")[0] in qty(db, date(2026, 11, 1), date(2026, 11, 30))


def test_quantities_come_from_stored_shares_not_from_the_current_report_content(client, db):
    """份額是已確認數量的唯一來源：之後 report_items 或 report_crew 怎麼變，都不影響。"""
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70}, crew=("Wei",))
    confirm(client, db, rid)
    with db.cursor() as cur:
        cur.execute("update yc_v3.report_items set tenths = 999 where report_id = %s", (rid,))
        cur.execute("delete from yc_v3.report_crew where report_id = %s", (rid,))
    db.commit()
    wen, wei = account_ids(db, "Wen", "Wei")
    assert qty(db, date(2026, 11, 10), date(2026, 11, 10)) == {wen: {"direct_13": 35}, wei: {"direct_13": 35}}


def test_custom_item_quantities_are_not_part_of_the_result_yet(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 10}, custom=("Extra", 20, 100))
    confirm(client, db, rid)
    wen = h.account_row(db, "Wen")[0]
    assert qty(db, date(2026, 11, 10), date(2026, 11, 10)) == {wen: {"direct_13": 10}}, "T-302 才加自訂工項"


def test_reading_the_quantities_writes_nothing(client, db):
    rid = h.insert_report(db, "Wen", DAY, "PENDING", items={"direct_13": 70})
    confirm(client, db, rid)
    before = take_snapshot(db)
    qty(db, date(2026, 11, 1), date(2026, 11, 30))
    assert diff(before, take_snapshot(db)) == {}
