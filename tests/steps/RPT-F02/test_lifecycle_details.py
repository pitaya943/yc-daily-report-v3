"""RPT-F02 的細節測試：規格 scenario 沒有逐一寫出、但完成條件要求的行為（比規格更嚴格的斷言見 PR 說明）。

直接走 HTTP（TestClient），輔助函式來自同目錄的 rpt_f02_steps（由 conftest 載入）。
"""
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


def edit(client, db, name, rid, fields):
    return h.post(client, db, name, f"/reports/{rid}", fields)


def audit(db):
    with db.cursor() as cur:
        cur.execute("select type, actor_name, description from yc_v3.audit_log order by id")
        rows = cur.fetchall()
    db.rollback()
    return rows


def test_admin_edit_of_confirmed_returns_to_pending_and_writes_two_audit_rows(client, db):
    rid = h.insert_report(db, "Wen", DATE, "CONFIRMED", items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    r = edit(client, db, "Admin1", rid, [("report_date", DATE), ("direct_13", "5.0")])
    assert r.status_code == 200, r.text
    assert h.report_state(db, rid) == "PENDING"
    assert h.report_snapshot(db, rid)["items"] == [("direct_13", 50)]
    rows = audit(db)
    assert [(t, a) for t, a, _ in rows] == [("REPORT_UNCONFIRM", "Admin1"), ("REPORT_UPDATE", "Admin1")]
    assert "direct_13 2.0→5.0" in rows[1][2]


@pytest.mark.parametrize("state", ["PENDING", "REJECTED"])
def test_admin_edit_of_unconfirmed_writes_only_update(client, db, state):
    rid = h.insert_report(db, "Wen", DATE, state, items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    assert edit(client, db, "Admin1", rid, [("report_date", DATE), ("direct_13", "3.5")]).status_code == 200
    assert h.report_state(db, rid) == "PENDING"
    assert [t for t, _, _ in audit(db)] == ["REPORT_UPDATE"]


def test_owner_role_can_edit_and_delete_like_an_admin(client, db):
    rid = h.insert_report(db, "Wen", DATE, "CONFIRMED", items={"direct_13": 20})
    sign_in(client, db, "Kuei")
    assert edit(client, db, "Kuei", rid, [("report_date", DATE), ("direct_13", "1.0")]).status_code == 200
    assert h.post(client, db, "Kuei", f"/reports/{rid}/delete", []).status_code == 200
    assert h.report_state(db, rid) is None


def test_edit_keeps_date_catalogue_and_submitter_and_replaces_content(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20, "direct_20": 10}, crew=("Wei",))
    before = h.report_snapshot(db, rid)
    sign_in(client, db, "Wen")
    wan = h.account_row(db, "Wan")[0]
    fields = [("report_date", DATE), ("collaborator", str(wan)), ("direct_13", "7.5")]
    assert edit(client, db, "Wen", rid, fields).status_code == 200
    after = h.report_snapshot(db, rid)
    assert after["head"] == before["head"], "日期、工項組、提交者不變"
    assert after["items"] == [("direct_13", 75)], "以送出的內容整個取代：沒送的工項不留"
    assert after["crew"] == [wan]


def test_edit_does_not_use_quota_even_when_the_day_is_full(client, db):
    ids = [h.insert_report(db, "Wen", DATE, "PENDING") for _ in range(3)]
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", ids[0], [("report_date", DATE), ("direct_13", "1.0")]).status_code == 200


def test_edit_works_on_a_report_older_than_30_days(client, db):
    old = "2026-09-01"  # 超過「往前 30 天」：編輯不該因此被擋（日期沒改）
    rid = h.insert_report(db, "Wen", old, "PENDING")
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", rid, [("report_date", old), ("direct_13", "1.0")]).status_code == 200


def test_delete_releases_the_daily_quota(client, db):
    ids = [h.insert_report(db, "Wen", DATE, "PENDING") for _ in range(3)]
    sign_in(client, db, "Wen")
    assert h.post(client, db, "Wen", f"/reports/{ids[0]}/delete", []).status_code == 200
    assert h.post(client, db, "Wen", "/reports", [("report_date", DATE), ("direct_13", "1.0")]).status_code == 200


def test_delete_removes_items_and_crew_and_writes_one_audit_row(client, db):
    rid = h.insert_report(db, "Wen", DATE, "REJECTED", items={"direct_13": 20}, crew=("Wei",))
    sign_in(client, db, "Wen")
    assert h.post(client, db, "Wen", f"/reports/{rid}/delete", []).status_code == 200
    with db.cursor() as cur:
        cur.execute("select (select count(*) from yc_v3.report_items), (select count(*) from yc_v3.report_crew)")
        assert cur.fetchone() == (0, 0)
    db.rollback()
    assert [(t, a) for t, a, _ in audit(db)] == [("REPORT_DELETE", "Wen")]


@pytest.mark.parametrize(
    "fields, message",
    [
        ([("direct_13", "5.0")], "回報日期須為今天或往前 30 天內，不可選擇未來日期"),  # 缺少日期：不補已存的日期
        ([("report_date", ""), ("direct_13", "5.0")], "回報日期須為今天或往前 30 天內，不可選擇未來日期"),
        ([("report_date", "2026/11/15"), ("direct_13", "5.0")], "回報日期須為今天或往前 30 天內，不可選擇未來日期"),
        ([("report_date", DATE), ("report_date", DATE), ("direct_13", "5.0")], "回報日期須為今天或往前 30 天內，不可選擇未來日期"),
        ([("report_date", "2026-11-16"), ("direct_13", "5.0")], "回報日期送出後不可修改"),
        ([("report_date", DATE), ("direct_20", "1.0"), ("direct_13", "abc")], "工項數量須為 0 到 999.9，最小單位 0.1"),
        ([("report_date", DATE), ("direct_20", "1.0"), ("direct_13", "0.05")], "工項數量須為 0 到 999.9，最小單位 0.1"),
        ([("report_date", DATE), ("direct_20", "1.0"), ("direct_13", "1000")], "工項數量須為 0 到 999.9，最小單位 0.1"),
        ([("report_date", DATE), ("direct_20", "1.0"), ("direct_13", "1"), ("direct_13", "2")], "工項數量須為 0 到 999.9，最小單位 0.1"),
    ],
)
def test_invalid_fields_are_rejected_with_the_full_string_and_nothing_changes(client, db, fields, message):
    rid = h.insert_report(db, "Wen", DATE, "REJECTED", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, fields)
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": message}
    assert diff(before, take_snapshot(db)) == {}, "拒絕時資料庫完全不變"


@pytest.mark.parametrize("extra", [("status", "CONFIRMED"), ("submitter_id", "1"), ("not_an_item", "1"), ("catalogue", "SOUTH")])
def test_unknown_fields_are_invalid_and_the_client_cannot_set_the_state(client, db, extra):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "5.0"), extra])
    assert r.status_code == 422 and r.json()["outcome"] == "INVALID"
    assert diff(before, take_snapshot(db)) == {}


