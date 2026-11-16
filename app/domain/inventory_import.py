"""庫存比對（MAT-R20）與暫存區解決（MAT-R21、AD-6）：純函式，不讀資料庫、不讀時鐘。

名詞：A = 系統現況，B = 上傳檔，x = B.received - A.received。
數量以 tenth（0.1 只）的整數計，不使用浮點數。
不變式：received == cumulative + remaining。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.outcomes import Outcome

# AD-6 規格定義的完整錯誤字串，逐字不可改。
B_INCONSISTENT_MESSAGE = "B 系統數值不一致，無法採用"

Decision = Literal["applied", "quarantined"]
# "-" 無疑點；"?" x < 0（無法判斷哪邊錯）；"A" 系統現況壞；"B" 上傳檔與預期不符。
Fault = Literal["-", "?", "A", "B"]
Choice = Literal["trust A", "trust B"]


@dataclass(frozen=True)
class Stock:
    received: int
    cumulative: int
    remaining: int

    def is_consistent(self) -> bool:
        return self.received == self.cumulative + self.remaining


@dataclass(frozen=True)
class ImportResult:
    decision: Decision
    fault: Fault
    stock: Stock  # 比對後系統的庫存：套用時為新值，隔離時為原 A


@dataclass(frozen=True)
class ResolveResult:
    stock: Stock
    quarantined: bool
    audit: str | None = None
    outcome: Outcome | None = None  # 拒絕時的結果類別；成功為 None
    message: str | None = None


def expected_after_inbound(a: Stock, b: Stock) -> Stock:
    """預期更新後的 A：received + x、remaining + x、cumulative 不變。"""
    x = b.received - a.received
    return Stock(a.received + x, a.cumulative, a.remaining + x)


def decide_import(a: Stock, b: Stock) -> ImportResult:
    """MAT-R20：A 一致、x >= 0、且 B 等於預期的 A 時才套用，否則隔離（A 不動）。

    判斷順序即疑點優先順序：先看 A（A 壞時 B 怎樣都不可信），再看 x，最後看 B。
    """
    if not a.is_consistent():
        return ImportResult("quarantined", "A", a)
    if b.received - a.received < 0:
        return ImportResult("quarantined", "?", a)
    expected = expected_after_inbound(a, b)
    if b != expected:
        return ImportResult("quarantined", "B", a)
    return ImportResult("applied", "-", expected)


def resolve_quarantine(choice: Choice, a: Stock, b: Stock) -> ResolveResult:
    """MAT-R21：解決暫存列，結果必須回到不變式。

    - trust A：A 依 x 更新（B 的 cumulative 不採用），稽核 MATERIAL_KEEP_A。
    - trust B：採用 B，稽核 MATERIAL_SYNC_B；B 不合不變式時拒絕 CONFLICT（AD-6），
      列留在暫存區、資料不變、不寫稽核。

    spec 沒有定義「信任 A 但 x < 0 或 A 本身不一致」的結果，這裡不猜；
    該情況由呼叫端（T-504 之後）依 Kuei 的決定處理。
    """
    if choice == "trust A":
        return ResolveResult(expected_after_inbound(a, b), False, "MATERIAL_KEEP_A")
    if choice == "trust B":
        if not b.is_consistent():
            return ResolveResult(
                a, True, None, Outcome.CONFLICT, B_INCONSISTENT_MESSAGE
            )
        return ResolveResult(b, False, "MATERIAL_SYNC_B")
    raise ValueError(f"unknown choice: {choice!r}")
