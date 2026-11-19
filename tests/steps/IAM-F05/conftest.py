"""把 IAM-F05 的步驟註冊成全域 plugin（原因見 tests/steps/IAM-F01/conftest.py 與 pitfall #26）。

只跑 `tests/test_spec.py` 一個檔案時不會載入這個 conftest；請跑完整的 `python3 -m pytest`。
"""
import iam_f05_steps


def pytest_configure(config):
    config.pluginmanager.register(iam_f05_steps, "iam_f05_steps")