def test_an_item_of_another_catalogue_is_invalid(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING")  # WEST
    sign_in(client, db, "Wen")
    from app.modules.reports.submit_a_daily_report import catalogue as cat

    other = sorted(cat.item_codes("SOUTH") - cat.item_codes("WEST"))
    assert other, "SOUTH 應有 WEST 沒有的工項"
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "5.0"), (other[0], "1.0")])
    assert r.status_code == 422 and r.json()["outcome"] == "INVALID"
    assert diff(before, take_snapshot(db)) == {}


def test_an_edit_without_collaborators_clears_the_crew(client, db):
    """作業小組是「以送出的內容整個取代」：沒有送 collaborator 就是沒有共同作業者（不涉及資格判斷）。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, crew=("Wei",))
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "2.0")]).status_code == 200
    assert h.report_snapshot(db, rid)["crew"] == []


def test_more_than_six_collaborators_is_invalid(client, db):
    from app.modules.reports.submit_a_daily_report.service import MSG_COLLABORATORS

    rid = h.insert_report(db, "Wen", DATE, "PENDING")
    with db.cursor() as cur:  # 再加 6 位同區同類型的啟用 USER，湊成 7 位合格者
        for i in range(6):
            cur.execute("insert into yc_v3.accounts(name, role, zone, big_meter, archived) values (%s, 'USER', 'WEST', false, false)", (f"Extra{i}",))
    db.commit()
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where role = 'USER' and zone = 'WEST' and not big_meter and not archived and name <> 'Wen'")
        ids = [r[0] for r in cur.fetchall()]
    db.rollback()
    assert len(ids) >= 7
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "1.0")] + [("collaborator", str(i)) for i in ids[:7]])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_COLLABORATORS}
    assert diff(before, take_snapshot(db)) == {}


@pytest.mark.parametrize("who, state", [("Nan", "PENDING"), ("Wei", "REJECTED"), ("Admin1", None)])
def test_nobody_else_may_edit_or_delete_and_the_attempt_is_audited(client, db, who, state):
    """其他 USER（不同區、共同作業者、無關的人）一律 FORBIDDEN 並寫 ACCESS_DENIED，回報不變；Admin1 這列是對照（可以）。"""
    rid = h.insert_report(db, "Wen", DATE, state or "PENDING", items={"direct_13": 20})
    sign_in(client, db, who)
    before = take_snapshot(db)
    for path in (f"/reports/{rid}", f"/reports/{rid}/delete"):
        r = h.post(client, db, who, path, [("report_date", DATE), ("direct_13", "9.0")] if path.endswith(str(rid)) else [])
        if state is None:
            assert r.status_code == 200
        else:
            assert r.status_code == 403 and r.json() == {"outcome": "FORBIDDEN", "message": None}
    if state is not None:
        changes = diff(before, take_snapshot(db))
        assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 2
        assert [(t, a) for t, a, _ in audit(db)] == [("ACCESS_DENIED", who)] * 2


def test_unauthenticated_and_missing_csrf_and_missing_report(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING")
    assert client.post(f"/reports/{rid}", content="report_date=" + DATE).status_code == 401
    assert client.post(f"/reports/{rid}/delete").status_code == 401
    assert client.get(f"/reports/{rid}/edit").status_code == 401
    sign_in(client, db, "Wen")
    r = client.post(f"/reports/{rid}/delete")  # 沒有 X-CSRF-Token
    assert r.status_code == 403
    assert h.report_state(db, rid) == "PENDING"
    assert h.post(client, db, "Wen", "/reports/9999", [("report_date", DATE)]).status_code == 404
    assert h.post(client, db, "Wen", "/reports/9999/delete", []).status_code == 404


def test_edit_page_prefills_the_report_and_is_forbidden_when_confirmed(client, db):
    rid = h.insert_report(db, "Wen", DATE, "REJECTED", items={"direct_13": 55}, crew=("Wei",))
    sign_in(client, db, "Wen")
    page = client.get(f"/reports/{rid}/edit")
    assert page.status_code == 200
    assert 'name="direct_13" value="5.5"' in page.text
    assert f'value="{DATE}" readonly' in page.text
    wei = h.account_row(db, "Wei")[0]
    assert f'<option value="{wei}" selected>Wei</option>' in page.text
    confirmed = h.insert_report(db, "Wen", DATE, "CONFIRMED")
    r = client.get(f"/reports/{confirmed}/edit")
    assert r.status_code == 403 and r.json()["outcome"] == "FORBIDDEN"
    sign_in(client, db, "Admin1")
    assert client.get(f"/reports/{confirmed}/edit").status_code == 200


def test_no_change_description_and_a_change_description(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "2.0")]).status_code == 200
    assert edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "2.5")]).status_code == 200
    descriptions = [d for t, _, d in audit(db) if t == "REPORT_UPDATE"]
    assert "無變更" in descriptions[0] and "無變更" not in descriptions[1] and "direct_13 2.0→2.5" in descriptions[1]


def test_blank_quantity_equals_a_missing_item_for_the_no_change_check(client, db):
    """表單送出時空白欄位存成 0；沒有存過的工項與 0 視為相同，不算「有變更」（回報另有一個有數量的工項）。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_20": 10})
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_20", "1.0"), ("direct_13", "")]).status_code == 200
    assert "無變更" in audit(db)[-1][2]


