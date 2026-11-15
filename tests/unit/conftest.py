import pytest


@pytest.fixture(autouse=True)
def world():
    """單元測試不碰資料庫：覆寫 tests/conftest.py 的 autouse fixture。"""
    yield
