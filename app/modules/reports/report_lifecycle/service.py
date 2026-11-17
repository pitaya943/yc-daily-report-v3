"""回報生命週期的規則（RPT-F02：R10 編輯與刪除的權限、R11 編輯的內容與稽核、R13 刪除；R12 的份額由 T-301 補）。

欄位驗證**重用** T-201 的 `submit_a_daily_report.service`（parse_quantities、resolve_collaborators、MSG_DATE）與
`catalogue`，這裡只加編輯特有的規則：回報日期不能改（AD-8）、工項組沿用送出時記下的（AD-4）、狀態一律回到 PENDING。

## 權限（RPT-R10，spec/state-machines.md §回報）

| 誰 | PENDING | REJECTED | CONFIRMED |
| --- | --- | --- | --- |
| 提交者（USER） | 編輯、刪除 | 編輯、刪除 | FORBIDDEN |
| 共同作業者、其他 USER | FORBIDDEN | FORBIDDEN | FORBIDDEN |
| ADMIN、OWNER | 編輯、刪除 | 編輯、刪除 | 編輯（→ PENDING，份額作廢）、刪除 |

寫成兩條 `Rule`（管理員，或自己的、尚未確認的回報），不是一個塞滿旗標的判斷（app/core/permissions.py）。
被拒絕時 `authorize` 先寫 ACCESS_DENIED（獨立連線），再丟 FORBIDDEN。

## 順序（有意義）

鎖列 → 權限 → 欄位驗證 → 寫入與稽核同一個 transaction。權限先於欄位驗證，所以沒有權限的人不論送什麼，
只會得到 FORBIDDEN，不會因為內容而探到欄位規則。回報不存在是 `ReportNotFound`（規格沒有這個結果類別，router 回 404）。

## 伺服器重新驗證每個欄位（AGENTS.md 不可違反 #6）

`report_date` 必須出現一次，而且等於已存的日期；缺少或格式錯誤不補成已存的日期，直接 INVALID。
沒有送出的工項不存（與 T-201 相同）；編輯是「以送出的內容整個取代」，不是只改有送出的那幾個。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Resource, Rule, authorize
from app.modules.reports.report_lifecycle import repo as lifecycle_repo
from app.modules.reports.submit_a_daily_report import repo
from app.modules.reports.submit_a_daily_report import service as submit

# spec/appendix-b-fields.md（逐字）。`strings` 檢查要求傳給 OutcomeError 的是本檔的字串常數，所以 MSG_DATE 在這裡再寫一次
# （與 T-201 的 submit.MSG_DATE 相同；test_lifecycle_details 會比對兩者相等）。
MSG_DATE = "回報日期須為今天或往前 30 天內，不可選擇未來日期"
MSG_DATE_LOCKED = "回報日期送出後不可修改"  # 編輯時的回報日期（AD-8）

FIELD_DATE = submit.FIELD_DATE

ADMIN_RULE = Rule(roles={Role.ADMIN})  # OWNER 擁有 ADMIN 的全部權限（permissions.py）
OWN_UNCONFIRMED_RULE = Rule(roles={Role.USER}, owner_only=True, states={"PENDING", "REJECTED"})

_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")  # 只收半形數字


class ReportNotFound(Exception):
    """沒有這張回報（規格沒有「找不到」的結果類別；router 回 404）。"""


@dataclass(frozen=True)
class Edited:
    report_id: int
    report_date: date
    previous_status: str
    changed: bool  # 內容（工項數量或作業小組）有沒有變


# ───────────────────────── 權限 ─────────────────────────


def authorize_change(actor: Actor, report: repo.Report, action: str) -> None:
    """RPT-R10：通過就回傳；否則寫 ACCESS_DENIED 並丟 FORBIDDEN。編輯與刪除共用同一組規則。"""
    authorize(
        actor,
        f"{action}（日報 #{report.id}，狀態 {report.status}）",
        ADMIN_RULE,
        OWN_UNCONFIRMED_RULE,
        resource=Resource(owner_id=report.submitter_id, state=report.status),
    )


def load_for_change(conn: psycopg.Connection, actor: Actor, report_id: int, action: str) -> repo.Report:
    """讀一張回報並檢查權限（打開編輯頁用；不鎖列、不寫入）。"""
    report = repo.get_report(conn, report_id)
    if report is None:
        raise ReportNotFound(report_id)
    authorize_change(actor, report, action)
    return report


# ───────────────────────── 欄位 ─────────────────────────


def check_report_date_unchanged(form: dict[str, list[str]], stored: date) -> None:
    """RPT-R11（AD-8）：編輯不能改回報日期。

    不呼叫 T-201 的 `parse_report_date`：它檢查「今天或往前 30 天內」，而這張回報可能是更早之前送出的，
    編輯它不該因為日期太舊而失敗。這裡只要求格式正確且等於已存的日期。
    """
    values = form.get(FIELD_DATE, [])
    text = values[0].strip() if len(values) == 1 else ""
    if not _ISO_DATE.match(text):
        raise OutcomeError(Outcome.INVALID, MSG_DATE)  # 缺少、重複或格式錯誤：不補預設值
    try:
        parsed = date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:  # 2026-02-30 這類不存在的日期
        raise OutcomeError(Outcome.INVALID, MSG_DATE) from None
    if parsed != stored:
        raise OutcomeError(Outcome.INVALID, MSG_DATE_LOCKED)


def _tenths(value: int) -> str:
    return f"{value // 10}.{value % 10}"


def describe_changes(
    old_items: dict[str, int], new_items: dict[str, int], old_crew: list[str], new_crew: list[str]
) -> list[str]:
    """內容的差異，給稽核說明用。沒送出的工項與 0 視為相同：表單送出時空白欄位存成 0，不該因此變成「有變更」。"""
    changes = []
    for code in sorted(set(old_items) | set(new_items)):
        before, after = old_items.get(code, 0), new_items.get(code, 0)
        if before != after:
            changes.append(f"{code} {_tenths(before)}→{_tenths(after)}")
    if old_crew != new_crew:
        changes.append(f"共同作業者 {'、'.join(old_crew) or '無'}→{'、'.join(new_crew) or '無'}")
    return changes


def audit_description_for_update(report: repo.Report, changes: list[str]) -> str:
    text = f"編輯日報 #{report.id}（{report.report_date.isoformat()}，{report.catalogue}）："
    text += "；".join(changes) if changes else "無變更"
    if report.status != "PENDING":
        text += f"；狀態 {report.status}→PENDING"
    return text


# ───────────────────────── 編輯 ─────────────────────────


def edit_report(conn: psycopg.Connection, actor: Actor, report_id: int, form: dict[str, list[str]]) -> Edited:
    """編輯一張回報：以送出的內容取代工項數量與作業小組，狀態回到 PENDING（RPT-R10、R11）。

    - 不佔額度（RPT-R11）：沒有任何「每日 3 筆」的檢查或計數，回報的筆數不變。
    - CONFIRMED 的回報只有管理員能編輯；編輯後回到 PENDING，寫 REPORT_UNCONFIRM 與 REPORT_UPDATE 兩筆（狀態機）。
    - 通過回傳；否則丟 OutcomeError / ReportNotFound，而且**沒有任何資料被寫入**（transaction 回滾；ACCESS_DENIED 除外）。
    """
    try:
        report = lifecycle_repo.lock_report(conn, report_id)
        if report is None:
            raise ReportNotFound(report_id)
        authorize_change(actor, report, "edit a report")

        check_report_date_unchanged(form, report.report_date)
        # 工項組沿用送出時記下的（AD-4）：之後帳戶改區域，這張回報的工項組不變
        items = submit.parse_quantities({k: v for k, v in form.items() if k != FIELD_DATE}, report.catalogue)
        submit.require_a_quantity(items, report.custom_tenths)  # RPT-R14：與送出同一份判斷；已存的自訂工項數量也算
        submitter = repo.get_account(conn, report.submitter_id)
        crew_ids = submit.resolve_collaborators(conn, submitter, form.get(submit.FIELD_COLLABORATOR, []))

        names = lifecycle_repo.account_names(conn, crew_ids)
        changes = describe_changes(report.items, items, [n for _, n in report.crew], [names[i] for i in crew_ids])

        repo.replace_report_content(conn, report.id, items=items, crew_ids=crew_ids, status="PENDING", now=clock.now())
        if report.status == "CONFIRMED":
            # T-301（D-085）：份額表建立後，在這裡刪除這張回報的份額（RPT-R12 的 "has no stored shares"）。
            audit.write(actor, "REPORT_UNCONFIRM", f"日報 #{report.id} 由 CONFIRMED 退回 PENDING：管理員編輯，已確認的結果作廢", conn=conn)
        audit.write(actor, "REPORT_UPDATE", audit_description_for_update(report, changes), conn=conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return Edited(report.id, report.report_date, report.status, bool(changes))


# ───────────────────────── 刪除 ─────────────────────────


def delete_report(conn: psycopg.Connection, actor: Actor, report_id: int) -> repo.Report:
    """永久刪除一張回報（RPT-R13）：工項與作業小組隨之刪除，當天的額度釋放（RPT-R04）；稽核與刪除同一個 transaction。"""
    try:
        report = lifecycle_repo.lock_report(conn, report_id)
        if report is None:
            raise ReportNotFound(report_id)
        authorize_change(actor, report, "delete a report")
        deleted = repo.delete_report(conn, report.id)
        assert deleted, "已鎖住的回報應該刪得掉"
        audit.write(
            actor,
            "REPORT_DELETE",
            f"刪除日報 #{report.id}（{report.report_date.isoformat()}，{report.catalogue}，提交者 {report.submitter_name}，原狀態 {report.status}）",
            conn=conn,
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return report
