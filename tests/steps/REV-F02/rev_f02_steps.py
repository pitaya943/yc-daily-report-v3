"""REV-F02 小組分配與份額保存的步驟（REV-R10、REV-R11；D-111）。

- REV-R10 是純函式：`app.domain.split.split`，不碰資料庫與 HTTP。
- REV-R11 走真的 HTTP 確認（`POST /review/reports/confirm`），再從資料庫讀回份額；
  「計算薪資」呼叫 `app.modules.review.crew_split_and_stored_shares.service.confirmed_quantities`（D-111：T-402 會把它改接真正的薪資）。
- 輔助函式來自 REV-F01 的步驟檔（見 conftest.py）。
- 步驟文字（全域註冊，新增前已 grep 過）都是 REV-F02 獨有的。
"""
from __future__ import annotations

from datetime import date

import pytest
import rev_f01_steps as h
from pytest_bdd import given, parsers, then, when

from app.domain.split import split
from tests.steps.common.outcome import *  # noqa: F401,F403
from tests.steps.common.steps import *  # noqa: F401,F403

DATE = "2026-11-10"  # 回報日期：背景的「今天」往前 5 天，在 30 天內


@pytest.fixture
def rev2() -> dict:
    """REV-R10 與 REV-R11 的 scenario 狀態。"""
    return {}


def names_and_values(text: str) -> list[tuple[str, int]]:
    """`Wen 2.4, Wei 2.3, Wan 2.3` → [("Wen", 24), ("Wei", 23), ("Wan", 23)]。"""
    out = []
    for piece in text.split(","):
        who, qty = piece.split()
        out.append((who, h.parse_tenths(qty)))
    return out


# ───────────────────────── REV-R10：純函式 ─────────────────────────


@given(parsers.re(r'a crew of (?P<n>[0-9]+) in order "(?P<crew>[^"]+)"$'))
def _a_crew_of(rev2, n, crew):
    members = [m.strip() for m in crew.split(",")]
    assert len(members) == int(n), f"crew 的人數 {len(members)} 與 {n} 不符"
    rev2["crew"] = members


@when(parsers.re(r"a quantity of (?P<qty>[0-9.]+) units is split$"))
def _split_a_quantity(rev2, qty):
    rev2["shares"] = split(h.parse_tenths(qty), len(rev2["crew"]))


@then(parsers.re(r'the shares in crew order are "(?P<shares>[^"]+)"$'))
def _shares_in_crew_order(rev2, shares):
    actual = ", ".join(h.tenths_text(t) for t in rev2["shares"])
    assert actual == shares, f"份額（依 crew 順序）應為 {shares}，實際 {actual}"


@given("any quantity from 0 to 999.9 in steps of 0.1 and any crew size from 1 to 7")
def _any_quantity_and_crew(rev2):
    rev2["inputs"] = [(tenths, size) for tenths in range(0, 10000) for size in range(1, 8)]


@when("the quantity is split")
def _split_everything(rev2):
    rev2["results"] = [(tenths, size, split(tenths, size)) for tenths, size in rev2["inputs"]]


@then("the shares sum exactly to the quantity")
def _sum_is_exact(rev2):
    bad = [(t, n, s) for t, n, s in rev2["results"] if sum(s) != t or len(s) != n]
    assert not bad, f"份額加總必須等於數量（共 {len(bad)} 組不符），例如 {bad[:3]}"


@then("the largest and smallest share differ by at most 0.1")
def _spread(rev2):
    bad = [(t, n, s) for t, n, s in rev2["results"] if max(s) - min(s) > 1]
    assert not bad, f"最大與最小份額最多相差 0.1（1 tenth），例如 {bad[:3]}"


@then("no later crew member has a larger share than an earlier one")
def _non_increasing(rev2):
    bad = [(t, n, s) for t, n, s in rev2["results"] if any(s[i] < s[i + 1] for i in range(len(s) - 1))]
    assert not bad, f"後面的人不該比前面的人多，例如 {bad[:3]}"


# ───────────────────────── REV-R11：保存的份額 ─────────────────────────


def _crew_members(crew: str) -> list[str]:
    return [m.strip() for m in crew.split(",")]


