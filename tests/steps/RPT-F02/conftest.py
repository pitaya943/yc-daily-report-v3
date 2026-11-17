"""把 RPT-F02 的步驟註冊成全域 plugin（理由與限制同 tests/steps/IAM-F01/conftest.py，pitfall #26）。

只跑 `tests/test_spec.py` 一個檔案時不會載入這個 conftest；請跑完整的 `python3 -m pytest`。
"""
import rpt_f02_steps


def pytest_configure(config):
    config.pluginmanager.register(rpt_f02_steps, "rpt_f02_steps")
