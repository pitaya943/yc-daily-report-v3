"""工項目錄（spec/appendix-a-catalogues.md；AD-4）。

保存方式：Python 的不可變常數，不放資料庫。
- 目錄是規格固定的（代碼是穩定識別碼；32／37／25 項），不是使用者編輯的資料；放在程式裡，
  git 就是它的版本紀錄，也不需要為了「讀目錄」多一次查詢或多一張要 seed 的表。
- 會變的是「單價」與「保留金費率」（管理員可改，CFG feature）：那些之後存資料庫，這裡的 `default_price` 只是
  附錄 A 的預設值，`retention` 只是附錄 A 標示的「該區該工項是否預扣保留金」。
- 回報存的是工項「代碼」（report_items.item_code），不是顯示名稱，所以日後改顯示名稱不影響既有回報。
- tests/steps/RPT-F01 會把這份資料逐項（代碼、顯示名稱、預設單價、保留金、順序）與附錄 A 比對；
  改動這個檔案卻沒有改規格會讓測試失敗。
取捨：之後若要「管理員新增工項」，這裡要改成資料庫；規格目前沒有這個需求（工項組固定為三個）。

給 T-202、T-203 import：

    from app.modules.reports.submit_a_daily_report.catalogue import catalogue, catalogue_for_account, display_name
"""
from __future__ import annotations

from dataclasses import dataclass

# 規格的三個工項組名稱（AD-4）；與 migration 0005 reports.catalogue 的 check 約束相同
WEST = "WEST"
SOUTH = "SOUTH"
BIG_METER = "BIG_METER"
CATALOGUE_NAMES = (WEST, SOUTH, BIG_METER)


@dataclass(frozen=True)
class Item:
    code: str  # 穩定識別碼；表單欄位名稱、report_items.item_code
    display_name: str  # 使用者看到的文字
    default_price: int  # NTD／只，附錄 A 的預設值（管理員可改，CFG feature）
    retention: bool  # 附錄 A「保留金」欄：該區該工項是否預扣保留金


def _item(code: str, display_name: str, default_price: int, retention: bool) -> Item:
    return Item(code, display_name, default_price, retention)


# 以下三個目錄由附錄 A.1～A.3 的表逐列產生，順序與表中相同（也是表單顯示的順序）。
_WEST = (
    _item("direct_13", "直總-13", 120, True),
    _item("direct_20", "直總-20", 120, True),
    _item("direct_25", "直總-25", 120, True),
    _item("direct_40", "直總-40", 170, True),
    _item("indirect_13", "間接-13", 75, True),
    _item("indirect_20", "間接-20", 75, True),
    _item("indirect_25", "間接-25", 75, True),
    _item("indirect_40", "間接-40", 125, True),
    _item("original_change", "原改", 45, False),
    _item("dsv_13", "直總-換由令(含表)-13", 200, False),
    _item("dsv_20", "直總-換由令(含表)-20", 200, False),
    _item("dsv_25", "直總-換由令(含表)-25", 200, False),
    _item("isv_13", "間接-換由令(含表)-13", 150, False),
    _item("isv_20", "間接-換由令(含表)-20", 150, False),
    _item("isv_25", "間接-換由令(含表)-25", 150, False),
    _item("sw_13", "13換開關(含表)", 320, False),
    _item("sw_20", "20換開關(含表)", 320, False),
    _item("sw_25", "25換開關(含表)", 320, False),
    _item("switch_valve_40", "40換開關(含表)", 450, False),
    _item("dfix_13", "直總-13固拆(含表)", 340, False),
    _item("dfix_20", "直總-20固拆(含表)", 340, False),
    _item("dfix_25", "直總-25固拆(含表)", 340, False),
    _item("direct_fixed_40", "直總-40固拆(含表)", 500, False),
    _item("ifix_13", "間接-13固拆(含表)", 230, False),
    _item("ifix_20", "間接-20固拆(含表)", 230, False),
    _item("ifix_25", "間接-25固拆(含表)", 230, False),
    _item("indirect_fixed_40", "間接-40固拆(含表)", 450, False),
    _item("pipe_repair", "管修(提高)", 150, False),
    _item("mobilization", "動員", 1200, False),
    _item("recheck", "複查案/9年表", 60, False),
    _item("soil_clearing", "清積土", 100, False),
    _item("app_item", "APP", 10, False),
)

