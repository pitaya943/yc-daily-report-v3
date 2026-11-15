"""tests/unit/conftest.py 把 `world` 關掉（純單元測試不碰資料庫）。
app/core 的稽核與權限要寫資料庫，所以這個目錄把 `world` 開回來：行為與 tests/conftest.py 相同
（清空 yc_v3、載入 background、固定時鐘）。純函式的測試不受影響，只是多花幾毫秒。
"""
import pytest

from app.core.clock import clock
from tests.conftest import _truncate_all, load_background


@pytest.fixture(autouse=True)
def world(db):
    _truncate_all(db)
    load_background(db)
    yield
    clock.reset()
