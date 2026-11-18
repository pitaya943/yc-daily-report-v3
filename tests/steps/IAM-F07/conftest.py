"""把 IAM-F07（與 IAM-F04 的 IAM-R14）的步驟註冊成全域 plugin（理由與限制同 tests/steps/IAM-F01/conftest.py，pitfall #26）。

只跑 `tests/test_spec.py` 一個檔案時不會載入這個 conftest；請跑完整的 `python3 -m pytest`。
"""
import iam_f07_steps


def pytest_configure(config):
    config.pluginmanager.register(iam_f07_steps, "iam_f07_steps")
