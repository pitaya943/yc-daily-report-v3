"""保留金公式(純函式,不讀資料庫、不讀時鐘)。T-113。

  period raw  = Σ(tenths × 費率) / 10          (每個年度各自加總,Fraction)
  per-year    = max(0, min(half_up(raw), cap − ytd_before))
  period      = Σ 各年度 per-year

設計重點:
- 金額一律是整數與 fractions.Fraction,不使用浮點數,也不用內建 round()(銀行家捨入)。
- 費率、上限、年度累計都以參數傳入,不寫死預設值(預設值在附錄 A.4,由呼叫端讀設定)。
- AD-3:每筆回報歸屬它「自己回報日期」的日曆年(日期由呼叫端換成台灣時間的日曆日);
  跨年區間分年各算再相加,與區間怎麼切無關。
- 四捨五入(AD-2,half-up)在「每個年度加總之後」做一次;因為 cap − ytd 是整數,
  先四捨五入再截上限與先截再四捨五入結果相同。
- ytd_before 已包含管理員的 offset(PAY-R14):呼叫端用 displayed_ytd(calculated, offset)。
"""
import re
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class RetentionEntry:
    """一筆已核准的份額:回報日期(台灣日曆日)、數量(tenth)、保留金費率(元/只)。"""
    report_date: date
    tenths: int
    rate: int


def round_half_up(value: Fraction) -> int:
    """四捨五入到整數,恰好 .5 時往正無限大進位(floor(x + 1/2))。"""
    return (value * 2 + 1) // 2


def item_rate(*, account_has_retention: bool, item_is_retention: bool,
              zone_rate: int, personal_rate: Optional[int]) -> int:
    """PAY-R10:這個帳戶在這個工項的保留金費率(元/只)。

    帳戶沒有保留金(大表、管理員)或工項不是該區的保留金項 → 0。
    否則個人費率(含 0)優先於區費率;None 才表示沒設定。
    """
    if not account_has_retention or not item_is_retention:
        return 0
    return zone_rate if personal_rate is None else personal_rate


def raw_retention_by_year(entries: Sequence[RetentionEntry]) -> dict[int, Fraction]:
    """AD-3:依每筆回報日期的年度分組,各年度的未四捨五入保留金。"""
    totals: dict[int, Fraction] = {}
    for e in entries:
        totals[e.report_date.year] = (
            totals.get(e.report_date.year, Fraction(0)) + Fraction(e.tenths * e.rate, 10))
    return totals


def capped_retention(raw: int, cap: int, ytd_before: int) -> int:
    """PAY-R11:max(0, min(raw, cap − ytd_before))。cap < ytd 時空間為負,結果夾成 0。"""
    return max(0, min(raw, cap - ytd_before))


def period_retention(entries: Sequence[RetentionEntry], cap: int,
                     ytd_before_by_year: Mapping[int, int]) -> int:
    """一個薪資區間的保留金:各年度四捨五入、套各自的上限,再相加。缺少的年度累計視為 0。"""
    total = 0
    for year, raw in raw_retention_by_year(entries).items():
        total += capped_retention(round_half_up(raw), cap, ytd_before_by_year.get(year, 0))
    return total


def offset_for_target(*, calculated: int, target: int) -> int:
    """PAY-R14:管理員輸入目標年度累計,存 offset = 目標 − 計算值(按年度分開存)。"""
    return target - calculated


def displayed_ytd(*, calculated: int, offset: int) -> int:
    """顯示的年度累計 = 計算值 + 該年度 offset;也是計算上限時使用的累計。"""
    return calculated + offset


_WHOLE_AMOUNT = re.compile(r"-?[0-9]+")


def parse_whole_amount(text: str) -> int:
    """PAY-R14 目標驗證:只接受(可為負的)ASCII 整數字串,否則 ValueError(對應 INVALID)。

    不去除空白、不接受小數、正號、科學記號;缺少的值不補預設值。
    """
    if not _WHOLE_AMOUNT.fullmatch(text):
        raise ValueError("not a whole amount")
    return int(text)
