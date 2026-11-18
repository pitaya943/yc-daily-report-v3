"""REV-F03 的細節測試（T-302 補）：scenario 沒寫到的邊界、拒絕案例的三個斷言、D-112、鎖、讀取函式。每個測試只放一個錯誤原因。

比規格更嚴格的地方（逐條列在 PR 說明，D-091）：
- 每個 INVALID／CONFLICT 的拒絕都比對動作前後整個資料庫（含 audit_log）完全不變，規格只寫「資料不變」。
- FORBIDDEN 恰好新增 1 列 ACCESS_DENIED（行為者是被拒絕的人），其他資料表不變（D-095）。
- 沒有變更的儲存（附加相同的自訂工項、移除本來沒有的）什麼都不寫，已確認的回報不退回 PENDING。
- 欄位缺少或重複是 INVALID（沒有字串），不補預設值。
"""
from __future__ import annotations

import threading
import time
from datetime import date
from fractions import Fraction

import pytest
import rev_f01_steps as h
import rev_f03_steps as s
from fastapi.testclient import TestClient

from app.core.db import connect
from app.main import create_app
from app.modules.reports.report_lifecycle import repo as lifecycle_repo
from app.modules.review.crew_split_and_stored_shares import service as shares
from app.modules.review.custom_work_item import service
from tests.steps.common.steps import diff, take_snapshot

DAY = s.DAY
ITEM = s.ITEM
MSG_NO_QUANTITY = "請至少填寫一個工項數量"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def pending(db, *, custom=None, items=None):
    return h.insert_report(db, "Wen", DAY, "PENDING", items={ITEM: 10} if items is None else items, custom=custom)