@given(parsers.re(r'a PENDING report by "(?P<name>[^"]+)" with crew "(?P<crew>[^"]+)" and "(?P<item>[^"]+)" = (?P<qty>[0-9.]+)$'))
def _pending_with_crew(db, rev2, lifecycle, name, crew, item, qty):
    members = _crew_members(crew)
    assert members[0] == name, "crew 的第一位是提交者"
    rid = h.insert_report(db, name, DATE, "PENDING", items={item: h.parse_tenths(qty)}, crew=tuple(members[1:]))
    rev2.update(report_id=rid, item=item, submitter=name)
    lifecycle.update(report_id=rid, date=DATE, state="PENDING")


@given(parsers.re(r'a PENDING report with crew "(?P<crew>[^"]+)" and custom item quantity (?P<qty>[0-9.]+) at price (?P<price>[0-9]+)$'))
def _pending_with_custom(db, rev2, lifecycle, crew, qty, price):
    members = _crew_members(crew)
    rid = h.insert_report(db, members[0], DATE, "PENDING", crew=tuple(members[1:]), custom=("Special work", h.parse_tenths(qty), int(price)))
    rev2.update(report_id=rid, submitter=members[0])
    lifecycle.update(report_id=rid, date=DATE, state="PENDING")


@given(parsers.re(r'a CONFIRMED report with stored shares (?P<shares>[A-Za-z0-9., ]+) of "(?P<item>[^"]+)"$'))
def _confirmed_with_shares(db, rev2, lifecycle, shares, item):
    pairs = names_and_values(shares)
    rid = h.insert_report(
        db, pairs[0][0], DATE, "CONFIRMED", items={item: sum(t for _, t in pairs)}, crew=tuple(n for n, _ in pairs[1:]), reviewer="Admin2"
    )
    h.insert_shares(db, rid, item, pairs)
    rev2.update(report_id=rid, item=item)
    lifecycle.update(report_id=rid, date=DATE, state="CONFIRMED")


@given(parsers.re(r'"(?P<name>[^"]+)" was archived after (?:the confirmation|the report was submitted)$'))
def _was_archived(db, name):
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = %s", (name,))
    db.commit()


@when(parsers.re(r'"(?P<name>[^"]+)" confirms it$'))
def _confirms_it(recorder, client, db, rev2, name):
    h.ensure_signed_in(client, db, name)
    recorder.perform(lambda: h.post(client, db, name, "/review/reports/confirm", [("id", str(rev2["report_id"]))]))


@when("payroll is calculated for a period containing the report")
def _payroll_for_period(db, rev2):
    from app.modules.review.crew_split_and_stored_shares import service as shares

    rev2["quantities"] = shares.confirmed_quantities(db, date(2026, 11, 6), date(2026, 11, 20))
    db.rollback()


@then(parsers.re(r'the stored shares of "(?P<item>[^"]+)" are (?P<shares>[A-Za-z0-9., ]+)$'))
def _stored_shares_are(db, rev2, item, shares):
    expected = names_and_values(shares)
    actual = h.stored_shares(db, rev2["report_id"], item)
    assert actual == expected, f"{item} 已存的份額（依 crew 順序）應為 {expected}，實際 {actual}"


@then(parsers.re(r'the stored custom-item shares are (?P<shares>[A-Za-z0-9., ]+)$'))
def _stored_custom_shares_are(db, rev2, shares):
    with db.cursor() as cur:
        cur.execute(
            "select a.name, s.tenths from yc_v3.report_custom_shares s join yc_v3.accounts a on a.id = s.account_id "
            "where s.report_id = %s order by s.position",
            (rev2["report_id"],),
        )
        actual = cur.fetchall()
    db.rollback()
    expected = names_and_values(shares)
    assert actual == expected, f"自訂工項已存的份額應為 {expected}，實際 {actual}"


@then(parsers.re(r'the "(?P<item>[^"]+)" quantities are (?P<shares>[A-Za-z0-9., ]+)$'))
def _quantities_are(db, rev2, item, shares):
    expected = {h.account_row(db, who)[0]: tenths for who, tenths in names_and_values(shares)}
    actual = {account_id: items[item] for account_id, items in rev2["quantities"].items() if item in items}
    assert actual == expected, f"{item} 的數量應為 {expected}（依帳戶 id），實際 {actual}"
