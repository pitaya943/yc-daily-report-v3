"""時鐘：產品程式取得「現在」的唯一入口。

設計：
- 產品程式（app/**）不得呼叫 datetime.now()、time.time() 或 SQL 的 now()；一律用 `clock.now()`。
  tests/unit/test_clock.py 會掃描 app/ 強制這一點。
- 測試用 `set()` 凍結時間、`advance()` 推進時間（鎖定 15 分鐘、23:59 排程、跨年等 scenario 都需要）。
- 沒有被 `set()` 時跟隨真實時間，所以正式執行不需要任何設定。
- 一律回傳帶時區的 datetime，時區固定 Asia/Taipei（spec/background.md）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


class Clock:
    def __init__(self) -> None:
        self._frozen: datetime | None = None

    def now(self) -> datetime:
        if self._frozen is not None:
            return self._frozen
        # 整個 app 唯一允許讀系統時間的地方
        return datetime.now(timezone.utc).astimezone(TAIPEI)

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("clock.set() requires a timezone-aware datetime")
        self._frozen = when.astimezone(TAIPEI)

    def advance(self, delta: timedelta) -> None:
        self._frozen = self.now() + delta

    def reset(self) -> None:
        """回到跟隨真實時間。"""
        self._frozen = None


# 行程內唯一的時鐘；測試與產品程式共用同一個實例。
clock = Clock()
