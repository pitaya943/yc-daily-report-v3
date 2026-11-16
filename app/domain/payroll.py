"""薪資公式(純函式,不讀資料庫、不讀時鐘)。T-112。

  gross  = Σ(share × unit price) + custom-item money
  net    = gross − period retention
  final  = net + fixed salary applied − insurance applied − uninsured deduction

金額一律用整數與 fractions.Fraction 計算,不使用浮點數。
數量以 tenth(0.1 只)為單位的整數表示(2.3 只 = 23)。
AD-2:gross、retention、uninsured deduction 各自 half-up 到整數元;
final 用四捨五入後的整數組成相加;未投保扣除的基數是「未四捨五入」的 gross。
"""
from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence


def round_half_up(value: Fraction) -> int:
    """四捨五入到整數,恰好 .5 時往正無限大進位(floor(x + 1/2))。"""
    return (value * 2 + 1) // 2


@dataclass(frozen=True)
class ShareLine:
    """核准時存下的一筆份額:數量(tenth)、單價(元/只)、保留金(元/只)。"""
    tenths: int
    unit_price: int
    retention_per_unit: int


@dataclass(frozen=True)
class PayrollRow:
    gross: int
    retention: int
    fixed_applied: int
    insurance_applied: int
    uninsured_deduction: int
    final: int

    @property
    def listed(self) -> bool:
        """PAY-R06:毛額與實發都是 0 的帳戶不列出。"""
        return not (self.gross == 0 and self.final == 0)


def calculate_row(
    lines: Sequence[ShareLine],
    *,
    custom_money: int,
    fixed_salary: int,
    insurance: int,
    every_period: bool,
    exempt: bool,
    payday_10: bool,
    uninsured_rate_percent: Fraction,
) -> PayrollRow:
    """計算一位員工在一個薪資批次的各欄金額。

    - 固定薪資:10 號發薪,或帳戶設為每期發放時才套用。
    - 勞健保:只在 10 號發薪套用。
    - 未投保扣除:每一批次都套用,但已加保(insurance > 0)或豁免者為 0。
    """
    gross_exact = sum(
        (Fraction(l.tenths * l.unit_price, 10) for l in lines), Fraction(custom_money))
    retention_exact = sum(
        (Fraction(l.tenths * l.retention_per_unit, 10) for l in lines), Fraction(0))

    insured = insurance > 0
    if exempt or insured:
        uninsured_exact = Fraction(0)
    else:
        uninsured_exact = gross_exact * Fraction(uninsured_rate_percent) / 100

    gross = round_half_up(gross_exact)
    retention = round_half_up(retention_exact)
    uninsured = round_half_up(uninsured_exact)
    fixed_applied = fixed_salary if (payday_10 or every_period) else 0
    insurance_applied = insurance if payday_10 else 0

    final = gross - retention + fixed_applied - insurance_applied - uninsured
    return PayrollRow(gross, retention, fixed_applied, insurance_applied, uninsured, final)