def test_a_confirmed_report_cannot_be_edited_by_the_submitter_even_with_a_stale_form(client, db):
    """表單打開時是 PENDING，之後被確認：送出時以資料庫當下的狀態判斷（不是表單打開時的狀態）。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    assert client.get(f"/reports/{rid}/edit").status_code == 200
    with db.cursor() as cur:
        cur.execute("update yc_v3.reports set status = 'CONFIRMED' where id = %s", (rid,))
    db.commit()
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "9.0")])
    assert r.status_code == 403
    assert h.report_snapshot(db, rid)["items"] == [("direct_13", 20)] and h.report_state(db, rid) == "CONFIRMED"


def test_the_date_message_is_the_same_string_as_the_submit_form_uses():
    from app.modules.reports.report_lifecycle import service
    from app.modules.reports.submit_a_daily_report import service as submit

    assert service.MSG_DATE == submit.MSG_DATE


# ───────────────────────── T-204：編輯時至少一個工項（RPT-R14）與共同作業者資格（RPT-R05，D-096、D-097）─────────────────────────

MSG_NO_QUANTITY = "請至少填寫一個工項數量"  # spec/appendix-b-fields.md
MSG_COLLAB_TEXT = "共同作業者最多 6 人，且須為同一區域、同一類型的啟用員工"


def _account_id(db, name):
    return h.account_row(db, name)[0]


@pytest.mark.parametrize("fields_after_date", [[], [("direct_13", "0")], [("direct_13", ""), ("direct_20", "0.0")]])
def test_an_edit_that_leaves_no_quantity_is_invalid_and_changes_nothing(client, db, fields_after_date):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE)] + fields_after_date)
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_NO_QUANTITY}
    assert diff(before, take_snapshot(db)) == {}


@pytest.mark.parametrize("state", ["PENDING", "REJECTED", "CONFIRMED"])
def test_the_admin_edit_of_every_state_also_needs_a_quantity(client, db, state):
    rid = h.insert_report(db, "Wen", DATE, state, items={"direct_13": 20})
    sign_in(client, db, "Admin1")
    before = take_snapshot(db)
    r = edit(client, db, "Admin1", rid, [("report_date", DATE), ("direct_13", "0")])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_NO_QUANTITY}
    assert diff(before, take_snapshot(db)) == {}  # CONFIRMED 也不會退回 PENDING、不寫 REPORT_UNCONFIRM


def test_a_custom_item_quantity_of_zero_does_not_count(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", custom=("夜間加班", 0, 500))
    sign_in(client, db, "Admin1")
    before = take_snapshot(db)
    r = edit(client, db, "Admin1", rid, [("report_date", DATE), ("direct_13", "0")])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_NO_QUANTITY}
    assert diff(before, take_snapshot(db)) == {}


def test_an_edit_keeps_the_custom_item_when_the_catalogue_quantities_are_cleared(client, db):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, custom=("夜間加班", 20, 500))
    sign_in(client, db, "Wen")
    assert edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "0")]).status_code == 200
    row = db.execute("select custom_name, custom_tenths, custom_price from yc_v3.reports where id = %s", (rid,)).fetchone()
    db.rollback()
    assert row == ("夜間加班", 20, 500)


def _edit_with_collaborators(client, db, ids):
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20})
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "2.0")] + [("collaborator", str(i)) for i in ids])
    return rid, before, r


@pytest.mark.parametrize("who", ["Nan", "Big", "Old", "Admin1", "Wen"])
def test_an_edit_naming_an_ineligible_collaborator_is_invalid_and_changes_nothing(client, db, who):
    _, before, r = _edit_with_collaborators(client, db, [_account_id(db, who)])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_COLLAB_TEXT}
    assert diff(before, take_snapshot(db)) == {}


def test_an_edit_naming_the_same_collaborator_twice_is_invalid_and_changes_nothing(client, db):
    wei = _account_id(db, "Wei")
    _, before, r = _edit_with_collaborators(client, db, [wei, wei])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_COLLAB_TEXT}
    assert diff(before, take_snapshot(db)) == {}


def test_an_edit_with_a_stale_collaborator_who_was_archived_after_submit_is_refused(client, db):
    """原本在作業小組裡、之後被封存的人：表單不再提供；用舊的表單送出會被拒絕（D-097），不是默默拿掉。"""
    rid = h.insert_report(db, "Wen", DATE, "PENDING", items={"direct_13": 20}, crew=("Wei",))
    db.execute("update yc_v3.accounts set archived = true where name = 'Wei'")
    db.commit()
    wei = _account_id(db, "Wei")
    sign_in(client, db, "Wen")
    before = take_snapshot(db)
    r = edit(client, db, "Wen", rid, [("report_date", DATE), ("direct_13", "2.0"), ("collaborator", str(wei))])
    assert r.status_code == 422 and r.json() == {"outcome": "INVALID", "message": MSG_COLLAB_TEXT}
    assert diff(before, take_snapshot(db)) == {}
