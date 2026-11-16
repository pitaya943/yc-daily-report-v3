"""RPT-F03 的細節測試：scenario 沒有逐一涵蓋的邊界（AGENTS.md #5、#6）。

不是 Gherkin：篩選值的驗證矩陣（四個頁面與匯出）、權限、可見範圍、匯出檔的內容與安全。
"""
from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import openpyxl
import pytest

from app.modules.reports.history_and_export import service
from rpt_f03_steps import (
    ADMIN_HISTORY,
    CUSTOM_ITEM,
    STATUS_WORDING,
    USER_HISTORY,
    ensure_signed_in,
    get,
    insert_report,
    page_rows,
    read_xlsx,
    union_names,
)
from tests.steps.common.steps import diff, take_snapshot

MESSAGE = "請輸入有效的篩選條件"
ADMIN_PAGES = [ADMIN_HISTORY["ordinary"], ADMIN_HISTORY["big-meter"]]


def _act(client, db, who, path, query=None):
    """登入後送出請求，回傳（回應, 動作前後的資料庫差異）。"""
    ensure_signed_in(client, db, who)
    before = take_snapshot(db)
    response = get(client, path, query)
    return response, diff(before, take_snapshot(db))


def _assert_invalid(response, changes):
    assert response.status_code == 422, response.text[:200]
    assert response.json() == {"outcome": "INVALID", "message": MESSAGE}
    assert changes == {}, f"被拒絕的篩選不得寫入任何資料：{changes}"


# ───────────────────────── 篩選值的驗證（RPT-R23）─────────────────────────

BAD_VALUES = [
    ("date_from", "2026-13-40"), ("date_from", "2026-02-30"), ("date_from", "2026-00-10"), ("date_from", "20261110"),
    ("date_from", "2026-1-5"), ("date_from", " 2026-11-10"), ("date_from", "2026-11-10 "), ("date_from", "２０２６-１１-１０"),
    ("date_from", "abc"), ("date_to", "2026-13-40"), ("date_to", "2026-11-31"), ("date_to", "2026/11/10"),
    ("has_custom", "0"), ("has_custom", "true"), ("has_custom", "2"),
    ("status", "PENDING"), ("unknown", "1"),
]
ADMIN_BAD_VALUES = [
    ("zone", "EAST"), ("zone", "west"), ("zone", " WEST"), ("zone", "BIG_METER"), ("zone", "WEST "),
    ("account", "Nobody"), ("account", "wen"), ("account", " Wen"), ("account", "Admin1"), ("account", "Kuei"),
]


@pytest.mark.parametrize("path", [USER_HISTORY, *ADMIN_PAGES])
@pytest.mark.parametrize("key, value", BAD_VALUES)
def test_invalid_filter_values_are_rejected_on_every_page(client, db, path, key, value):
    who = "Wen" if path == USER_HISTORY else "Admin1"
    insert_report(db, "Wen", "2026-11-10")
    _assert_invalid(*_act(client, db, who, path, {key: value}))


@pytest.mark.parametrize("path", ADMIN_PAGES)
@pytest.mark.parametrize("key, value", ADMIN_BAD_VALUES)
def test_invalid_admin_filter_values(client, db, path, key, value):
    _assert_invalid(*_act(client, db, "Admin1", path, {key: value}))


@pytest.mark.parametrize("key", ["zone", "account"])
def test_a_user_cannot_use_the_administrator_filters(client, db, key):
    _assert_invalid(*_act(client, db, "Wen", USER_HISTORY, {key: "WEST" if key == "zone" else "Wen"}))


def test_a_reversed_date_range_is_invalid(client, db):
    _assert_invalid(*_act(client, db, "Admin1", ADMIN_PAGES[0], {"date_from": "2026-11-13", "date_to": "2026-11-12"}))


def test_a_repeated_parameter_is_invalid_not_last_one_wins(client, db):
    ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    response = client.get(ADMIN_PAGES[0] + "?date_from=2026-11-10&date_from=2026-11-11")
    _assert_invalid(response, diff(before, take_snapshot(db)))


def test_one_bad_value_rejects_the_whole_request_even_next_to_good_ones(client, db):
    _assert_invalid(*_act(client, db, "Admin1", ADMIN_PAGES[0], {"date_from": "2026-11-10", "zone": "EAST"}))


