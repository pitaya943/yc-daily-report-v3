"""把 IAM-F06 的步驟註冊成全域 plugin（原因見 tests/steps/IAM-F01/conftest.py 與 pitfall #26）。"""
import iam_f06_steps


def pytest_configure(config):
    config.pluginmanager.register(iam_f06_steps, "iam_f06_steps")
