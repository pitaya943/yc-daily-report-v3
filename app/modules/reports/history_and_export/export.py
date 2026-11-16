"""匯出 .xlsx（D-087：openpyxl）。純函式：輸入已篩選的回報，輸出檔案的位元組；不讀資料庫、不讀時鐘、不寫稽核。

欄位（RPT-R22）：日期、帳戶、工項（該頁涵蓋的工項組的聯集）、自訂工項、確認狀態。
每張回報一列；沒填的工項留空白，填了的是數量（0.1 只，以 Decimal 寫入，不經過浮點數計算）。

安全：帳戶名稱與自訂工項名稱是使用者輸入。openpyxl 會把以 `=` 開頭的字串存成公式，所以所有文字儲存格都
明確設成字串型別（data_type "s"），開啟檔案時 Excel 不會執行它。
"""
from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.cell import Cell

from app.modules.reports.history_and_export import service
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report.repo import Report

CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_NAME = "歷史"
HEAD_DATE, HEAD_ACCOUNT, HEAD_CUSTOM, HEAD_STATUS = "日期", "帳戶", "自訂工項", "確認狀態"


def headers(catalogue_names: list[str]) -> list[str]:
    return [HEAD_DATE, HEAD_ACCOUNT, *service.item_columns(catalogue_names), HEAD_CUSTOM, HEAD_STATUS]


def _text(cell: Cell, value: str) -> None:
    cell.value = value
    cell.data_type = "s"  # 不論開頭是不是 `=`，都是文字


def build_workbook(reports: list[Report], catalogue_names: list[str]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    head = headers(catalogue_names)
    for col, title in enumerate(head, start=1):
        _text(ws.cell(row=1, column=col), title)
    first_item_col = 3
    column_of = {title: first_item_col + i for i, title in enumerate(head[2:-2])}
    for row, report in enumerate(reports, start=2):
        _text(ws.cell(row=row, column=1), report.report_date.isoformat())
        _text(ws.cell(row=row, column=2), report.submitter_name)
        for code, tenths in report.items.items():
            title = cat.display_name(report.catalogue, code)
            ws.cell(row=row, column=column_of[title], value=service.tenths_to_decimal(tenths))
        _text(ws.cell(row=row, column=len(head) - 1), service.custom_text(report))
        _text(ws.cell(row=row, column=len(head)), service.STATUS_WORDING[report.status])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
