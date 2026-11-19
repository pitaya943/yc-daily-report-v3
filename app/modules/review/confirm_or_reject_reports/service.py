"""確認或駁回回報（REV-F01：REV-R01、R02、R03）。

## 並行與鎖（ticket 完成條件 8）

確認與駁回在改變一張回報之前，先用 `report_lifecycle.repo.lock_report`（`select … from yc_v3.reports where id = %s for update`）
鎖住它，與 T-202 的編輯、刪除是**同一個函式**。鎖住之後才讀狀態，所以：
- 提交者的編輯與管理員的確認同時送出：後到的那個等前一個提交後才看狀態。先確認，編輯就看到 CONFIRMED（USER 被擋，FORBIDDEN）；
  先編輯，確認看到的是編輯後的內容，份額就依新的數量與小組存下。不會出現「確認後又被改掉內容，份額卻是舊數量」。
- 兩位管理員同時確認同一張回報：第二位等第一位提交後，看到 CONFIRMED，略過（REV-R02），份額不會存兩次。

批次依 id 由小到大逐筆上鎖（一個 transaction 內）。兩個批次若以不同順序鎖同一批回報會互相等待而死結；
所有批次都用升冪，等待的方向一致，就不會成環。

## 批次只處理仍是 PENDING 的列（REV-R02）

不是 PENDING（已確認、已駁回）或已不存在（例如提交者剛好刪除了）的 id 一律略過，不是錯誤，也不寫任何東西。
每張實際改變的回報寫一列稽核（`REPORT_CONFIRM` 或 `REPORT_REJECT`）；整個批次同一個 transaction，要嘛全部生效、要嘛全部不生效。
id 缺少或格式不對是 `INVALID`（附錄 B 沒有為它寫字串，所以 message 為 null，不替規格發明）。

## 取消確認不存在（REV-R03）

`POST /review/reports/{id}/unconfirm` 一律 `CONFLICT`、不帶錯誤字串、不寫任何資料。要讓已確認的回報回到 PENDING，
只有管理員編輯（RPT-R12）。
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
from app.modules.reports.submit_a_daily_report import repo as reports_repo
from app.modules.review.confirm_or_reject_reports import repo
from app.modules.review.crew_split_and_stored_shares import service as shares

ADMIN_RULE = Rule(roles={Role.ADMIN})  # OWNER 擁有 ADMIN 的全部權限（permissions.py）

FIELD_ID = "id"
MAX_IDS = 200  # 一次批次的上限

# 兩個佇列（REV-R01）：一般 = WEST 與 SOUTH，大表 = BIG_METER。依回報送出時記下的工項組分（AD-4）。
QUEUES: dict[str, tuple[str, ...]] = {"ordinary": ("WEST", "SOUTH"), "big-meter": ("BIG_METER",)}

_POSITIVE_INT = re.compile(r"^[1-9][0-9]{0,17}$")  # 只收半形數字、不收 0 與前導零


@dataclass(frozen=True)
class ReviewResult:
    decision: str  # CONFIRMED 或 REJECTED
    changed: list[int]  # 這次實際改變的回報 id（升冪）
    skipped: list[int]  # 略過的 id（不是 PENDING 或已不存在；升冪）


def parse_ids(form: dict[str, list[str]]) -> list[int]:
    """表單的 `id`（可重複）→ 不重複的升冪 id。沒有 id、或任何一個格式不對：INVALID，不補預設值。"""
    values = form.get(FIELD_ID, [])
    if not values or len(values) > MAX_IDS:
        raise OutcomeError(Outcome.INVALID)
    ids: set[int] = set()
    for raw in values:
        if not _POSITIVE_INT.match(raw.strip()):
            raise OutcomeError(Outcome.INVALID)
        ids.add(int(raw.strip()))
    return sorted(ids)


def _describe(report: reports_repo.Report) -> str:
    crew = f"，共 {len(report.crew) + 1} 人作業" if report.crew else ""
    return f"日報 #{report.id}（{report.report_date.isoformat()}，{report.catalogue}，提交者 {report.submitter_name}{crew}）"


def authorize_review(actor: Actor, decision: str) -> None:
    authorize(actor, "confirm reports" if decision == "CONFIRMED" else "reject reports", ADMIN_RULE)


def review_reports(conn: psycopg.Connection, actor: Actor, ids: list[int], decision: str) -> ReviewResult:
    """確認（decision = CONFIRMED）或駁回（REJECTED）這些回報。`ids` 必須是 `parse_ids` 的結果（升冪、不重複）。

    順序：權限 → 逐筆上鎖並處理 → 一次提交。沒有權限的人只得到 FORBIDDEN，不會因 id 的內容而得到不同的結果。
    """
    assert decision in ("CONFIRMED", "REJECTED") and ids == sorted(set(ids)), "呼叫端必須傳升冪、不重複的 id"
    verb = "確認" if decision == "CONFIRMED" else "駁回"
    audit_type = "REPORT_CONFIRM" if decision == "CONFIRMED" else "REPORT_REJECT"
    authorize_review(actor, decision)
    changed: list[int] = []
    skipped: list[int] = []
    try:
        for report_id in ids:  # 升冪：所有批次的上鎖方向一致，不會互相等待成環
            report = lifecycle_repo.lock_report(conn, report_id)  # 與 T-202 編輯、刪除同一把鎖
            if report is None or report.status != "PENDING":
                skipped.append(report_id)
                continue
            repo.mark_reviewed(conn, report.id, decision, actor.id, clock.now())
            if decision == "CONFIRMED":
                shares.store_shares(conn, report)  # 與狀態同一個 transaction：沒有「已確認卻沒有份額」的瞬間
            audit.write(actor, audit_type, f"{verb}{_describe(report)}", conn=conn)
            changed.append(report.id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return ReviewResult(decision, changed, skipped)


def unconfirm(actor: Actor, report_id: int) -> None:
    """REV-R03：佇列上沒有取消確認。管理員一律 CONFLICT，不帶字串、不讀不寫資料。"""
    authorize(actor, f"unconfirm report #{report_id} from the queue", ADMIN_RULE)
    raise OutcomeError(Outcome.CONFLICT)


def queue(conn: psycopg.Connection, name: str) -> list[tuple[str, list[reports_repo.Report]]]:
    """佇列內容：依工項組分組 [(工項組, [回報…])]。沒有回報的工項組也列出（空清單），畫面才有固定的分區。"""
    catalogues = QUEUES[name]
    pending = repo.pending_reports(conn, catalogues)
    return [(c, [r for r in pending if r.catalogue == c]) for c in catalogues]
