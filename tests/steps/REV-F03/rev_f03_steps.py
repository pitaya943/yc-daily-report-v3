"""REV-F03 自訂工項的步驟（REV-R20～R24；D-086、D-111、D-112、D-118 的路徑）。

設計：
- 動作走真的 HTTP：`POST /review/reports/{id}/custom-item`，表單欄位 `custom_name`、`custom_quantity`、`custom_price`
  （帶 session cookie 與 `X-CSRF-Token`，D-080）。一律經 `recorder.perform`。
- Given 直接寫資料庫（輔助函式來自 REV-F01 的步驟檔，見 conftest.py）。
- **回報要先有一個數量 > 0 的一般工項**（D-112）：否則「移除自訂工項」會因為「至少一個工項」被拒，
  REV-R21 的 Remove 與 REV-R22 的各列就不是在測它們自己的規則。
- 共用步驟（拒絕、稽核、登入）來自 tests/steps/common/，不重新定義（pitfall #26）。
  `audit rows "…" and "…" are written` 是 T-301 為 RPT-R12 定義的（RPT-F02 的步驟檔），REV-R24 直接用。
  `the outcome is <outcome> with message "<message>"` 是 T-305（D-117 S1）的共用步驟，這裡**不**定義。
- 本檔定義的步驟文字（全域註冊，新增前已 `grep -rn` 過同文字）：
  `a PENDING report R1 by "<name>"`、`R1 has custom item "<name>", <qty>, <price>`（Given 與 Then 各一，裝飾器不同）、
  `a CONFIRMED report R1 with stored shares`、`"<admin>" attaches custom item …`、`"<admin>" attaches a custom item to R1`、
  `"<admin>" saves the custom item of R1 with an empty name`、`"<admin>" attaches a custom item with name …, quantity …, price …`、
  `R1 has exactly one custom item …`、`R1 has no custom item`、`R1 is PENDING and has no stored shares`、
  `a CONFIRMED report with crew "<crew>" and custom item quantity <qty> at price <price>`、
  `custom-item money is <n> for "<a>" and <m> for "<b>"`。
"""
from __future__ import annotations

from datetime import date

import pytest
import rev_f01_steps as h
from pytest_bdd import given, parsers, then, when

from tests.steps.common.outcome import *  # noqa: F401,F403
from tests.steps.common.session import *  # noqa: F401,F403
from tests.steps.common.steps import *  # noqa: F401,F403

DAY = "2026-11-10"  # 回報日期：背景的「今天」往前 5 天；REV-F02 的「計算薪資」期間（11-06～11-20）包含它
ITEM = h.ITEM  # direct_13：WEST 的一般工項
PATH = "/review/reports/{id}/custom-item"
FIELD_NAME, FIELD_QTY, FIELD_PRICE = "custom_name", "custom_quantity", "custom_price"


@pytest.fixture
def rev3() -> dict:
    """scenario 的狀態：`R1` 是那張回報的 id。"""
    return {}