@pytest.mark.parametrize("path", ["/reports/history/export", "/review/history/ordinary/export", "/review/history/big-meter/export"])
def test_an_invalid_filter_rejects_the_export_and_writes_no_audit_row(client, db, path):
    who = "Wen" if path.startswith("/reports") else "Admin1"
    _assert_invalid(*_act(client, db, who, path, {"date_from": "2026-13-40"}))


def test_blank_values_mean_no_filter(client, db):
    insert_report(db, "Wen", "2026-11-10")
    insert_report(db, "Nan", "2026-11-12")
    response, changes = _act(client, db, "Admin1", ADMIN_PAGES[0], {"date_from": "", "date_to": "", "zone": "", "account": "", "has_custom": ""})
    assert len(page_rows(response)) == 2 and changes == {}


# ───────────────────────── 權限 ─────────────────────────


@pytest.mark.parametrize("path", [*ADMIN_PAGES, "/review/history/ordinary/export", "/review/history/big-meter/export"])
def test_a_user_is_turned_away_from_the_administrator_pages(client, db, path):
    response, changes = _act(client, db, "Wen", path)
    assert response.status_code == 403 and response.json() == {"outcome": "FORBIDDEN", "message": None}
    # 只多一列 ACCESS_DENIED，而且 actor 是被拒絕的那個人
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1 and "ACCESS_DENIED" in changes["audit_log"]["added"][0]
    assert "Wen" in changes["audit_log"]["added"][0]


@pytest.mark.parametrize("who", ["Admin1", "Kuei"])
@pytest.mark.parametrize("path", [USER_HISTORY, USER_HISTORY + "/export"])
def test_administrators_and_the_owner_have_no_personal_history(client, db, who, path):
    response, changes = _act(client, db, who, path)
    assert response.status_code == 403
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1


def test_the_forbidden_check_comes_before_filter_validation(client, db):
    response, _ = _act(client, db, "Wen", ADMIN_PAGES[0], {"zone": "EAST"})
    assert response.status_code == 403


def test_the_owner_can_open_the_administrator_pages(client, db):
    insert_report(db, "Wen", "2026-11-10")
    response, changes = _act(client, db, "Kuei", ADMIN_PAGES[0])
    assert len(page_rows(response)) == 1 and changes == {}


@pytest.mark.parametrize("path", [USER_HISTORY, USER_HISTORY + "/export", *ADMIN_PAGES, "/review/history/ordinary/export"])
def test_signed_out_requests_get_401_and_nothing_is_written(client, db, path):
    before = take_snapshot(db)
    response = client.get(path)
    assert response.status_code == 401 and response.json() == {"outcome": "UNAUTHENTICATED", "message": None}
    assert diff(before, take_snapshot(db)) == {}


def test_opening_a_page_writes_nothing(client, db):
    insert_report(db, "Wen", "2026-11-10")
    for who, path in (("Wen", USER_HISTORY), ("Admin1", ADMIN_PAGES[0]), ("Admin1", ADMIN_PAGES[1])):
        response, changes = _act(client, db, who, path)
        assert response.status_code == 200 and changes == {}, (who, path, changes)


# ───────────────────────── 可見範圍與篩選 ─────────────────────────


def test_a_user_never_sees_other_peoples_reports(client, db):
    mine = insert_report(db, "Wen", "2026-11-10")
    collab = insert_report(db, "Wei", "2026-11-11", crew=("Wen",))
    insert_report(db, "Wei", "2026-11-12")
    insert_report(db, "Wan", "2026-11-12", crew=("Wei",))
    response, _ = _act(client, db, "Wen", USER_HISTORY)
    assert [r["id"] for r in page_rows(response)] == [collab, mine]


def test_same_day_reports_are_listed_newest_id_first(client, db):
    first = insert_report(db, "Wen", "2026-11-10")
    second = insert_report(db, "Wen", "2026-11-10")
    response, _ = _act(client, db, "Wen", USER_HISTORY)
    assert [r["id"] for r in page_rows(response)] == [second, first]


def test_date_range_bounds_are_inclusive(client, db):
    ids = {d: insert_report(db, "Wen", d) for d in ("2026-11-09", "2026-11-10", "2026-11-12", "2026-11-13")}
    response, _ = _act(client, db, "Wen", USER_HISTORY, {"date_from": "2026-11-10", "date_to": "2026-11-12"})
    assert [r["id"] for r in page_rows(response)] == [ids["2026-11-12"], ids["2026-11-10"]]


