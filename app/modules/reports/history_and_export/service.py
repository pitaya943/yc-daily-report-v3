"""歷史與匯出的規則（RPT-R20～R23）：誰看得到哪些回報、篩選值的驗證、畫面與匯出的列。

只讀。讀取回報重用 T-201 的 `repo.list_reports`；工項顯示名稱重用 `catalogue.py`。

設計取捨（見 PR 說明）：
- 篩選在 Python 做（日期交給 SQL）：`list_reports` 已經依日期、提交者、共同作業者過濾，區域與「有自訂工項」
  是少數幾個欄位的比較，不值得為此複製一份 SQL。代價：管理員的歷史會先載入日期範圍內的全部回報再濾；
  規格沒有分頁，這個團隊每日只有數十張。要分頁時把這裡改成 SQL。
- 所有篩選值嚴格驗證，不修正、不補預設值：未知的參數、重複的參數、前後空白、全形數字一律 INVALID。空字串 = 沒有篩選
  （附錄 B：「有效日期或清單內的值，或空白」），HTMX 表單的空欄位會送出空字串。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from app.core.actor import Actor
from app.core.outcomes import Outcome, OutcomeError
from app.core.actor import Role
from app.core.permissions import Rule
from app.modules.reports.history_and_export import repo as history_repo
from app.modules.reports.submit_a_daily_report import catalogue as cat
from app.modules.reports.submit_a_daily_report import repo
from app.modules.reports.submit_a_daily_report.repo import Report

MSG_FILTER = "請輸入有效的篩選條件"  # spec/appendix-b-fields.md「篩選條件」

USER_RULE = Rule(roles={Role.USER})  # 自己的歷史：只有 USER（ADMIN、OWNER 不填日報）
ADMIN_RULE = Rule(roles={Role.ADMIN})  # OWNER 擁有 ADMIN 的全部權限（permissions.py）

# RPT-R20 的三個狀態用語
STATUS_WORDING = {"PENDING": "未確認", "CONFIRMED": "已確認", "REJECTED": "已駁回"}

ZONES = frozenset({cat.WEST, cat.SOUTH})
# 各頁接受的查詢參數；其他一律 INVALID
USER_PARAMS = frozenset({"date_from", "date_to", "has_custom"})
ADMIN_PARAMS = USER_PARAMS | {"zone", "account"}

# 兩個管理員頁面（D-090）：頁面 → 它涵蓋的工項組
ADMIN_PAGES: dict[str, tuple[str, ...]] = {"ordinary": (cat.WEST, cat.SOUTH), "big-meter": (cat.BIG_METER,)}

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # 不用 date.fromisoformat：它也收 "20261110" 與其他寫法


@dataclass(frozen=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    zone: str | None = None
    account_name: str | None = None
    account_id: int | None = None
    has_custom: bool = False

    def query(self) -> dict[str, str]:
        """回到查詢字串的形式（匯出連結與稽核說明用）。只含有設定的條件。"""
        out: dict[str, str] = {}
        if self.date_from:
            out["date_from"] = self.date_from.isoformat()
        if self.date_to:
            out["date_to"] = self.date_to.isoformat()
        if self.zone:
            out["zone"] = self.zone
        if self.account_name:
            out["account"] = self.account_name
        if self.has_custom:
            out["has_custom"] = "1"
        return out


def _invalid() -> OutcomeError:
    return OutcomeError(Outcome.INVALID, MSG_FILTER)


def _parse_date(raw: str) -> date:
    if not _ISO_DATE.fullmatch(raw):
        raise _invalid()
    try:
        return date.fromisoformat(raw)
    except ValueError:  # 2026-13-40、2026-02-30
        raise _invalid() from None


def parse_filters(conn: psycopg.Connection, params: list[tuple[str, str]], allowed: frozenset[str]) -> Filters:
    """查詢字串 → 篩選條件；任何一項無效就整個拒絕（RPT-R23）。`params` 是（名稱, 值）依出現順序。"""
    seen: dict[str, str] = {}
    for key, value in params:
        if key not in allowed or key in seen:  # 未知的參數、重複的參數
            raise _invalid()
        seen[key] = value
    values = {k: v for k, v in seen.items() if v != ""}  # 空字串 = 沒有篩選
    date_from = _parse_date(values["date_from"]) if "date_from" in values else None
    date_to = _parse_date(values["date_to"]) if "date_to" in values else None
    if date_from and date_to and date_from > date_to:
        raise _invalid()
    zone = values.get("zone")
    if zone is not None and zone not in ZONES:
        raise _invalid()
    has_custom = values.get("has_custom")
    if has_custom is not None and has_custom != "1":
        raise _invalid()
    account_name = values.get("account")
    account_id = None
    if account_name is not None:
        account_id = history_repo.find_user_by_name(conn, account_name)
        if account_id is None:
            raise _invalid()
    return Filters(date_from, date_to, zone, account_name, account_id, has_custom is not None)


# ───────────────────────── 誰看得到哪些回報 ─────────────────────────


def user_history(conn: psycopg.Connection, actor: Actor, f: Filters) -> list[Report]:
    """RPT-R20：自己送出的，加上自己是共同作業者的；日期新到舊。"""
    reports = repo.list_reports(conn, submitter_id=actor.id, collaborator_id=actor.id, date_from=f.date_from, date_to=f.date_to)
    return [r for r in reports if not f.has_custom or r.custom_name is not None]


def admin_history(conn: psycopg.Connection, page: str, f: Filters) -> list[Report]:
    """RPT-R21：一般頁 = WEST、SOUTH 工項組的回報；大表頁 = BIG_METER 工項組的回報（依回報送出時記下的工項組，AD-4）。
    帳戶篩選含「該帳戶是共同作業者」的回報（例：篩 Wen，會有 Wei 送出、Wen 共同作業的那張）。"""
    catalogues = ADMIN_PAGES[page]
    reports = repo.list_reports(
        conn, submitter_id=f.account_id, collaborator_id=f.account_id, date_from=f.date_from, date_to=f.date_to
    )
    reports = [r for r in reports if r.catalogue in catalogues]
    if f.zone is not None:
        if page == "ordinary":
            # RPT-R24（D-100）：依回報送出時記下的工項組（AD-4）；帳戶之後換區域，舊回報仍留在原本那一區
            reports = [r for r in reports if r.catalogue == f.zone]
        else:
            # 大表頁：回報的工項組是 BIG_METER，不含區域，維持依提交者目前的區域（D-100）
            zones = history_repo.zones_by_account(conn, {r.submitter_id for r in reports})
            reports = [r for r in reports if zones.get(r.submitter_id) == f.zone]
    return [r for r in reports if not f.has_custom or r.custom_name is not None]


# ───────────────────────── 畫面與匯出的列 ─────────────────────────


def format_tenths(tenths: int) -> str:
    """0.1 只的整數 → 「2.3」。全程整數運算，不經過浮點數。"""
    return f"{tenths // 10}.{tenths % 10}"


def tenths_to_decimal(tenths: int) -> Decimal:
    return Decimal(tenths).scaleb(-1)


def role_label(report: Report, viewer: Actor | None) -> str:
    """USER 歷史的「身分」標籤：自己送出 / 共作（<提交者> 回報）。管理員頁不是任何人的共作，標籤留空。"""
    if viewer is None:
        return ""
    if report.submitter_id == viewer.id:
        return "自己送出"
    return f"共作（{report.submitter_name} 回報）"


def item_texts(report: Report) -> list[str]:
    """這張回報填了哪些工項：「顯示名稱 數量」，依工項組的順序。"""
    return [
        f"{item.display_name} {format_tenths(report.items[item.code])}"
        for item in cat.catalogue(report.catalogue)
        if item.code in report.items
    ]


def custom_text(report: Report) -> str:
    if report.custom_name is None:
        return ""
    return f"{report.custom_name} {format_tenths(report.custom_tenths)} 只 × {report.custom_price}"


def item_columns(catalogue_names: list[str]) -> list[str]:
    """匯出的工項欄位：多個工項組的聯集，依顯示名稱合併（WEST 與 SOUTH 的「直總-13」是同一欄）。
    順序：先依序走第一個工項組，之後工項組才有的接在後面。"""
    out: list[str] = []
    for name in catalogue_names:
        for item in cat.catalogue(name):
            if item.display_name not in out:
                out.append(item.display_name)
    return out