def custom_row(db, report_id: int) -> tuple:
    """(自訂工項名稱, tenths, 單價, 狀態)。"""
    with db.cursor() as cur:
        cur.execute("select custom_name, custom_tenths, custom_price, status from yc_v3.reports where id = %s", (report_id,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"回報 #{report_id} 不存在"
    return row


def attach(client, db, name: str, report_id: int, fields: list[tuple[str, str]]):
    h.ensure_signed_in(client, db, name)
    return h.post(client, db, name, PATH.format(id=report_id), fields)


def form(custom_name: str, quantity: str, price: str) -> list[tuple[str, str]]:
    return [(FIELD_NAME, custom_name), (FIELD_QTY, quantity), (FIELD_PRICE, price)]


def _ensure_report(db, rev3: dict) -> int:
    """沒有 Given 的 scenario（REV-R22）自己先放一張 PENDING 的回報：有一個數量 > 0 的一般工項。"""
    if "R1" not in rev3:
        rev3["R1"] = h.insert_report(db, "Wen", DAY, "PENDING", items={ITEM: 10})
    return rev3["R1"]


# ───────────────────────── Given ─────────────────────────


@given(parsers.re(r'a PENDING report R1 by "(?P<name>[^"]+)"$'))
def _pending_r1_by(db, rev3, name):
    rev3["R1"] = h.insert_report(db, name, DAY, "PENDING", items={ITEM: 10})


@given(parsers.re(r'R1 has custom item "(?P<name>[^"]+)", (?P<qty>[0-9.]+), (?P<price>[0-9]+)$'))
def _r1_has_custom_item(db, rev3, name, qty, price):
    rev3["R1"] = h.insert_report(db, "Wen", DAY, "PENDING", items={ITEM: 10}, custom=(name, h.parse_tenths(qty), int(price)))


@given(parsers.re(r"a CONFIRMED report R1 with stored shares$"))
def _confirmed_r1_with_shares(db, rev3):
    """Wen、Wei、Wan 共同作業，direct_13 = 7.0，份額 2.4、2.3、2.3；沒有自訂工項。審核者 Admin2。"""
    rid = h.insert_report(db, "Wen", DAY, "CONFIRMED", items={ITEM: 70}, crew=("Wei", "Wan"), reviewer="Admin2")
    h.insert_shares(db, rid, ITEM, [("Wen", 24), ("Wei", 23), ("Wan", 23)])
    rev3["R1"] = rid


@given(parsers.re(r'a CONFIRMED report with crew "(?P<crew>[^"]+)" and custom item quantity (?P<qty>[0-9.]+) at price (?P<price>[0-9]+)$'))
def _confirmed_with_custom(db, rev3, crew, qty, price):
    """已確認、小組 crew、自訂工項 qty × price；自訂工項的份額依 REV-R10 的規則存好（0.3 分給兩人 = 0.2、0.1）。"""
    from app.domain.split import split

    members = [m.strip() for m in crew.split(",")]
    tenths = h.parse_tenths(qty)
    rid = h.insert_report(
        db, members[0], DAY, "CONFIRMED", items={ITEM: 10}, crew=tuple(members[1:]), custom=("Special work", tenths, int(price)), reviewer="Admin2"
    )
    ids = [h.account_row(db, who)[0] for who in members]
    with db.cursor() as cur:
        for position, (account_id, share) in enumerate(zip(ids, split(tenths, len(ids)))):
            cur.execute(
                "insert into yc_v3.report_custom_shares(report_id, account_id, position, tenths) values (%s, %s, %s, %s)",
                (rid, account_id, position, share),
            )
    db.commit()
    rev3["R1"] = rid


# ───────────────────────── When ─────────────────────────


@when(parsers.re(r'"(?P<admin>[^"]+)" attaches custom item "(?P<name>[^"]+)" with quantity (?P<qty>[0-9.]+) and unit price (?P<price>[0-9]+) to R1$'))
def _attaches_item(recorder, client, db, rev3, admin, name, qty, price):
    h.ensure_signed_in(client, db, admin)
    recorder.perform(lambda: attach(client, db, admin, rev3["R1"], form(name, qty, price)))


@when(parsers.re(r'"(?P<who>[^"]+)" attaches a custom item to R1$'))
def _attaches_a_custom_item(recorder, client, db, rev3, who):
    """內容固定為合法的值：被拒絕的原因只能是角色（REV-R20）或回報的狀態（REV-R24）。"""
    h.ensure_signed_in(client, db, who)
    recorder.perform(lambda: attach(client, db, who, rev3["R1"], form("夜間加班", "2.0", "500")))


@when(parsers.re(r'"(?P<admin>[^"]+)" saves the custom item of R1 with an empty name$'))
def _saves_with_empty_name(recorder, client, db, rev3, admin):
    h.ensure_signed_in(client, db, admin)
    recorder.perform(lambda: attach(client, db, admin, rev3["R1"], form("", "", "")))


def name_from_example(token: str) -> str:
    """REV-R22 的例子欄：`100 characters`／`101 characters` 是長度，`"搬運"` 是字面值（含引號）。
    長度用全形字（每字 3 bytes）：規格說「字」，用 ASCII 會讓「算位元組」的實作也通過。"""
    token = token.strip()
    if token.endswith(" characters"):
        return "工" * int(token.split()[0])
    assert token.startswith('"') and token.endswith('"'), f"例子欄的名稱應是 `N characters` 或帶引號的字串：{token}"
    return token[1:-1]


@when(parsers.re(r'"(?P<admin>[^"]+)" attaches a custom item with name (?P<name>.+), quantity "(?P<qty>[^"]*)", price "(?P<price>[^"]*)"$'))
def _attaches_with_example_values(recorder, client, db, rev3, admin, name, qty, price):
    rid = _ensure_report(db, rev3)
    h.ensure_signed_in(client, db, admin)
    fields = form(name_from_example(name), qty, price)
    recorder.perform(lambda: attach(client, db, admin, rid, fields))


# ───────────────────────── Then ─────────────────────────


@then(parsers.re(r'R1 has custom item "(?P<name>[^"]+)", (?P<qty>[0-9.]+), (?P<price>[0-9]+)$'))
def _r1_has_item(db, rev3, name, qty, price):
    actual = custom_row(db, rev3["R1"])[:3]
    assert actual == (name, h.parse_tenths(qty), int(price)), f"R1 的自訂工項應為 {(name, qty, price)}，實際 {actual}"


@then(parsers.re(r'R1 has exactly one custom item "(?P<name>[^"]+)", (?P<qty>[0-9.]+), (?P<price>[0-9]+)$'))
def _r1_has_exactly_one_item(db, rev3, name, qty, price):
    """取代，不是新增：舊的名稱不在了，這張回報只有這一個（三個欄位就是這個工項的全部）。"""
    actual = custom_row(db, rev3["R1"])[:3]
    assert actual == (name, h.parse_tenths(qty), int(price)), f"R1 應只有自訂工項 {(name, qty, price)}，實際 {actual}"


@then("R1 has no custom item")
def _r1_has_none(db, rev3):
    actual = custom_row(db, rev3["R1"])[:3]
    assert actual == (None, None, None), f"R1 不應有自訂工項（三個欄位都是 null），實際 {actual}"


@then("R1 is PENDING and has no stored shares")
def _r1_pending_no_shares(db, rev3):
    status, reviewer, reviewed_at = h.report_row(db, rev3["R1"])
    assert (status, reviewer, reviewed_at) == ("PENDING", None, None), f"R1 應為 PENDING 且沒有審核者，實際 {(status, reviewer, reviewed_at)}"
    with db.cursor() as cur:
        cur.execute(
            "select (select count(*) from yc_v3.report_shares where report_id = %s), "
            "(select count(*) from yc_v3.report_custom_shares where report_id = %s)",
            (rev3["R1"], rev3["R1"]),
        )
        shares, custom = cur.fetchone()
    db.rollback()
    assert (shares, custom) == (0, 0), f"份額應已作廢：目錄工項 {shares} 列、自訂工項 {custom} 列"


@then(parsers.re(r'custom-item money is (?P<first>[0-9]+) for "(?P<a>[^"]+)" and (?P<second>[0-9]+) for "(?P<b>[^"]+)"$'))
def _custom_money(db, first, a, second, b):
    """呼叫 T-301 目錄裡 T-302 新增的讀取函式（D-111），期間與 REV-F02 的「計算薪資」步驟相同（11-06～11-20）。"""
    from app.modules.review.crew_split_and_stored_shares import service as shares

    money = shares.confirmed_custom_money(db, date(2026, 11, 6), date(2026, 11, 20))
    db.rollback()
    expected = {h.account_row(db, a)[0]: int(first), h.account_row(db, b)[0]: int(second)}
    assert money == expected, f"自訂工項金額應為 {expected}（依帳戶 id），實際 {money}"