def test_the_two_administrator_pages_partition_the_reports(client, db):
    west, south, big = insert_report(db, "Wen", "2026-11-10"), insert_report(db, "Nan", "2026-11-10"), insert_report(db, "Big", "2026-11-10")
    ordinary, _ = _act(client, db, "Admin1", ADMIN_PAGES[0])
    big_page, _ = _act(client, db, "Admin1", ADMIN_PAGES[1])
    assert {r["id"] for r in page_rows(ordinary)} == {west, south}
    assert {r["id"] for r in page_rows(big_page)} == {big}


def test_the_filters_work_on_the_big_meter_page_too(client, db):
    with_custom = insert_report(db, "Big", "2026-11-12", custom=CUSTOM_ITEM)
    insert_report(db, "Big", "2026-11-10")
    for query in ({"has_custom": "1"}, {"zone": "WEST"}, {"account": "Big"}, {"date_from": "2026-11-11"}):
        response, _ = _act(client, db, "Admin1", ADMIN_PAGES[1], query)
        assert with_custom in [r["id"] for r in page_rows(response)], query
    response, _ = _act(client, db, "Admin1", ADMIN_PAGES[1], {"zone": "SOUTH"})
    assert page_rows(response) == []


def test_filters_combine_with_and(client, db):
    insert_report(db, "Wen", "2026-11-10", custom=CUSTOM_ITEM)
    keep = insert_report(db, "Wen", "2026-11-12", custom=CUSTOM_ITEM)
    insert_report(db, "Wen", "2026-11-12")
    insert_report(db, "Nan", "2026-11-12", custom=CUSTOM_ITEM)
    response, _ = _act(client, db, "Admin1", ADMIN_PAGES[0], {"zone": "WEST", "has_custom": "1", "date_from": "2026-11-11", "account": "Wen"})
    assert [r["id"] for r in page_rows(response)] == [keep]


def test_an_archived_account_can_still_be_filtered(client, db):
    old = insert_report(db, "Old", "2026-11-10")
    response, _ = _act(client, db, "Admin1", ADMIN_PAGES[0], {"account": "Old"})
    assert [r["id"] for r in page_rows(response)] == [old]


def test_status_wording_matches_the_spec_for_every_status():
    assert STATUS_WORDING == service.STATUS_WORDING == {"PENDING": "未確認", "CONFIRMED": "已確認", "REJECTED": "已駁回"}


def test_user_content_in_the_page_is_escaped(client, db):
    insert_report(db, "Wen", "2026-11-10", custom=("<script>alert(1)</script>", 10, 5))
    response, _ = _act(client, db, "Wen", USER_HISTORY)
    assert "<script>alert(1)</script>" not in response.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_the_export_link_carries_exactly_the_validated_filter(client, db):
    response, _ = _act(client, db, "Admin1", ADMIN_PAGES[0], {"zone": "SOUTH", "date_from": "2026-11-01", "has_custom": "1"})
    assert 'href="/review/history/ordinary/export?date_from=2026-11-01&amp;zone=SOUTH&amp;has_custom=1"' in response.text


# ───────────────────────── 匯出檔 ─────────────────────────


def _export(client, db, who, path, query=None):
    response, changes = _act(client, db, who, path, query)
    header, data = read_xlsx(response)
    return header, data, changes


def test_export_rows_are_the_filtered_rows_in_page_order(client, db):
    insert_report(db, "Wen", "2026-11-10")
    insert_report(db, "Nan", "2026-11-12", custom=CUSTOM_ITEM)
    insert_report(db, "Wei", "2026-11-13", crew=("Wen",))
    _, data, _ = _export(client, db, "Admin1", "/review/history/ordinary/export", {"date_from": "2026-11-11"})
    assert [(r[0], r[1]) for r in data] == [("2026-11-13", "Wei"), ("2026-11-12", "Nan")]


