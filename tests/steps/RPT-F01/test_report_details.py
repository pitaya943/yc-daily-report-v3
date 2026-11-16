"""RPT-F01 的細節測試：scenario 沒有逐一涵蓋的邊界，以及給 T-202、T-203 import 的函式。

不是 Gherkin：這些是「伺服器重新驗證每個欄位、缺少的值不補預設值」（AGENTS.md #6）與 service.py／repo.py 的函式合約。
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.core.outcomes import Outcome, OutcomeError
from app.main import create_app
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo, service
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import take_snapshot, diff

CSRF = "X-CSRF-Token"


def _raises(fn, *args):
    with pytest.raises(OutcomeError) as e:
        fn(*args)
    return e.value


# ───────────────────────── 純函式：數量（RPT-R03）─────────────────────────


@pytest.mark.parametrize(
    "raw, tenths",
    [(None, 0), ("", 0), ("   ", 0), ("0", 0), ("0.0", 0), ("0.1", 1), ("1.0", 10), ("1.00", 10), ("2.3", 23), (" 2.3 ", 23), ("007", 70), ("999.9", 9999), ("999.90", 9999), ("999", 9990)],
)
def test_quantity_accepts_multiples_of_a_tenth(raw, tenths):
    assert service.parse_quantity(raw) == tenths


@pytest.mark.parametrize(
    "raw",
    ["1000", "999.91", "999.95", "1000.0", "0.05", "0.11", "1.01", "-1", "-0", "+1", "abc", "1e3", "1,0", "1.", ".5", ".", "1 2", "１", "２.３", "0x10", "NaN", "inf", "9" * 30],
)
def test_quantity_rejects_everything_else_with_the_appendix_b_string(raw):
    e = _raises(service.parse_quantity, raw)
    assert (e.outcome, e.message) == (Outcome.INVALID, "工項數量須為 0 到 999.9，最小單位 0.1")


# ───────────────────────── 純函式：日期（RPT-R02）─────────────────────────

TODAY = date(2026, 11, 15)


@pytest.mark.parametrize("raw, expected", [("2026-11-15", TODAY), ("2026-10-16", date(2026, 10, 16)), (" 2026-11-15 ", TODAY)])
def test_date_accepts_today_and_30_days_back(raw, expected):
    assert service.parse_report_date(raw, TODAY) == expected


@pytest.mark.parametrize("raw", [None, "", " ", "2026-10-15", "2026-11-16", "2027-11-15", "2026-02-30", "20261115", "2026/11/15", "2026-1-5", "11-15-2026", "２０２６-11-15", "tomorrow"])
def test_date_rejects_with_the_appendix_b_string(raw):
    e = _raises(service.parse_report_date, raw, TODAY)
    assert (e.outcome, e.message) == (Outcome.INVALID, "回報日期須為今天或往前 30 天內，不可選擇未來日期")


def test_date_window_follows_the_given_today_across_a_year_boundary():
    assert service.parse_report_date("2025-12-31", date(2026, 1, 30)) == date(2025, 12, 31)
    assert _raises(service.parse_report_date, "2025-12-30", date(2026, 1, 30)).outcome is Outcome.INVALID


# ───────────────────────── 純函式：工項（RPT-R01）─────────────────────────


def test_quantities_keep_blank_as_zero_and_do_not_invent_missing_items():
    out = service.parse_quantities({"report_date": ["2026-11-15"], "direct_13": [""], "direct_20": ["2.3"], "collaborator": ["1"]}, "WEST")
    assert out == {"direct_13": 0, "direct_20": 23}  # 沒送的工項不存在，也不會被補成 0


@pytest.mark.parametrize("code", ["s_orig_13", "bm_app", "nonsense", "", "direct_13 ", "DIRECT_13", "bm_40_fen"])
def test_an_item_outside_the_catalogue_is_invalid_without_a_message(code):
    e = _raises(service.parse_quantities, {code: ["1.0"]}, "WEST")
    assert (e.outcome, e.message) == (Outcome.INVALID, None)


def test_the_same_item_sent_twice_is_invalid():
    assert _raises(service.parse_quantities, {"direct_13": ["1", "2"]}, "WEST").outcome is Outcome.INVALID


def test_the_bm_40_fen_item_never_appears():  # Q-007
    assert all("bm_40_fen" not in cat.item_codes(n) for n in cat.CATALOGUE_NAMES)


def test_catalogue_selection_follows_zone_and_the_big_meter_flag():
    assert cat.catalogue_name_for("WEST", False) == "WEST"
    assert cat.catalogue_name_for("SOUTH", False) == "SOUTH"
    assert cat.catalogue_name_for("WEST", True) == "BIG_METER"
    assert cat.catalogue_name_for("SOUTH", True) == "BIG_METER"
    assert cat.display_name("WEST", "direct_13") == "直總-13"


# ───────────────────────── 送出（HTTP）─────────────────────────


def _client_for(db, name: str):
    client = TestClient(create_app(), raise_server_exceptions=False)
    sign_in_with_correct_password(client, db, name)
    token = db.execute("select s.anti_forgery_token from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id where a.name = %s", (name,)).fetchone()[0]
    db.rollback()
    return client, token


def _post(client, token, fields):
    return client.post("/reports", content=urlencode(fields), headers={"Content-Type": "application/x-www-form-urlencoded", CSRF: token}, follow_redirects=False)


def _assert_rejected_and_unchanged(db, before, response, outcome, message):
    assert response.status_code == outcome.http_status
    assert response.json() == {"outcome": outcome.value, "message": message}
    assert diff(before, take_snapshot(db)) == {}


def test_a_missing_report_date_is_invalid_and_is_not_defaulted_to_today(db):
    client, token = _client_for(db, "Wen")
    before = take_snapshot(db)
    response = _post(client, token, [("direct_13", "1.0")])
    _assert_rejected_and_unchanged(db, before, response, Outcome.INVALID, service.MSG_DATE)


def test_a_blank_report_date_and_a_repeated_report_date_are_invalid(db):
    client, token = _client_for(db, "Wen")
    before = take_snapshot(db)
    _assert_rejected_and_unchanged(db, before, _post(client, token, [("report_date", ""), ("direct_13", "1.0")]), Outcome.INVALID, service.MSG_DATE)
    two = _post(client, token, [("report_date", "2026-11-15"), ("report_date", "2026-11-14"), ("direct_13", "1.0")])
    _assert_rejected_and_unchanged(db, before, two, Outcome.INVALID, service.MSG_DATE)


def test_an_unknown_field_is_invalid_and_nothing_is_written(db):
    client, token = _client_for(db, "Wen")
    before = take_snapshot(db)
    response = _post(client, token, [("report_date", "2026-11-15"), ("direct_13", "1.0"), ("status", "CONFIRMED")])
    _assert_rejected_and_unchanged(db, before, response, Outcome.INVALID, None)


def test_the_status_cannot_be_chosen_by_the_client(db):
    # 欄位名稱 status 是未知欄位（上一個測試）；送出的回報一定是 PENDING
    client, token = _client_for(db, "Wen")
    assert _post(client, token, [("report_date", "2026-11-15"), ("direct_13", "1.0")]).status_code == 200
    assert db.execute("select status from yc_v3.reports").fetchone()[0] == "PENDING"
    db.rollback()


def test_a_post_without_the_anti_forgery_token_is_forbidden_and_writes_only_the_audit_row(db):
    client, _ = _client_for(db, "Wen")
    before = take_snapshot(db)
    response = client.post("/reports", content="report_date=2026-11-15&direct_13=1.0", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert response.status_code == 403
    changes = diff(before, take_snapshot(db))
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1


def test_nobody_signed_in_is_unauthenticated(db):
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert client.get("/reports").status_code == 401
    assert client.post("/reports", content="report_date=2026-11-15", headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 401


@pytest.mark.parametrize("name", ["Admin1", "Kuei"])
def test_administrators_cannot_even_open_the_form(db, name):
    client, _ = _client_for(db, name)
    before = take_snapshot(db)
    response = client.get("/reports")
    assert response.status_code == 403
    changes = diff(before, take_snapshot(db))
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1


def test_an_oversized_body_is_invalid(db):
    client, token = _client_for(db, "Wen")
    before = take_snapshot(db)
    response = _post(client, token, [("report_date", "2026-11-15"), ("direct_13", "1" * 20000)])
    _assert_rejected_and_unchanged(db, before, response, Outcome.INVALID, None)


def _add_users(db, n: int, zone="WEST", big=False):
    for i in range(n):
        db.execute("insert into yc_v3.accounts(name, role, zone, big_meter) values (%s, 'USER', %s, %s)", (f"Extra{zone}{big}{i}", zone, big))
    db.commit()
    return [r[0] for r in db.execute("select id from yc_v3.accounts where name like %s order by id", (f"Extra{zone}{big}%",)).fetchall()]


def test_seven_eligible_collaborators_are_invalid_and_six_are_fine(db):
    ids = _add_users(db, 7)
    client, token = _client_for(db, "Wen")
    base = [("report_date", "2026-11-15"), ("direct_13", "1.0")]
    before = take_snapshot(db)
    seven = _post(client, token, base + [("collaborator", str(i)) for i in ids])
    _assert_rejected_and_unchanged(db, before, seven, Outcome.INVALID, service.MSG_COLLABORATORS)
    six = _post(client, token, base + [("collaborator", str(i)) for i in ids[:6]])
    assert six.status_code == 200
    report = repo.list_reports(db)[0]
    db.rollback()
    assert [c[0] for c in report.crew] == ids[:6]


def test_the_catalogue_is_recorded_at_submit_time_and_survives_a_later_zone_change(db):  # AD-4
    client, token = _client_for(db, "Wen")
    assert _post(client, token, [("report_date", "2026-11-15"), ("direct_13", "1.0")]).status_code == 200
    db.execute("update yc_v3.accounts set zone = 'SOUTH' where name = 'Wen'")
    db.commit()
    assert repo.list_reports(db)[0].catalogue == "WEST"
    db.rollback()


def test_the_form_offers_only_eligible_collaborators(db):
    client, _ = _client_for(db, "Wen")
    html = client.get("/reports").text
    for expected in ("Wei", "Wan"):
        assert f">{expected}<" in html
    for forbidden in ("Nan", "Big", "Old", "Admin1", "Kuei", ">Wen<"):
        assert forbidden not in html.split("共同作業者")[1].split("工項數量")[0], forbidden


def test_html_in_a_display_name_is_escaped(db):
    db.execute("update yc_v3.accounts set name = %s where name = 'Wei'", ("<script>alert(1)</script>",))
    db.commit()
    client, _ = _client_for(db, "Wen")
    html = client.get("/reports").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_the_page_carries_the_anti_forgery_header_from_the_shared_layout(db):
    client, token = _client_for(db, "Wen")
    html = client.get("/reports").text
    assert f'hx-headers=\'{{"X-CSRF-Token": "{token}"}}\'' in html
    assert 'name="csrf' not in html.lower() and 'type="hidden"' not in html  # D-080：不放隱藏欄位


# ───────────────────────── repo：給 T-202、T-203 用的函式 ─────────────────────────


def _make(db, name="Wen", date_="2026-11-15", status="PENDING", crew=(), items=None):
    ids = {r[1]: r[0] for r in db.execute("select id, name from yc_v3.accounts").fetchall()}
    account = repo.get_account(db, ids[name])
    rid = repo.insert_report(
        db, submitter_id=account.id, report_date=date.fromisoformat(date_), catalogue=cat.catalogue_name_for(account.zone, account.big_meter),
        status=status, now=clock.now(), items=items or {"direct_13": 10}, crew_ids=[ids[c] for c in crew],
    )
    db.commit()
    return rid, ids


def test_get_report_returns_items_crew_in_order_and_empty_custom_item(db):
    rid, ids = _make(db, crew=("Wan", "Wei"), items={"direct_20": 5, "direct_13": 23})
    r = repo.get_report(db, rid)
    assert (r.submitter_name, r.status, r.catalogue, r.report_date) == ("Wen", "PENDING", "WEST", date(2026, 11, 15))
    assert r.items == {"direct_13": 23, "direct_20": 5}
    assert [c[1] for c in r.crew] == ["Wan", "Wei"]
    assert (r.custom_name, r.custom_tenths, r.custom_price) == (None, None, None)
    assert repo.get_report(db, rid + 100) is None


def test_replace_content_changes_items_crew_and_status_but_not_date_or_catalogue(db):
    rid, ids = _make(db, status="CONFIRMED", crew=("Wei",))
    clock.advance(timedelta(minutes=5))
    repo.replace_report_content(db, rid, items={"direct_25": 7}, crew_ids=[ids["Wan"], ids["Wei"]], status="PENDING", now=clock.now())
    db.commit()
    r = repo.get_report(db, rid)
    assert (r.status, r.items, [c[1] for c in r.crew], r.report_date, r.catalogue) == ("PENDING", {"direct_25": 7}, ["Wan", "Wei"], date(2026, 11, 15), "WEST")
    assert r.updated_at > r.created_at


def test_delete_frees_the_quota_and_removes_the_children(db):
    rid, ids = _make(db, crew=("Wei",))
    assert repo.count_own_reports(db, ids["Wen"], date(2026, 11, 15)) == 1
    assert repo.delete_report(db, rid) is True
    db.commit()
    assert repo.count_own_reports(db, ids["Wen"], date(2026, 11, 15)) == 0
    assert db.execute("select (select count(*) from yc_v3.report_items) + (select count(*) from yc_v3.report_crew)").fetchone()[0] == 0
    assert repo.delete_report(db, rid) is False
    db.rollback()


def test_list_reports_filters_and_orders_newest_first(db):
    a, ids = _make(db, "Wen", "2026-11-10")
    b, _ = _make(db, "Wen", "2026-11-14", crew=("Wei",))
    c, _ = _make(db, "Wei", "2026-11-12", status="CONFIRMED")
    assert [r.id for r in repo.list_reports(db)] == [b, c, a]
    assert [r.id for r in repo.list_reports(db, submitter_id=ids["Wen"])] == [b, a]
    assert [r.id for r in repo.list_reports(db, collaborator_id=ids["Wei"])] == [b]
    assert [r.id for r in repo.list_reports(db, submitter_id=ids["Wei"], collaborator_id=ids["Wei"])] == [b, c]  # 我送出的加上我是共同作業者的
    assert [r.id for r in repo.list_reports(db, date_from=date(2026, 11, 11), date_to=date(2026, 11, 13))] == [c]
    assert [r.id for r in repo.list_reports(db, status="CONFIRMED")] == [c]


# ───────────────────────── 資料庫約束（migration 0005 的最後防線）─────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        "update yc_v3.reports set status = 'DONE'",
        "update yc_v3.reports set catalogue = 'EAST'",
        "update yc_v3.reports set custom_name = 'x'",  # 三者同時為 null 或同時有值
        "update yc_v3.reports set custom_name = 'x', custom_tenths = 1",
        "update yc_v3.reports set custom_name = '', custom_tenths = 1, custom_price = 1",
        "update yc_v3.reports set custom_name = repeat('x', 101), custom_tenths = 1, custom_price = 1",
        "update yc_v3.reports set custom_name = 'x', custom_tenths = 10000, custom_price = 1",
        "update yc_v3.reports set custom_name = 'x', custom_tenths = -1, custom_price = 1",
        "update yc_v3.reports set custom_name = 'x', custom_tenths = 1, custom_price = -1",
        "update yc_v3.reports set updated_at = created_at - interval '1 second'",
        "update yc_v3.report_items set tenths = 10000",
        "update yc_v3.report_items set tenths = -1",
        "update yc_v3.report_crew set position = 7",
        "insert into yc_v3.report_crew(report_id, position, account_id) select report_id, 2, account_id from yc_v3.report_crew",  # 同一人只能出現一次
    ],
)
def test_database_constraints_reject_bad_data(db, sql):
    import psycopg

    _make(db, crew=("Wei",))
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute(sql)
    db.rollback()


@pytest.mark.parametrize("custom", [(None, None, None), ("自訂", 0, 0), ("x" * 100, 9999, 123456)])
def test_database_accepts_a_whole_custom_item_or_none(db, custom):
    rid, _ = _make(db)
    db.execute("update yc_v3.reports set custom_name = %s, custom_tenths = %s, custom_price = %s where id = %s", (*custom, rid))
    db.commit()
    r = repo.get_report(db, rid)
    assert (r.custom_name, r.custom_tenths, r.custom_price) == custom
    db.rollback()
