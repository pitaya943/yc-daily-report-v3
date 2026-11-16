"""T-112: payroll formula (pure functions), PAY-R01/R02/R03/R06 examples.

Quantities are integers in tenths of a unit (2.3 units == 23); prices and
rates are integers. The helper `line` builds the share lines the way the
spec's Gherkin examples describe them.
"""
import ast
import inspect
from fractions import Fraction

import pytest

from app.domain import payroll
from app.domain.payroll import ShareLine, calculate_row, round_half_up

# Spec defaults (WEST direct_13 = 120, retention 20/unit, uninsured 3%).
RATE_3 = Fraction(3)


def line(qty_tenths, price=120, retention=20):
    return ShareLine(tenths=qty_tenths, unit_price=price, retention_per_unit=retention)


def row(lines, *, fixed=0, ins=0, every=False, exempt=False, p10=False,
        rate=RATE_3, custom=0):
    return calculate_row(
        lines, custom_money=custom, fixed_salary=fixed, insurance=ins,
        every_period=every, exempt=exempt, payday_10=p10,
        uninsured_rate_percent=rate)


# ---- PAY-R01: one test per Examples row ---------------------------------
R01_EXAMPLES = [
    # qty fixed ins every exempt p10  gross ret fa ia ud final
    pytest.param(10, 0, 0, False, False, False, 1200, 200, 0, 0, 36, 964, id="v2-example-A"),
    pytest.param(10, 5000, 834, False, False, True, 1200, 200, 5000, 834, 0, 5166, id="v2-example-B"),
    pytest.param(10, 5000, 834, False, False, False, 1200, 200, 0, 0, 0, 1000, id="enrolled-not-payday-10"),
    pytest.param(10, 5000, 0, True, False, False, 1200, 200, 5000, 0, 36, 5964, id="every-period-fixed"),
    pytest.param(10, 0, 0, False, True, False, 1200, 200, 0, 0, 0, 1000, id="exempt"),
    pytest.param(0, 5000, 0, False, False, True, 0, 0, 5000, 0, 0, 5000, id="fixed-salary-only"),
]


@pytest.mark.parametrize(
    "qty,fixed,ins,every,exempt,p10,gross,ret,fa,ia,ud,final", R01_EXAMPLES)
def test_pay_r01_components(qty, fixed, ins, every, exempt, p10,
                            gross, ret, fa, ia, ud, final):
    r = row([line(qty * 10)] if qty else [], fixed=fixed, ins=ins,
            every=every, exempt=exempt, p10=p10)
    assert (r.gross, r.retention, r.fixed_applied, r.insurance_applied,
            r.uninsured_deduction, r.final) == (gross, ret, fa, ia, ud, final)


# ---- PAY-R02 -------------------------------------------------------------
def test_pay_r02_fixed_salary_not_in_base():
    # gross 10000 (= 100 units x 100), fixed 5000 every-period: 3% of 10000.
    r = row([line(1000, price=100, retention=0)], fixed=5000, every=True)
    assert r.gross == 10000
    assert r.uninsured_deduction == 300


def test_pay_r02_personal_rate_overrides_zone_rate():
    r = row([line(1000, price=100, retention=0)], rate=Fraction(5))
    assert r.uninsured_deduction == 500


# ---- PAY-R03 -------------------------------------------------------------
@pytest.mark.parametrize("gross,expected", [(10001, 300), (10017, 301)])
def test_pay_r03_uninsured_deduction_rounds_half_up(gross, expected):
    r = row([ShareLine(tenths=10, unit_price=gross, retention_per_unit=0)])
    assert r.gross == gross
    assert r.uninsured_deduction == expected


def test_pay_r03_each_component_rounded_then_summed_ad2():
    # indirect_13, 2.3 units at 75: exact gross 172.5, retention 46, ud 5.175
    r = row([line(23, price=75)])
    assert (r.gross, r.retention, r.uninsured_deduction, r.final) == (173, 46, 5, 122)


@pytest.mark.parametrize("kwargs", [
    dict(), dict(fixed=5000, ins=834, p10=True), dict(fixed=5000, every=True),
    dict(exempt=True), dict(custom=333),
])
@pytest.mark.parametrize("qty", [0, 1, 23, 77, 1000])
def test_pay_r03_displayed_components_add_up_to_final(qty, kwargs):
    r = row([line(qty, price=75)] if qty else [], **kwargs)
    assert r.final == (r.gross - r.retention + r.fixed_applied
                       - r.insurance_applied - r.uninsured_deduction)


def test_round_half_up_boundaries():
    assert round_half_up(Fraction(1, 2)) == 1
    assert round_half_up(Fraction(1725, 10)) == 173
    assert round_half_up(Fraction(499, 1000)) == 0
    assert round_half_up(Fraction(0)) == 0
    assert round_half_up(Fraction(-1, 2)) == 0  # half-up: toward +infinity


# ---- PAY-R06 -------------------------------------------------------------
@pytest.mark.parametrize("gross,final,listed", [
    (0, 0, False), (0, 5000, True), (1200, 0, True)])
def test_pay_r06_row_visibility(gross, final, listed):
    r = payroll.PayrollRow(gross=gross, retention=0, fixed_applied=0,
                           insurance_applied=0, uninsured_deduction=0, final=final)
    assert r.listed is listed


def test_pay_r06_zero_activity_row_not_listed():
    assert row([]).listed is False
    assert row([], fixed=5000, p10=True).listed is True


# ---- No floating point ---------------------------------------------------
def test_results_are_ints():
    r = row([line(23, price=75)])
    for v in (r.gross, r.retention, r.fixed_applied, r.insurance_applied,
              r.uninsured_deduction, r.final):
        assert type(v) is int


def test_module_source_has_no_float():
    tree = ast.parse(inspect.getsource(payroll))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
        if isinstance(node, ast.Name):
            assert node.id != "float"