_SOUTH = (
    _item("direct_13", "直總-13", 140, True),
    _item("direct_20", "直總-20", 140, True),
    _item("direct_25", "直總-25", 140, True),
    _item("direct_40", "直總-40", 190, True),
    _item("indirect_13", "間接-13", 90, True),
    _item("indirect_20", "間接-20", 90, True),
    _item("indirect_25", "間接-25", 90, True),
    _item("indirect_40", "間接-40", 140, True),
    _item("s_orig_13", "原改-13", 40, False),
    _item("s_orig_20", "原改-20", 40, False),
    _item("s_orig_25", "原改-25", 40, False),
    _item("s_orig_40", "原改-40", 50, False),
    _item("s_dsv_13", "直總-換由令(含表)-13", 220, True),
    _item("s_dsv_20", "直總-換由令(含表)-20", 220, True),
    _item("s_dsv_25", "直總-換由令(含表)-25", 220, True),
    _item("s_dsv_40", "直總-換由令(含表)-40", 220, True),
    _item("s_isv_13", "間接-換由令(含表)-13", 170, True),
    _item("s_isv_20", "間接-換由令(含表)-20", 170, True),
    _item("s_isv_25", "間接-換由令(含表)-25", 170, True),
    _item("s_isv_40", "間接-換由令(含表)-40", 170, True),
    _item("s_sw_13", "13換開關(含表)", 310, True),
    _item("s_sw_20", "20換開關(含表)", 310, True),
    _item("s_sw_25", "25換開關(含表)", 310, True),
    _item("switch_valve_40", "40換開關(含表)", 440, True),
    _item("s_dfix_13", "直總-13固拆(含表)", 330, True),
    _item("s_dfix_20", "直總-20固拆(含表)", 330, True),
    _item("s_dfix_25", "直總-25固拆(含表)", 330, True),
    _item("direct_fixed_40", "直總-40固拆(含表)", 490, True),
    _item("s_ifix_13", "間接-13固拆(含表)", 270, True),
    _item("s_ifix_20", "間接-20固拆(含表)", 270, True),
    _item("s_ifix_25", "間接-25固拆(含表)", 270, True),
    _item("indirect_fixed_40", "間接-40固拆(含表)", 440, True),
    _item("pipe_repair", "管修(提高)", 150, False),
    _item("mobilization", "動員", 1200, False),
    _item("recheck", "複查案/9年表", 70, False),
    _item("soil_clearing", "清積土", 130, False),
    _item("app_item", "APP", 10, False),
)

_BIG_METER = (
    _item("bm_50_down", "50mm下", 1100, False),
    _item("bm_75_down", "75mm下", 1800, False),
    _item("bm_100_down", "100mm下", 2000, False),
    _item("bm_150_down", "150mm下", 2400, False),
    _item("bm_200_down", "200mm下", 2800, False),
    _item("bm_250_down", "250mm下", 3300, False),
    _item("bm_300_down", "300mm下", 3900, False),
    _item("bm_50_up", "50mm上", 1100, False),
    _item("bm_75_up", "75mm上", 1700, False),
    _item("bm_100_up", "100mm上", 1900, False),
    _item("bm_150_up", "150mm上", 2100, False),
    _item("bm_200_up", "200mm上", 2500, False),
    _item("bm_250_up", "250mm上", 2700, False),
    _item("bm_rm_screw50", "拆表/復水-螺紋50mm", 800, False),
    _item("bm_rm_noscrew50", "拆表/復水-非螺紋50mm", 1100, False),
    _item("bm_rm_75", "拆表/復水-75mm", 1600, False),
    _item("bm_rm_100", "拆表/復水-100mm", 1900, False),
    _item("bm_rm_150", "拆表/復水-150mm", 2100, False),
    _item("bm_rm_200", "拆表/復水-200mm", 3000, False),
    _item("bm_hole", "孔片", 500, False),
    _item("bm_clean_big", "清箱大", 700, False),
    _item("bm_truck", "小貨車", 700, False),
    _item("bm_mobilization", "動員", 1200, False),
    _item("bm_recheck", "復查", 70, False),
    _item("bm_app", "APP", 10, False),
)
_CATALOGUES: dict[str, tuple[Item, ...]] = {WEST: _WEST, SOUTH: _SOUTH, BIG_METER: _BIG_METER}
_BY_CODE: dict[str, dict[str, Item]] = {name: {i.code: i for i in items} for name, items in _CATALOGUES.items()}


def catalogue(name: str) -> tuple[Item, ...]:
    """某個工項組的全部工項（順序固定）。名稱不是 WEST／SOUTH／BIG_METER 時丟 KeyError（程式錯誤，不是使用者輸入）。"""
    return _CATALOGUES[name]


def catalogue_name_for(zone: str, big_meter: bool) -> str:
    """帳戶 → 工項組（spec/glossary.md）：大表旗標開的 USER 用 BIG_METER，否則依施工區域。"""
    return BIG_METER if big_meter else zone


def catalogue_for_account(zone: str, big_meter: bool) -> tuple[Item, ...]:
    return catalogue(catalogue_name_for(zone, big_meter))


def item_codes(name: str) -> frozenset[str]:
    return frozenset(_BY_CODE[name])


def display_name(catalogue_name: str, code: str) -> str:
    """工項代碼 → 顯示名稱（以回報送出當時的工項組為準）。代碼不在該工項組時丟 KeyError。"""
    return _BY_CODE[catalogue_name][code].display_name
