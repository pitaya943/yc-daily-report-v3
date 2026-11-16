"""結果類別（spec/README.md「結果類別」表，AD-9）。

規格不規定 API，用與傳輸層無關的結果類別描述拒絕；這裡把它們綁到 HTTP status，
並提供統一的例外 `OutcomeError` 與 FastAPI 的 exception handler。

設計：
- 業務程式一律 `raise OutcomeError(Outcome.X, "完整錯誤字串")`，不自己組 HTTP 回應；
  這樣「類別 → status → 回應格式」只有一個出口，測試斷言（類別、完整字串）才有一致的形狀。
- 錯誤字串由呼叫端傳入，字串逐字出自 spec/appendix-b-fields.md。這裡**不替 spec 沒寫的情況發明字串**：
  spec 沒有為 FORBIDDEN、UNAUTHENTICATED（未登入）等寫訊息，所以 message 可以是 None，回應的 `message` 為 null。
- 「要不要寫稽核」不在這裡決定：FORBIDDEN 的 ACCESS_DENIED 在 `permissions.authorize()` 寫（那裡才知道行為者與動作），
  LOCKED 的 ACCOUNT_LOCKOUT 在「鎖定當下」寫（不是每次被拒絕都寫），屬於登入 feature。
"""
from __future__ import annotations

from enum import Enum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class Outcome(str, Enum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    INVALID = "INVALID"
    CONFLICT = "CONFLICT"
    LOCKED = "LOCKED"
    RATE_LIMITED = "RATE_LIMITED"
    BLOCKED = "BLOCKED"

    @property
    def http_status(self) -> int:
        return _HTTP_STATUS[self]


# spec/README.md 的表。tests/unit/core/test_outcomes.py 會從 spec 解析同一張表逐列比對。
_HTTP_STATUS: dict[Outcome, int] = {
    Outcome.UNAUTHENTICATED: 401,
    Outcome.FORBIDDEN: 403,
    Outcome.INVALID: 422,
    Outcome.CONFLICT: 409,
    Outcome.LOCKED: 423,
    Outcome.RATE_LIMITED: 429,
    Outcome.BLOCKED: 409,
}


class OutcomeError(Exception):
    """以結果類別拒絕一個請求。`message` 是 spec 規定的完整錯誤字串；spec 沒寫字串時為 None。"""

    def __init__(self, outcome: Outcome, message: str | None = None) -> None:
        super().__init__(f"{outcome.value}: {message}" if message else outcome.value)
        self.outcome = outcome
        self.message = message


async def _handle_outcome_error(_: Request, exc: OutcomeError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.outcome.http_status,
        content={"outcome": exc.outcome.value, "message": exc.message},
    )


def register_outcome_handlers(app: FastAPI) -> None:
    app.add_exception_handler(OutcomeError, _handle_outcome_error)
