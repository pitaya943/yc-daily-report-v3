"""pytest plugin：把每個測試 ID（nodeid）的結果寫成 JSON，給 no-weakened-tests 比對用（D-046）。

用法：`python3 -m pytest -p scripts.ci.test_report`，輸出到 $YC_TEST_REPORT（預設 test-report.json）。
CI 用 scripts/ci/test-results 在同一個 job 裡對「目標分支」與「PR」各跑一次，再由 checks.compare_test_results 比對。

格式：{"exitstatus": 0, "tests": {"tests/unit/test_x.py::test_a": "passed", ...}}
* 結果：passed、failed（setup／call／teardown 任一階段失敗）、skipped、xfailed、xpassed、not-run（收集了但沒執行）。
* 只記錄最後真的要執行的項目（session.items，已扣掉 -k、--deselect、hook 篩掉的）。被篩掉的測試不會出現在報告裡，
  比對時就是「消失」。
* 開始前先刪掉舊的報告：session 中途結束（os._exit、在 sessionstart 裡 pytest.exit）就不會留下報告，
  「沒有報告」本身判為失敗，不會誤用上一次的結果。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

_RANK = {"passed": 0, "skipped": 1, "xfailed": 1, "xpassed": 1, "not-run": 1, "failed": 2}


def _path() -> Path:
    return Path(os.environ.get("YC_TEST_REPORT", "test-report.json"))


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    # 比 conftest 更早：conftest 在載入時就結束行程（os._exit）的話，也不會留下舊報告
    _path().unlink(missing_ok=True)


class _Recorder:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.outcomes: dict[str, str] = {}

    def pytest_collection_finish(self, session):
        self.items = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        xfail = hasattr(report, "wasxfail")
        if report.failed:
            outcome = "failed"
        elif report.skipped:
            outcome = "xfailed" if xfail else "skipped"
        elif report.when == "call":
            outcome = "xpassed" if xfail else "passed"
        else:
            return  # setup／teardown 成功：等 call 的結果
        old = self.outcomes.get(report.nodeid)
        if old is None or _RANK[outcome] > _RANK[old] or (old == "passed" and outcome != "passed"):
            self.outcomes[report.nodeid] = outcome

    def pytest_sessionfinish(self, session, exitstatus):
        tests = {nodeid: self.outcomes.get(nodeid, "not-run") for nodeid in self.items}
        _path().write_text(
            json.dumps({"exitstatus": int(exitstatus), "tests": tests}, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )


def pytest_configure(config):
    config.pluginmanager.register(_Recorder(), "yc_test_reporter")
