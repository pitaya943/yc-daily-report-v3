"""T-113: 保留金純函式(PAY-R10 / R11 / R12 / R14 的例子 + AD-3 補充)。

單位約定:數量以 tenth(0.1 只)的整數表示;費率、上限、年度累計都是整數元;
日期是台灣時間的日曆日(呼叫端負責換算,純函式不讀時鐘)。
費率與上限一律以參數傳入。預設值(20 元/只、上限 60000)只用在測試輸入。
"""
import ast
import inspect
from datetime import date
from fractions import Fraction

import pytest

from app.domain import retention
from app.domain.retention import (
    RetentionEntry,
    capped_retention,
    displayed_ytd,
    item_rate,
    offset_for_target,
    parse_whole_amount,
    period_retention,
    raw_retention_by_year,
)

ZONE_RATE = 20      # 附錄 A.4 預設:20 NTD/只
CAP = 60000         # 附錄 A.4 預設:60000 NTD
D = date(2026, 11, 15)


def raw_of(tenths, rate):
    """單一回報的未四捨五入保留金(Fraction)。"""
    return raw_retention_by_year([RetentionEntry(D, tenths, rate)])[2026]


# ---- PAY-R10:誰、哪個工項有保留金(每列一個測試) --------------------------
R10_EXAMPLES = [
    # id, 帳戶有保留金, 工項是該區保留金項, 預期 period retention(share 10.0 = 100 tenths)
    pytest.param(True, True, 200, id="Wen-direct_13-WEST-retention-item"),
    pytest.param(True, False, 0, id="Wen-dsv_13-not-a-retention-item"),
    pytest.param(True, True, 200, id="Nan-s_dsv_13-SOUTH-retention-item"),
    pytest.param(True, False, 0, id="Nan-s_orig_13-not-a-retention-item"),
    pytest.param(False, False, 0, id="Big-bm_50_down-big-meter"),
]


@pytest.mark.parametrize("account_has, item_is, expected", R10_EXAMPLES)
def test_pay_r10_rows(account_has, item_is, expected):
    rate = item_rate(account_has_retention=account_has, item_is_retention=item_is,
                     zone_rate=ZONE_RATE, personal_rate=None)
    entries = [RetentionEntry(D, 100, rate)]
    assert period_retention(entries, CAP, {}) == expected


def test_pay_r10_personal_rate_overrides_zone_rate():
    rate = item_rate(account_has_retention=True, item_is_retention=True,
                     zone_rate=ZONE_RATE, personal_rate=50)
    assert rate == 50
    assert period_retention([RetentionEntry(D, 100, rate)], CAP, {}) == 500


def test_pay_r10_personal_rate_zero_is_an_override_not_missing():
    # 個人費率 0 是有效的覆寫,不可被當成「沒設定」而退回區費率。
    assert item_rate(account_has_retention=True, item_is_retention=True,
                     zone_rate=ZONE_RATE, personal_rate=0) == 0


def test_pay_r10_personal_rate_never_creates_retention_for_ineligible():
    # 大表帳戶/非保留金項即使有個人費率也是 0(「沒有保留金」優先)。
    assert item_rate(account_has_retention=False, item_is_retention=True,
                     zone_rate=ZONE_RATE, personal_rate=50) == 0
    assert item_rate(account_has_retention=True, item_is_retention=False,
                     zone_rate=ZONE_RATE, personal_rate=50) == 0


# ---- PAY-R11:上限算術(每列一個測試) --------------------------------------
R11_EXAMPLES = [
    pytest.param(60000, 0, 200, 200, id="far-below-cap"),
    pytest.param(60000, 55000, 8000, 5000, id="v2-example-C"),
    pytest.param(60000, 59000, 3000, 1000, id="v2-BDD-010"),
    pytest.param(60000, 60000, 3000, 0, id="cap-already-reached"),
    pytest.param(80000, 59000, 3000, 3000, id="cap-raised"),
    pytest.param(0, 0, 3000, 0, id="cap-0-means-no-retention"),
    pytest.param(50000, 59000, 3000, 0, id="cap-lowered-below-ytd"),
]


