"""送出日報的規則（RPT-F01：R01～R07）。

驗證函式是純函式（不讀資料庫、不讀時鐘），日期與「今天」由呼叫端傳入，所以 T-202（編輯）可以直接重用：

    parse_report_date(raw, today)            RPT-R02
    parse_quantity(raw)                      RPT-R03
    parse_quantities(fields, catalogue)      RPT-R01、R03
    resolve_collaborators(conn, submitter, raw_ids)   RPT-R05
    submit_report(conn, actor, form)         RPT-R04、R06、R07（整個送出，含稽核）

## 伺服器重新驗證每個欄位（AGENTS.md 不可違反 #6）

沒有任何預設值：缺少 `report_date`（UI 的預設「今天」只在表單上）是 `INVALID`，不會被補成今天。
「空白數量視為 0」是規格寫的規則（RPT-R03），不是預設值：送出的空白欄位存成 0；沒有送出的工項不存。

## 錯誤字串

逐字出自 spec/appendix-b-fields.md。附錄 B 沒有為「不在工項組內的工項」寫字串，所以那個 `INVALID` 的 message 是 None
（不替規格發明字串）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Rule, authorize
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo

# spec/appendix-b-fields.md（逐字）
MSG_DATE = "回報日期須為今天或往前 30 天內，不可選擇未來日期"
MSG_QUANTITY = "工項數量須為 0 到 999.9，最小單位 0.1"
MSG_COLLABORATORS = "共同作業者最多 6 人，且須為同一區域、同一類型的啟用員工"
MSG_DAILY_CAP = "每日最多只能送出 3 筆回報"

# spec/appendix-a-catalogues.md「A.4 預設設定」：固定值，不是可設定的
MAX_BACK_DAYS = 30
DAILY_CAP = 3
MAX_COLLABORATORS = 6
MAX_TENTHS = 9999  # 999.9 只

FIELD_DATE = "report_date"
FIELD_COLLABORATOR = "collaborator"

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
# 只收半形數字：Python 的 \d 也會比對全形與其他文字的數字
_QTY_RE = re.compile(r"^([0-9]{1,6})(?:\.([0-9]{1,6}))?$")
_ID_RE = re.compile(r"^[0-9]{1,18}$")  # 帳戶 id（bigint 的位數內）

SUBMITTER_RULE = Rule(roles={Role.USER})  # RPT-R06：只有 USER 填日報；ADMIN、OWNER 不填


# ───────────────────────── 純函式的欄位驗證 ─────────────────────────


def parse_report_date(raw: str | None, today: date) -> date:
    """RPT-R02：今天或往前 30 天內，不可為未來。格式只收 YYYY-MM-DD。缺少或格式錯誤也是同一個 INVALID。"""
    text = (raw or "").strip()
    if not _DATE_RE.match(text):
        raise OutcomeError(Outcome.INVALID, MSG_DATE)
    try:
        parsed = date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:  # 2026-02-30 這類不存在的日期
        raise OutcomeError(Outcome.INVALID, MSG_DATE) from None
    if parsed > today or parsed < today - timedelta(days=MAX_BACK_DAYS):
        raise OutcomeError(Outcome.INVALID, MSG_DATE)
    return parsed


def parse_quantity(raw: str | None) -> int:
    """RPT-R03：0～999.9、0.1 的倍數；空白視為 0。回傳 0.1 只的整數（2.3 → 23）。

    不用浮點數：先把字串拆成整數與小數兩段，小數第一位進位成 tenths，第二位起必須全是 0（`1.0`、`1.00` 合法，`0.05` 不合法）。
    """
    text = (raw or "").strip()
    if text == "":
        return 0
    m = _QTY_RE.match(text)
    if m is None:  # 負號、字母、1,000、科學記號、空小數（`1.`、`.5`）都不合法
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)
    whole, fraction = int(m.group(1)), m.group(2) or ""
    if fraction[1:].strip("0") != "":
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)  # 小數第二位以後不是 0：不是 0.1 的倍數
    tenths = whole * 10 + (int(fraction[0]) if fraction else 0)
    if tenths > MAX_TENTHS:
        raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)
    return tenths


def parse_quantities(fields: dict[str, list[str]], catalogue_name: str) -> dict[str, int]:
    """送出的每個工項欄位 → {代碼: tenths}，依欄位出現的順序。

    欄位名稱就是工項代碼。不在這個人的工項組內的代碼（含別的工項組的、亂寫的）是 `INVALID`，不寫任何資料（RPT-R01）；
    附錄 B 沒有這個情況的字串，message 為 None。同一個欄位送兩次也是 `INVALID`（不猜哪一個才算數）。
    """
    allowed = cat.item_codes(catalogue_name)
    out: dict[str, int] = {}
    for code, values in fields.items():
        if code in (FIELD_DATE, FIELD_COLLABORATOR):
            continue
        if code not in allowed:
            raise OutcomeError(Outcome.INVALID)
        if len(values) != 1:
            raise OutcomeError(Outcome.INVALID, MSG_QUANTITY)
        out[code] = parse_quantity(values[0])
    return out


def resolve_collaborators(conn: psycopg.Connection, submitter: repo.Account, raw_ids: list[str]) -> list[int]:
    """RPT-R05：依提交者選的順序，留下符合資格的共同作業者的帳戶 id。

    不符資格的（不同區、不同類型、封存、非 USER、提交者自己、不存在、不是數字）**不被存入，也不是錯誤**：
    scenario 的 Then 是「the saved crew is "Wen"」，送出仍成功。同一個人重複選只留第一次。
    留下來的人數超過 6 才是 `INVALID`（附錄 B 的字串）。空白的選項（沒選人）略過。
    """
    candidates: list[int] = []
    for raw in raw_ids:
        text = raw.strip()
        if text == "":
            continue
        if _ID_RE.match(text):  # 只收純數字 id（半形）；其他一律當作不符資格
            candidates.append(int(text))
    eligible = repo.eligible_collaborator_ids(conn, submitter, list(dict.fromkeys(candidates)))
    chosen = [i for i in dict.fromkeys(candidates) if i in eligible]
    if len(chosen) > MAX_COLLABORATORS:
        raise OutcomeError(Outcome.INVALID, MSG_COLLABORATORS)
    return chosen


# ───────────────────────── 送出 ─────────────────────────


@dataclass(frozen=True)
class Submitted:
    report_id: int
    report_date: date
    catalogue: str
    crew_size: int  # 提交者加共同作業者


def audit_description_for_create(report_id: int, report_date: date, catalogue_name: str, crew_size: int) -> str:
    """附錄 C：回報含共同作業者時，建立說明要有「共 N 人作業」。單人回報不寫這句。"""
    text = f"送出日報 #{report_id}（{report_date.isoformat()}，{catalogue_name}）"
    return text + (f"，共 {crew_size} 人作業" if crew_size > 1 else "")


def submit_report(conn: psycopg.Connection, actor: Actor, form: dict[str, list[str]]) -> Submitted:
    """送出一張日報。通過回傳；否則丟 OutcomeError，而且**沒有任何資料被寫入**（transaction 回滾）。

    順序（有意義）：
    1. 權限（RPT-R06）：ADMIN、OWNER → FORBIDDEN，並寫 ACCESS_DENIED（authorize 內，獨立連線）。權限先於欄位驗證，
       所以管理員送出任何內容都只得到 FORBIDDEN，不會因為內容而洩漏欄位規則。
    2. 欄位（不碰資料庫的先做）：日期、工項、共同作業者。
    3. 每日上限（RPT-R04）：鎖住提交者 → 計數 → 寫入，在同一個 transaction，並行時也成立。
    4. 稽核 REPORT_CREATE 與資料同一個 transaction 提交（app/core/audit.py）。
    """
    authorize(actor, "submit a daily report", SUBMITTER_RULE)
    try:
        submitter = repo.get_account(conn, actor.id)
        if submitter is None or submitter.archived:  # 通常不會發生（session 檢查已擋）；fail-closed
            raise OutcomeError(Outcome.UNAUTHENTICATED)
        catalogue_name = cat.catalogue_name_for(submitter.zone, submitter.big_meter)

        values = form.get(FIELD_DATE, [])
        report_date = parse_report_date(values[0] if len(values) == 1 else None, clock.now().date())
        items = parse_quantities(form, catalogue_name)
        crew_ids = resolve_collaborators(conn, submitter, form.get(FIELD_COLLABORATOR, []))

        repo.lock_submitter(conn, submitter.id)
        if repo.count_own_reports(conn, submitter.id, report_date) >= DAILY_CAP:
            raise OutcomeError(Outcome.CONFLICT, MSG_DAILY_CAP)

        report_id = repo.insert_report(
            conn,
            submitter_id=submitter.id,
            report_date=report_date,
            catalogue=catalogue_name,
            status="PENDING",
            now=clock.now(),
            items=items,
            crew_ids=crew_ids,
        )
        crew_size = 1 + len(crew_ids)
        audit.write(actor, "REPORT_CREATE", audit_description_for_create(report_id, report_date, catalogue_name, crew_size), conn=conn)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return Submitted(report_id=report_id, report_date=report_date, catalogue=catalogue_name, crew_size=crew_size)