def confirmed(db, *, custom=None, items=None):
    """CONFIRMED、Wen 與 Wei，目錄工項 direct_13 的份額與（有的話）自訂工項的份額，審核者 Admin2。"""
    rid = h.insert_report(db, "Wen", DAY, "CONFIRMED", items={ITEM: 20} if items is None else items, crew=("Wei",), custom=custom, reviewer="Admin2")
    h.insert_shares(db, rid, ITEM, [("Wen", 10), ("Wei", 10)])
    if custom:
        ids = [h.account_row(db, n)[0] for n in ("Wen", "Wei")]
        with db.cursor() as cur:
            for position, account_id in enumerate(ids):
                cur.execute("insert into yc_v3.report_custom_shares values (%s, %s, %s, %s)", (rid, account_id, position, custom[1] // 2))
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


def post(client, db, who, rid, name, qty, price):
    return s.attach(client, db, who, rid, s.form(name, qty, price))


def audit_types(db, since_id=0):
    with db.cursor() as cur:
        cur.execute("select type, actor_name from yc_v3.audit_log where id > %s order by id", (since_id,))
        rows = cur.fetchall()
    db.rollback()
    return rows


def last_audit_id(db):
    with db.cursor() as cur:
        cur.execute("select coalesce(max(id), 0) from yc_v3.audit_log")
        value = cur.fetchone()[0]
    db.rollback()
    return value


def rejected_and_unchanged(db, response, status, outcome, message, before):
    body = response.json()
    assert (response.status_code, body["outcome"], body["message"]) == (status, outcome, message), response.text
    assert diff(before, take_snapshot(db)) == {}, "拒絕時資料庫在動作前後必須完全相同"


# ───────────────────────── REV-R20：權限 ─────────────────────────


@pytest.mark.parametrize("who", ["Wen", "Wei"])  # 回報的提交者、同組的其他 USER
def test_a_user_is_forbidden_and_only_access_denied_is_written(client, db, who):
    rid = pending(db)
    # 登入寫的 session 不算動作造成的變動：動作之前先登入
    h.ensure_signed_in(client, db, who)
    before = take_snapshot(db)
    response = post(client, db, who, rid, "夜間加班", "2.0", "500")
    assert (response.status_code, response.json()) == (403, {"outcome": "FORBIDDEN", "message": None})
    changes = diff(before, take_snapshot(db))
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1 and changes["audit_log"]["removed"] == []
    assert audit_types(db)[-1] == ("ACCESS_DENIED", who)


def test_permission_comes_before_field_validation(client, db):
    rid = pending(db)
    h.ensure_signed_in(client, db, "Wen")
    response = post(client, db, "Wen", rid, "工" * 101, "-5", "99.5")
    assert response.status_code == 403 and response.json()["outcome"] == "FORBIDDEN"


def test_the_owner_can_attach(client, db):
    rid = pending(db)
    assert post(client, db, "Kuei", rid, "夜間加班", "2.0", "500").status_code == 200
    assert s.custom_row(db, rid)[:3] == ("夜間加班", 20, 500)


def test_an_anonymous_request_is_unauthenticated_and_changes_nothing(client, db):
    rid = pending(db)
    before = take_snapshot(db)
    response = client.post(s.PATH.format(id=rid), data={s.FIELD_NAME: "x", s.FIELD_QTY: "1.0", s.FIELD_PRICE: "1"})
    rejected_and_unchanged(db, response, 401, "UNAUTHENTICATED", None, before)


def test_a_missing_report_is_404_and_changes_nothing(client, db):
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    response = post(client, db, "Admin1", 999999, "夜間加班", "2.0", "500")
    assert response.status_code == 404
    assert diff(before, take_snapshot(db)) == {}


# ───────────────────────── REV-R22：欄位 ─────────────────────────

MSG_NAME = "自訂工項名稱最多 100 個字"
MSG_QTY = "自訂工項數量須為 0 到 999.9，最小單位 0.1"
MSG_PRICE = "自訂工項單價須為 0 或正整數"


@pytest.mark.parametrize(
    ("name", "qty", "price", "message"),
    [
        ("工" * 101, "1.0", "500", MSG_NAME),
        ("搬運", "0.05", "500", MSG_QTY),
        ("搬運", "1000", "500", MSG_QTY),
        ("搬運", "999.95", "500", MSG_QTY),
        ("搬運", "-0.1", "500", MSG_QTY),
        ("搬運", "1,0", "500", MSG_QTY),
        ("搬運", "", "500", MSG_QTY),  # 有名稱時數量必填：空白不是 0
        ("搬運", "１.０", "500", MSG_QTY),  # 全形數字
        ("搬運", "1.0", "99.5", MSG_PRICE),
        ("搬運", "1.0", "-1", MSG_PRICE),
        ("搬運", "1.0", "", MSG_PRICE),  # 有名稱時單價必填
        ("搬運", "1.0", "５００", MSG_PRICE),  # 全形數字
        ("搬運", "1.0", "1e3", MSG_PRICE),
        ("搬運", "1.0", "99999999999", MSG_PRICE),  # 超過儲存的上限（32 位元整數）：INVALID，不是 500
    ],
)
def test_an_invalid_field_is_rejected_with_its_exact_message_and_changes_nothing(client, db, name, qty, price, message):
    rid = pending(db)
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    rejected_and_unchanged(db, post(client, db, "Admin1", rid, name, qty, price), 422, "INVALID", message, before)


@pytest.mark.parametrize(
    ("name", "qty", "price", "stored"),
    [
        ("工" * 100, "1.0", "500", ("工" * 100, 10, 500)),
        ("搬運", "999.9", "500", ("搬運", 9999, 500)),
        ("搬運", "0", "0", ("搬運", 0, 0)),
        ("搬運", "0.1", "1", ("搬運", 1, 1)),
        ("搬運", "1.00", "500", ("搬運", 10, 500)),  # 小數第二位是 0：仍是 0.1 的倍數（與 RPT-R03 相同）
        ("  搬運  ", "1.0", "500", ("搬運", 10, 500)),  # 名稱前後的空白不算字
        ("搬運", " 1.5 ", " 500 ", ("搬運", 15, 500)),
        ("搬運", "1.0", "999999999", ("搬運", 10, 999999999)),
    ],
)
def test_a_valid_item_is_stored_as_tenths_and_whole_ntd(client, db, name, qty, price, stored):
    rid = pending(db)
    assert post(client, db, "Admin1", rid, name, qty, price).status_code == 200
    assert s.custom_row(db, rid)[:3] == stored


@pytest.mark.parametrize(
    "fields",
    [
        [(s.FIELD_QTY, "1.0"), (s.FIELD_PRICE, "500")],  # 沒有名稱欄位：不補成「移除」
        [(s.FIELD_NAME, "搬運"), (s.FIELD_NAME, "搬運2"), (s.FIELD_QTY, "1.0"), (s.FIELD_PRICE, "500")],  # 名稱出現兩次
        [(s.FIELD_NAME, "搬運"), (s.FIELD_PRICE, "500")],  # 缺數量
        [(s.FIELD_NAME, "搬運"), (s.FIELD_QTY, "1.0")],  # 缺單價
        [(s.FIELD_NAME, "搬運"), (s.FIELD_QTY, "1.0"), (s.FIELD_QTY, "2.0"), (s.FIELD_PRICE, "500")],  # 數量出現兩次
    ],
)
def test_a_missing_or_repeated_field_is_invalid_and_changes_nothing(client, db, fields):
    rid = pending(db, custom=("夜間加班", 20, 500))
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    response = s.attach(client, db, "Admin1", rid, fields)
    assert response.status_code == 422 and response.json()["outcome"] == "INVALID"
    assert diff(before, take_snapshot(db)) == {}


# ───────────────────────── REV-R21：清空名稱 ─────────────────────────


@pytest.mark.parametrize(("qty", "price"), [("", ""), ("2.0", "500"), ("not a number", "-3")])
def test_an_empty_name_removes_whatever_the_other_fields_hold(client, db, qty, price):
    rid = pending(db, custom=("夜間加班", 20, 500))
    assert post(client, db, "Admin1", rid, "", qty, price).status_code == 200
    assert s.custom_row(db, rid)[:3] == (None, None, None)


def test_a_whitespace_only_name_removes_the_item(client, db):
    rid = pending(db, custom=("夜間加班", 20, 500))
    assert post(client, db, "Admin1", rid, "   ", "", "").status_code == 200
    assert s.custom_row(db, rid)[:3] == (None, None, None)


def test_removing_writes_one_report_update_row(client, db):
    rid = pending(db, custom=("夜間加班", 20, 500))
    mark = last_audit_id(db)
    assert post(client, db, "Admin1", rid, "", "", "").status_code == 200
    assert audit_types(db, mark) == [("REPORT_UPDATE", "Admin1")]


# ───────────────────────── D-112：至少一個工項 ─────────────────────────


def test_removing_the_only_quantity_is_rejected(client, db):
    rid = pending(db, items={ITEM: 0}, custom=("夜間加班", 20, 500))  # 一般工項全為 0，自訂工項是唯一的數量
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    rejected_and_unchanged(db, post(client, db, "Admin1", rid, "", "", ""), 422, "INVALID", MSG_NO_QUANTITY, before)


def test_removing_with_a_catalogue_quantity_succeeds(client, db):
    rid = pending(db, items={ITEM: 10}, custom=("夜間加班", 20, 500))
    assert post(client, db, "Admin1", rid, "", "", "").status_code == 200
    assert s.custom_row(db, rid)[:3] == (None, None, None)


def test_replacing_the_only_quantity_with_zero_is_rejected(client, db):
    rid = pending(db, items={ITEM: 0}, custom=("夜間加班", 20, 500))
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    rejected_and_unchanged(db, post(client, db, "Admin1", rid, "搬運", "0", "300"), 422, "INVALID", MSG_NO_QUANTITY, before)


def test_replacing_the_only_quantity_with_a_positive_one_succeeds(client, db):
    rid = pending(db, items={ITEM: 0}, custom=("夜間加班", 20, 500))
    assert post(client, db, "Admin1", rid, "搬運", "0.1", "300").status_code == 200
    assert s.custom_row(db, rid)[:3] == ("搬運", 1, 300)


def test_a_rejected_removal_leaves_a_confirmed_report_confirmed_with_its_shares(client, db):
    rid = confirmed(db, items={ITEM: 0}, custom=("夜間加班", 20, 500))
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    rejected_and_unchanged(db, post(client, db, "Admin1", rid, "", "", ""), 422, "INVALID", MSG_NO_QUANTITY, before)
    assert s.custom_row(db, rid)[3] == "CONFIRMED" and counts(db, rid)[1] == 2


def test_the_quantity_check_calls_the_shared_function(client, db, monkeypatch):
    """判斷只有一份：呼叫 T-201 的 `require_a_quantity`，不另寫（完成條件 10）。"""
    calls = []
    original = service.submit.require_a_quantity
    monkeypatch.setattr(service.submit, "require_a_quantity", lambda items, custom: (calls.append((dict(items), custom)), original(items, custom))[1])
    rid = pending(db, items={ITEM: 10})
    assert post(client, db, "Admin1", rid, "夜間加班", "2.0", "500").status_code == 200
    assert calls == [({ITEM: 10}, 20)]


# ───────────────────────── REV-R24：不是 PENDING ─────────────────────────


@pytest.mark.parametrize(
    ("custom", "name", "qty", "price"),
    [
        (None, "夜間加班", "2.0", "500"),  # 附加
        (("夜間加班", 20, 500), "搬運", "1.0", "300"),  # 取代
        (("夜間加班", 20, 500), "", "", ""),  # 移除
    ],
)
def test_a_change_on_a_confirmed_report_returns_it_to_pending_and_discards_its_shares(client, db, custom, name, qty, price):
    rid = confirmed(db, custom=custom)
    assert counts(db, rid)[0] == 2
    mark = last_audit_id(db)
    assert post(client, db, "Admin1", rid, name, qty, price).status_code == 200
    assert h.report_row(db, rid)[:3:2] == ("PENDING", None)  # (狀態, 審核時間)
    assert h.report_row(db, rid)[1] is None  # 審核者
    assert counts(db, rid) == (0, 0)  # 目錄工項與自訂工項的份額都作廢
    assert audit_types(db, mark) == [("REPORT_UNCONFIRM", "Admin1"), ("REPORT_UPDATE", "Admin1")]


def test_a_change_on_a_rejected_report_returns_it_to_pending_without_an_unconfirm_row(client, db):
    rid = h.insert_report(db, "Wen", DAY, "REJECTED", items={ITEM: 10}, reviewer="Admin2")
    mark = last_audit_id(db)
    assert post(client, db, "Admin1", rid, "夜間加班", "2.0", "500").status_code == 200
    assert h.report_row(db, rid)[0] == "PENDING" and h.report_row(db, rid)[1] is None
    assert audit_types(db, mark) == [("REPORT_UPDATE", "Admin1")]


def test_a_change_on_a_pending_report_keeps_it_pending_and_writes_one_row(client, db):
    rid = pending(db)
    mark = last_audit_id(db)
    assert post(client, db, "Admin1", rid, "夜間加班", "2.0", "500").status_code == 200
    assert audit_types(db, mark) == [("REPORT_UPDATE", "Admin1")]


def test_the_catalogue_items_and_crew_of_the_report_are_untouched(client, db):
    rid = confirmed(db, custom=("夜間加班", 20, 500))
    with db.cursor() as cur:
        cur.execute("select item_code, tenths from yc_v3.report_items where report_id = %s order by 1", (rid,))
        items = cur.fetchall()
        cur.execute("select account_id from yc_v3.report_crew where report_id = %s order by position", (rid,))
        crew = cur.fetchall()
    db.rollback()
    assert post(client, db, "Admin1", rid, "搬運", "1.0", "300").status_code == 200
    with db.cursor() as cur:
        cur.execute("select item_code, tenths from yc_v3.report_items where report_id = %s order by 1", (rid,))
        assert cur.fetchall() == items
        cur.execute("select account_id from yc_v3.report_crew where report_id = %s order by position", (rid,))
        assert cur.fetchall() == crew
    db.rollback()


@pytest.mark.parametrize(("custom", "name", "qty", "price"), [(("夜間加班", 20, 500), "夜間加班", "2.0", "500"), (None, "", "", "")])
def test_saving_no_change_writes_nothing_and_keeps_a_confirmed_report_confirmed(client, db, custom, name, qty, price):
    rid = confirmed(db, custom=custom)
    h.ensure_signed_in(client, db, "Admin1")
    before = take_snapshot(db)
    response = post(client, db, "Admin1", rid, name, qty, price)
    assert response.status_code == 200
    assert diff(before, take_snapshot(db)) == {}
    assert s.custom_row(db, rid)[3] == "CONFIRMED"


# ───────────────────────── 鎖（完成條件 8） ─────────────────────────


def test_it_takes_the_same_row_lock_as_edit_and_review(client, db, monkeypatch):
    locked = []
    original = lifecycle_repo.lock_report

    def spy(conn, report_id):
        locked.append(report_id)
        return original(conn, report_id)

    monkeypatch.setattr(service.lifecycle_repo, "lock_report", spy)
    rid = pending(db)
    assert post(client, db, "Admin1", rid, "夜間加班", "2.0", "500").status_code == 200
    assert locked == [rid]


def test_discarding_the_review_uses_the_t301_function(client, db, monkeypatch):
    discarded = []
    original = lifecycle_repo.discard_review
    monkeypatch.setattr(service.lifecycle_repo, "discard_review", lambda conn, rid: (discarded.append(rid), original(conn, rid))[1])
    rid = confirmed(db)
    assert post(client, db, "Admin1", rid, "夜間加班", "2.0", "500").status_code == 200
    assert discarded == [rid]


def test_a_request_waits_for_a_concurrent_holder_of_the_report_lock(client, db):
    """另一個 transaction 持有這張回報的列鎖時（例如管理員正在確認它），這個請求要等到它結束，而且之後看見的是新的狀態。"""
    rid = pending(db)
    h.ensure_signed_in(client, db, "Admin1")
    token = h.csrf_token(db, "Admin1")
    holder = connect()
    holder.execute("select id from yc_v3.reports where id = %s for update", (rid,))
    done: dict = {}

    def worker():
        c = TestClient(client.app, raise_server_exceptions=False)
        c.cookies.set(h.SESSION_COOKIE, client.cookies.get(h.SESSION_COOKIE))
        done["response"] = c.post(s.PATH.format(id=rid), **h.form_request(s.form("夜間加班", "2.0", "500"), token))

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(1.0)
    assert thread.is_alive() and "response" not in done, "持有列鎖時，請求不該先完成"
    holder.execute("update yc_v3.reports set status = 'REJECTED' where id = %s", (rid,))  # 鎖住的那邊先把狀態改了
    holder.commit()
    holder.close()
    thread.join(timeout=30)
    assert done["response"].status_code == 200
    assert h.report_row(db, rid)[0] == "PENDING", "等到鎖之後看見的是 REJECTED，所以要退回 PENDING 並寫入"


# ───────────────────────── 頁面 ─────────────────────────


def test_the_page_is_prefilled_with_the_current_item_for_an_admin(client, db):
    rid = pending(db, custom=("夜間加班", 25, 500))
    h.ensure_signed_in(client, db, "Admin1")
    page = client.get(s.PATH.format(id=rid))
    assert page.status_code == 200
    assert 'value="夜間加班"' in page.text and 'value="2.5"' in page.text and 'value="500"' in page.text
    assert f'hx-post="/review/reports/{rid}/custom-item"' in page.text


def test_the_page_is_forbidden_for_a_user(client, db):
    rid = pending(db)
    h.ensure_signed_in(client, db, "Wen")
    assert client.get(s.PATH.format(id=rid)).status_code == 403


# ───────────────────────── 讀取函式（D-111、REV-R23） ─────────────────────────


def money(db, d_from=date(2026, 11, 1), d_to=date(2026, 11, 30)):
    result = shares.confirmed_custom_money(db, d_from, d_to)
    db.rollback()
    return result


def with_custom_shares(db, status, day, custom, crew_shares):
    """crew_shares = [(人名, tenths)]：提交者是第一個。"""
    rid = h.insert_report(db, crew_shares[0][0], day, status, items={ITEM: 10}, crew=tuple(n for n, _ in crew_shares[1:]), custom=custom, reviewer="Admin2")
    ids = [h.account_row(db, who)[0] for who, _ in crew_shares]  # account_row 會 rollback：先查，再開始寫
    with db.cursor() as cur:
        for position, ((_, tenths), account_id) in enumerate(zip(crew_shares, ids)):
            cur.execute("insert into yc_v3.report_custom_shares values (%s, %s, %s, %s)", (rid, account_id, position, tenths))
    db.commit()
    return rid


def test_money_keeps_the_fraction_instead_of_rounding(db):
    with_custom_shares(db, "CONFIRMED", DAY, ("加班", 3, 55), [("Wen", 2), ("Wei", 1)])
    wen, wei = h.account_row(db, "Wen")[0], h.account_row(db, "Wei")[0]
    assert money(db) == {wen: Fraction(11), wei: Fraction(11, 2)}  # 0.2 × 55 = 11；0.1 × 55 = 5.5（AD-2：gross 才 half-up）


def test_money_uses_each_reports_own_price_and_sums_per_person(db):
    with_custom_shares(db, "CONFIRMED", "2026-11-09", ("加班", 10, 100), [("Wen", 10)])
    with_custom_shares(db, "CONFIRMED", "2026-11-10", ("搬運", 20, 30), [("Wen", 20)])
    assert money(db) == {h.account_row(db, "Wen")[0]: Fraction(100 + 60)}


@pytest.mark.parametrize("status", ["PENDING", "REJECTED"])
def test_money_counts_only_confirmed_reports(db, status):
    with_custom_shares(db, status, DAY, ("加班", 10, 100), [("Wen", 10)])
    assert money(db) == {}


def test_money_includes_both_ends_of_the_period_and_excludes_outside(db):
    with_custom_shares(db, "CONFIRMED", "2026-11-05", ("加班", 10, 100), [("Wen", 10)])
    with_custom_shares(db, "CONFIRMED", "2026-11-06", ("加班", 10, 100), [("Wei", 10)])
    with_custom_shares(db, "CONFIRMED", "2026-11-20", ("加班", 10, 100), [("Wan", 10)])
    with_custom_shares(db, "CONFIRMED", "2026-11-21", ("加班", 10, 100), [("Nan", 10)])
    result = money(db, date(2026, 11, 6), date(2026, 11, 20))
    assert set(result) == {h.account_row(db, n)[0] for n in ("Wei", "Wan")}


def test_a_zero_share_still_appears_with_zero_money(db):
    with_custom_shares(db, "CONFIRMED", DAY, ("加班", 1, 100), [("Wen", 1), ("Wei", 0)])
    assert money(db)[h.account_row(db, "Wei")[0]] == 0


def test_a_report_without_a_custom_item_contributes_nothing(db):
    confirmed(db)
    assert money(db) == {}


def test_attaching_to_a_confirmed_report_removes_its_money_until_it_is_confirmed_again(client, db):
    rid = confirmed(db, custom=("夜間加班", 20, 500))
    assert sum(money(db).values()) == 1000
    assert post(client, db, "Admin1", rid, "搬運", "1.0", "300").status_code == 200
    assert money(db) == {}


def test_confirmed_quantities_still_has_no_custom_item(db):
    """D-111：既有函式的行為不變——自訂工項的金額只在新函式。"""
    confirmed(db, custom=("夜間加班", 20, 500))
    quantities = shares.confirmed_quantities(db, date(2026, 11, 1), date(2026, 11, 30))
    db.rollback()
    assert all(set(items) == {ITEM} for items in quantities.values())