@pytest.mark.parametrize("cap, ytd, raw, expected", R11_EXAMPLES)
def test_pay_r11_rows(cap, ytd, raw, expected):
    assert capped_retention(raw, cap, ytd) == expected
    # 同一組數字經過完整的 period_retention(單一年度)也要一致。
    entries = [RetentionEntry(D, raw // ZONE_RATE * 10, ZONE_RATE)]
    assert period_retention(entries, cap, {2026: ytd}) == expected


# 例子沒區分到的公式細節:
def test_r11_boundary_exactly_fills_cap():
    assert capped_retention(1000, 60000, 59000) == 1000   # 剛好填滿
    assert capped_retention(1001, 60000, 59000) == 1000   # 超過 1 元被截
    assert capped_retention(999, 60000, 59000) == 999     # 差 1 元不截


def test_r11_zero_raw_is_zero():
    assert capped_retention(0, 60000, 0) == 0


def test_r11_rounding_half_up_before_cap():
    # raw = 0.5 元 → half-up 為 1(不是銀行家捨入的 0)。
    assert period_retention([RetentionEntry(D, 1, 5)], CAP, {}) == 1
    # raw = 1.5 → 2;2.5 → 3(銀行家捨入會給 2)。
    assert period_retention([RetentionEntry(D, 3, 5)], CAP, {}) == 2
    assert period_retention([RetentionEntry(D, 5, 5)], CAP, {}) == 3
    # raw = 0.4 → 0。
    assert period_retention([RetentionEntry(D, 4, 1)], CAP, {}) == 0


def test_r11_rounding_uses_sum_of_entries_not_per_entry():
    # 兩筆各 0.5 元(同年)→ 合計 1.0 → 1;逐筆四捨五入會變 2。
    entries = [RetentionEntry(D, 1, 5), RetentionEntry(D, 1, 5)]
    assert period_retention(entries, CAP, {}) == 1


def test_r11_cap_applies_after_rounding_up_to_room():
    # room = 10,raw = 10.5 → 四捨五入 11,再被上限截成 10。
    entries = [RetentionEntry(D, 21, 5)]  # 21 tenth × 5 / 10 = 10.5
    assert period_retention(entries, 60000, {2026: 59990}) == 10


def test_r11_negative_room_is_clamped_to_zero_not_negative():
    assert capped_retention(3000, 50000, 59000) == 0
    assert capped_retention(3000, 50000, 59000) >= 0


# ---- PAY-R12 / AD-3:日曆年與跨年 ------------------------------------------
def test_pay_r12_year_boundary_is_by_report_date():
    by_year = raw_retention_by_year([
        RetentionEntry(date(2026, 12, 31), 100, 20),
        RetentionEntry(date(2027, 1, 1), 10, 20),
    ])
    assert by_year == {2026: Fraction(200), 2027: Fraction(20)}


def test_pay_r12_period_spanning_new_year_ad3():
    # ytd 2026 = 59000;100.0 只 on 12-30 → raw 2000;10.0 只 on 01-03 → raw 200。
    entries = [
        RetentionEntry(date(2026, 12, 30), 1000, 20),
        RetentionEntry(date(2027, 1, 3), 100, 20),
    ]
    assert period_retention(entries, CAP, {2026: 59000}) == 1200


def test_ad3_not_attributed_to_period_start_year():
    # 若誤用區間起始年度,整段都被 2026 的 1000 空間截斷 → 1000。
    entries = [
        RetentionEntry(date(2026, 12, 30), 1000, 20),
        RetentionEntry(date(2027, 1, 3), 100, 20),
    ]
    assert period_retention(entries, CAP, {2026: 59000}) != 1000


def test_ad3_new_year_does_not_inherit_old_year_ytd():
    # 2026 已滿(ytd = cap),2027 的回報仍然全額。
    entries = [RetentionEntry(date(2027, 1, 3), 100, 20)]
    assert period_retention(entries, CAP, {2026: 60000}) == 200


def test_ad3_each_year_capped_independently():
    entries = [
        RetentionEntry(date(2026, 12, 30), 1000, 20),   # raw 2000, room 1000
        RetentionEntry(date(2027, 1, 3), 3000, 20),     # raw 6000, room 2000
    ]
    assert period_retention(entries, CAP, {2026: 59000, 2027: 58000}) == 1000 + 2000


def test_ad3_missing_year_in_ytd_means_zero():
    entries = [RetentionEntry(date(2027, 1, 3), 100, 20)]
    assert period_retention(entries, CAP, {}) == 200


def test_ad3_rounding_is_per_year_then_summed():
    # 各年 0.5 元:各年 half-up 為 1,相加 2。(合併再捨入只會得到 1)
    entries = [
        RetentionEntry(date(2026, 12, 31), 1, 5),
        RetentionEntry(date(2027, 1, 1), 1, 5),
    ]
    assert period_retention(entries, CAP, {}) == 2


def test_ad3_result_independent_of_period_cut():
    # 同一批回報分成兩個區間算(第二段帶入第一段後的累計),總和等於一次算完。
    e1 = RetentionEntry(date(2026, 12, 30), 1000, 20)
    e2 = RetentionEntry(date(2027, 1, 3), 100, 20)
    whole = period_retention([e1, e2], CAP, {2026: 59000})
    first = period_retention([e1], CAP, {2026: 59000})
    second = period_retention([e2], CAP, {2026: 59000 + first})
    assert whole == first + second


def test_empty_entries_is_zero():
    assert period_retention([], CAP, {2026: 100}) == 0


# ---- PAY-R14:管理員設定目標與 offset --------------------------------------
def test_pay_r14_target_above_calculated_stores_positive_offset():
    assert offset_for_target(calculated=12000, target=15000) == 3000
    assert displayed_ytd(calculated=12000, offset=3000) == 15000


def test_pay_r14_negative_offset():
    assert offset_for_target(calculated=12000, target=10000) == -2000
    assert displayed_ytd(calculated=12000, offset=-2000) == 10000


def test_pay_r14_target_equal_calculated_is_zero_offset():
    assert offset_for_target(calculated=12000, target=12000) == 0


def test_pay_r14_negative_target_is_allowed():
    assert offset_for_target(calculated=12000, target=-500) == -12500
    assert displayed_ytd(calculated=12000, offset=-12500) == -500


def test_pay_r14_offset_counts_toward_cap():
    # 計算值 12000 + offset 47000 = 59000,room 1000。
    ytd = displayed_ytd(calculated=12000, offset=47000)
    assert ytd == 59000
    assert capped_retention(3000, CAP, ytd) == 1000
    entries = [RetentionEntry(D, 1500, 20)]  # raw 3000
    assert period_retention(entries, CAP, {2026: ytd}) == 1000


def test_pay_r14_negative_ytd_gives_more_room():
    # 目標為負時 room 變大:room = 60000 − (−500) = 60500。
    assert capped_retention(70000, CAP, -500) == 60500


@pytest.mark.parametrize("text, expected", [
    ("-500", -500), ("0", 0), ("15000", 15000),
])
def test_pay_r14_target_validation_accepted(text, expected):
    assert parse_whole_amount(text) == expected


@pytest.mark.parametrize("text", ["100.5", "abc", "", " 5", "5 ", "+5", "1e3", "--5", "-", "１２"])
def test_pay_r14_target_validation_invalid(text):
    with pytest.raises(ValueError):
        parse_whole_amount(text)


# ---- 型別與浮點數防線 -----------------------------------------------------
def test_results_are_ints_and_fractions_never_floats():
    assert isinstance(period_retention([RetentionEntry(D, 5, 5)], CAP, {}), int)
    assert isinstance(raw_of(5, 5), Fraction)


def test_no_float_or_builtin_round_in_module():
    tree = ast.parse(inspect.getsource(retention))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"round", "float"}
