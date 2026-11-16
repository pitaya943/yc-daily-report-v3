"""把 IAM-F01 的步驟註冊成全域 plugin。

為什麼不直接把步驟寫在 conftest.py：scenario 是由 tests/test_spec.py 展開的，子目錄的 conftest 的 fixture
只對該目錄底下的測試可見，test_spec.py 看不到，IAM-R01～R03 會變成「找不到步驟」。
`pytest_configure` 在 D-046 的 hook 允許清單內；註冊的是靜態 import 的模組，沒有動態載入。
注意：只跑 `tests/test_spec.py` 這一個檔案時不會載入這個 conftest；請跑完整的 `python3 -m pytest`。
"""
import iam_f01_steps


def pytest_configure(config):
    config.pluginmanager.register(iam_f01_steps, "iam_f01_steps")
