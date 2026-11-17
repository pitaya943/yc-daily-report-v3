"""把 REV-F02 的步驟註冊成全域 plugin（理由與限制同 tests/steps/IAM-F01/conftest.py，pitfall #26）。

REV-F02 的步驟用到 REV-F01 的輔助函式（insert_report、post…）：先把 REV-F01 的目錄放進 sys.path，
`import rev_f01_steps` 取到的是同一個模組（REV-F01 的 conftest 也是用這個名稱載入並註冊），載入順序不影響結果。
只跑 `tests/test_spec.py` 一個檔案時不會載入這個 conftest；請跑完整的 `python3 -m pytest`。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "REV-F01"))

import rev_f02_steps  # noqa: E402


def pytest_configure(config):
    config.pluginmanager.register(rev_f02_steps, "rev_f02_steps")