def test_export_cells_hold_quantities_custom_item_and_status(client, db):
    insert_report(db, "Wen", "2026-11-10", status="CONFIRMED", items={"direct_13": 23, "app_item": 1}, custom=CUSTOM_ITEM)
    header, data, _ = _export(client, db, "Admin1", "/review/history/ordinary/export")
    row = dict(zip(header, data[0]))
    assert Decimal(str(row["直總-13"])) == Decimal("2.3") and Decimal(str(row["APP"])) == Decimal("0.1")
    assert row["直總-20"] is None, "沒填的工項是空白，不補 0"
    assert row["自訂工項"] == "Custom pipe 1.5 只 × 100" and row["確認狀態"] == "已確認"


def test_an_item_that_two_catalogues_share_is_one_column(client, db):
    wen = insert_report(db, "Wen", "2026-11-10", items={"dsv_13": 10})  # WEST 的代碼
    nan = insert_report(db, "Nan", "2026-11-10", items={"s_dsv_13": 20})  # SOUTH 的代碼，同一個顯示名稱
    assert wen != nan
    header, data, _ = _export(client, db, "Admin1", "/review/history/ordinary/export")
    assert header.count("直總-換由令(含表)-13") == 1
    by_account = {r[1]: dict(zip(header, r)) for r in data}
    assert Decimal(str(by_account["Wen"]["直總-換由令(含表)-13"])) == 1 and Decimal(str(by_account["Nan"]["直總-換由令(含表)-13"])) == 2


def test_the_big_meter_export_has_only_the_big_meter_columns(client, db):
    insert_report(db, "Big", "2026-11-10", items={"bm_50_down": 5})
    header, data, _ = _export(client, db, "Admin1", "/review/history/big-meter/export")
    assert header == ["日期", "帳戶", *union_names("BIG_METER"), "自訂工項", "確認狀態"] and len(data) == 1


def test_a_user_export_has_the_users_own_catalogue_columns_and_only_visible_rows(client, db):
    insert_report(db, "Wen", "2026-11-10", items={"direct_13": 10})
    insert_report(db, "Wei", "2026-11-12", crew=("Wen",))
    insert_report(db, "Wei", "2026-11-13")
    header, data, changes = _export(client, db, "Wen", "/reports/history/export")
    assert header == ["日期", "帳戶", *union_names("WEST"), "自訂工項", "確認狀態"]
    assert [(r[0], r[1]) for r in data] == [("2026-11-12", "Wei"), ("2026-11-10", "Wen")]
    assert len(changes["audit_log"]["added"]) == 1


def test_a_user_export_keeps_items_of_an_older_catalogue(client, db):
    """帳戶換過區域後，舊回報（SOUTH 工項組）的工項不能在匯出裡消失。"""
    insert_report(db, "Wen", "2026-11-10", items={"s_orig_13": 30})
    with db.cursor() as cur:
        cur.execute("update yc_v3.reports set catalogue = 'SOUTH'")
    db.commit()
    header, data, _ = _export(client, db, "Wen", "/reports/history/export")
    assert "原改-13" in header and "原改" in header
    assert Decimal(str(dict(zip(header, data[0]))["原改-13"])) == 3


def test_the_export_audit_row_names_the_actor_and_the_row_count(client, db):
    insert_report(db, "Wen", "2026-11-10")
    _, _, changes = _export(client, db, "Admin1", "/review/history/ordinary/export", {"zone": "WEST"})
    (row,) = changes["audit_log"]["added"]
    assert "EXPORT" in row and "Admin1" in row and "1 列" in row and "zone=WEST" in row
    assert set(changes) == {"audit_log"}


def test_text_cells_are_never_formulas(client, db):
    """帳戶與自訂工項名稱是使用者輸入；以 `=` 開頭不得被存成公式（試算表注入）。"""
    insert_report(db, "Wen", "2026-11-10", custom=("=1+1", 10, 5))
    response, _ = _act(client, db, "Admin1", "/review/history/ordinary/export")
    ws = openpyxl.load_workbook(io.BytesIO(response.content)).active
    cells = [c for row in ws.iter_rows() for c in row if isinstance(c.value, str) and c.value.startswith("=")]
    assert len(cells) == 1 and cells[0].data_type == "s", [(c.coordinate, c.data_type) for c in cells]
    book = zipfile.ZipFile(io.BytesIO(response.content))
    sheets = [book.read(n).decode("utf-8", "replace") for n in book.namelist() if n.startswith("xl/worksheets/")]
    assert sheets and all("<f>" not in xml for xml in sheets), "工作表裡不得有公式節點"
