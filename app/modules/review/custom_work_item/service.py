"""自訂工項（REV-F03：REV-R20～R24；D-086、D-112、D-118）。

    POST /review/reports/{id}/custom-item   附加、取代或移除（清空名稱）一張回報的自訂工項

## 規則與順序（有意義）

鎖列 → 權限 → 欄位驗證 → 「至少一個工項」→ 寫入、必要時退回 PENDING、稽核，同一個 transaction。

1. **鎖**（ticket 完成條件 8）：先用 `report_lifecycle.repo.lock_report`（`select … for update`）鎖住回報，
   與 T-202 的編輯、刪除、T-301 的確認／駁回是**同一個函式**。沒有這把鎖，管理員改自訂工項的同時另一位管理員確認，
   會得到「份額依舊的自訂工項存下、回報卻已是新的內容」的不一致。
2. **權限**（REV-R20）：只有 ADMIN、OWNER。權限先於欄位驗證，沒有權限的人不論送什麼都只得到 FORBIDDEN。
3. **欄位**（REV-R22，附錄 B）：名稱 1–100 字；清空名稱就是移除（REV-R21）；數量 0–999.9、0.1 的倍數；單價整數 ≥ 0。
4. **至少一個工項**（D-112）：改完之後回報若沒有任何數量 > 0 就拒絕 `INVALID`「請至少填寫一個工項數量」。
   判斷呼叫 `submit_a_daily_report.service.require_a_quantity`，不另寫一份。
5. **狀態**（REV-R24、AD-10）：回報不是 PENDING 時，改自訂工項等同管理員編輯：回到 PENDING、份額作廢（刪除份額與清掉審核者
   呼叫 T-301 的 `report_lifecycle.repo.discard_review`，不另寫一份）；CONFIRMED 另寫 `REPORT_UNCONFIRM`，與編輯（RPT-R12）相同。

## 伺服器重新驗證每個欄位（AGENTS.md 不可違反 #6）

`custom_name`、`custom_quantity`、`custom_price` 各必須出現恰好一次；缺少或重複不補預設值，直接 INVALID。
名稱有內容時，數量與單價也必須有值（附錄 B「必填：有名稱時」）；空白的數量或單價不是 0。
名稱清空（移除）時，數量與單價不看，不論送了什麼（REV-R21）。

## 沒有變更就不寫

附加與目前完全相同的自訂工項，或移除一個本來就沒有的自訂工項：成功，但什麼都不寫，也不讓已確認的回報退回 PENDING。
理由：份額與金額沒有變，不該逼管理員重新核准（AD-10 的理由是「自訂工項會改變薪資」）。

## 錯誤字串

逐字出自 spec/appendix-b-fields.md。欄位缺少、重複這類附錄 B 沒有字串的情況，message 為 None（不替規格發明字串）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Rule, authorize
from app.modules.reports.report_lifecycle import repo as lifecycle_repo
from app.modules.reports.report_lifecycle.service import ReportNotFound
from app.modules.reports.submit_a_daily_report import repo as reports_repo
from app.modules.reports.submit_a_daily_report import service as submit
from app.modules.review.custom_work_item import repo

# spec/appendix-b-fields.md（逐字）
MSG_NAME = "自訂工項名稱最多 100 個字"
MSG_QUANTITY = "自訂工項數量須為 0 到 999.9，最小單位 0.1"
MSG_PRICE = "自訂工項單價須為 0 或正整數"

ADMIN_RULE = Rule(roles={Role.ADMIN})  # OWNER 擁有 ADMIN 的全部權限（permissions.py）

FIELD_NAME = "custom_name"
FIELD_QUANTITY = "custom_quantity"
FIELD_PRICE = "custom_price"

MAX_NAME_CHARS = 100
# 單價只收半形數字；最多 9 位數（< 10 億）是儲存的上限（欄位是 32 位元整數），不是規格的業務規則。
_PRICE_RE = re.compile(r"^[0-9]{1,9}$")


@dataclass(frozen=True)
class CustomItem:
    name: str
    tenths: int  # 0.1 只的整數
    price: int  # 每 1.0 只的整數元

    def text(self) -> str:
        return f"{self.name} {_tenths(self.tenths)} 只 × {self.price}"


@dataclass(frozen=True)
class Saved:
    report_id: int
    report_date_text: str
    previous_status: str
    item: CustomItem | None  # None = 移除後沒有自訂工項
    changed: bool  # 自訂工項有沒有真的變


def _tenths(value: int) -> str:
    return f"{value // 10}.{value % 10}"


# ───────────────────────── 欄位 ─────────────────────────


def _once(form: dict[str, list[str]], field: str) -> str | None:
    """欄位出現恰好一次就回傳它的值；缺少或重複回傳 None（不補預設值、不猜哪一個才算數）。"""
    values = form.get(field, [])
    return values[0] if len(values) == 1 else None


def parse_custom_item(form: dict[str, list[str]]) -> CustomItem | None:
    """表單 → 自訂工項；名稱清空（移除）回傳 None。純函式：不讀資料庫、不讀時鐘。

    錯誤字串必須是本檔的字串常數（`strings` 檢查要逐字讀出），所以每個 `OutcomeError` 都直接寫常數。
    """
    raw_name = _once(form, FIELD_NAME)
    if raw_name is None:
        raise OutcomeError(Outcome.INVALID)  # 附錄 B 沒有「缺少名稱欄位」的字串
    name = raw_name.strip()
    if name == "":
        return None  # REV-R21：清空名稱就是移除，數量與單價不看
    if len(name) > MAX_NAME_CHARS:  # 字數，不是位元組：全形字也算一個字
        raise OutcomeError(Outcome.INVALID, MSG_NAME)
    raw_quantity, raw_price = _once(form, FIELD_QUANTITY), _once(form, FIELD_PRICE)
    if raw_quantity is None:
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)
    tenths = _parse_quantity(raw_quantity)
    if raw_price is None:
        raise OutcomeError(Outcome.INVALID, MSG_PRICE)
    return CustomItem(name, tenths, _parse_price(raw_price))


def _parse_quantity(raw: str) -> int:
    """0–999.9、0.1 的倍數，回傳 tenths。解析重用 T-201 的 `parse_quantity`（不用浮點數），只換成自訂工項的錯誤字串，
    並且空白不是 0：自訂工項的數量在有名稱時必填。"""
    if raw.strip() == "":
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)
    try:
        return submit.parse_quantity(raw)
    except OutcomeError:
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY) from None


def _parse_price(raw: str) -> int:
    text = raw.strip()
    if not _PRICE_RE.match(text):  # 負號、小數（99.5）、空白、字母、千分位都不合法
        raise OutcomeError(Outcome.INVALID, MSG_PRICE)
    return int(text)


# ───────────────────────── 儲存 ─────────────────────────


def current_item(report: reports_repo.Report) -> CustomItem | None:
    if report.custom_name is None:
        return None
    return CustomItem(report.custom_name, report.custom_tenths, report.custom_price)


def save_custom_item(conn: psycopg.Connection, actor: Actor, report_id: int, form: dict[str, list[str]]) -> Saved:
    """附加、取代或移除一張回報的自訂工項。通過回傳 `Saved`；否則丟 OutcomeError / ReportNotFound，**沒有任何資料被寫入**
    （transaction 回滾；FORBIDDEN 的 ACCESS_DENIED 除外）。"""
    try:
        report = lifecycle_repo.lock_report(conn, report_id)  # 與 T-202、T-301 同一把鎖
        if report is None:
            raise ReportNotFound(report_id)
        authorize(actor, f"change the custom item of report #{report.id}", ADMIN_RULE)

        item = parse_custom_item(form)
        before = current_item(report)
        saved = Saved(report.id, report.report_date.isoformat(), report.status, item, changed=item != before)
        if not saved.changed:
            conn.rollback()  # 什麼都沒寫；放掉鎖
            return saved
        # D-112：改完之後回報要還有至少一個數量 > 0（一般工項，或這個自訂工項）
        submit.require_a_quantity(report.items, None if item is None else item.tenths)

        now = clock.now()
        if item is None:
            repo.clear_custom_item(conn, report.id, now)
        else:
            repo.set_custom_item(conn, report.id, item.name, item.tenths, item.price, now)
        if report.status != "PENDING":  # AD-10、REV-R24：等同管理員編輯
            reports_repo.set_report_status(conn, report.id, "PENDING", now)
            lifecycle_repo.discard_review(conn, report.id)  # T-301：刪除份額（兩張表）、清掉審核者
        if report.status == "CONFIRMED":
            audit.write(actor, "REPORT_UNCONFIRM", f"日報 #{report.id} 由 CONFIRMED 退回 PENDING：管理員改自訂工項，已確認的結果作廢", conn=conn)
        audit.write(actor, "REPORT_UPDATE", _describe(report, before, item), conn=conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return saved


def _describe(report: reports_repo.Report, before: CustomItem | None, after: CustomItem | None) -> str:
    text = f"自訂工項 日報 #{report.id}（{report.report_date.isoformat()}，{report.catalogue}）："
    text += f"{before.text() if before else '無'}→{after.text() if after else '無'}"
    if report.status != "PENDING":
        text += f"；狀態 {report.status}→PENDING"
    return text
