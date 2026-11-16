"""pytest plugin：把每條規則底下每個 scenario 的結果寫成 JSON，給 done-when 檢查用。

用法：`PYTHONPATH=. python3 -m pytest -p scripts.ci.rule_report`，輸出到 $YC_RULE_REPORT（預設 rule-report.json）。

格式：{"rules": {"IAM-R01": {"IAM-F01-sign-in.feature:12": "passed", ...}}}
* scenario 鍵 = feature 檔名:scenario 所在行。Scenario Outline 展開成很多個 pytest 項目，但只算一個 scenario；
  同一個 scenario 只要有一個項目沒通過，整個 scenario 就算沒通過（failed > skipped > passed）。
* 規則 ID 的取得方式與 tests/support/bdd_plugin.py 相同（從 Rule 名稱取 ID），不另外發明一套。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pytest_bdd.scenario import scenario_wrapper_template_registry

from tests.support.implemented import rule_id_of

_RANK = {"passed": 0, "skipped": 1, "failed": 2}


class _Reporter:
    def __init__(self) -> None:
        self.item_key: dict[str, tuple[str, str]] = {}
        self.item_outcome: dict[str, str] = {}

    def pytest_collection_modifyitems(self, items):
        for item in items:
            scenario = scenario_wrapper_template_registry.get(getattr(item, "obj", None))
            if scenario is None:
                continue
            rid = rule_id_of(getattr(getattr(scenario, "rule", None), "name", None))
            if rid is None:
                continue
            key = f"{Path(scenario.feature.filename).name}:{scenario.line_number}"
            self.item_key[item.nodeid] = (rid, key)

    def pytest_runtest_logreport(self, report):
        if report.nodeid not in self.item_key:
            return
        if report.failed:  # setup、call、teardown 任何一階段失敗
            outcome = "failed"
        elif report.skipped:
            outcome = "skipped"
        elif report.when == "call":
            outcome = "passed"
        else:
            return
        old = self.item_outcome.get(report.nodeid)
        if old is None or _RANK[outcome] > _RANK[old]:
            self.item_outcome[report.nodeid] = outcome

    def pytest_sessionfinish(self, session):
        rules: dict[str, dict[str, str]] = {}
        for nodeid, (rid, key) in self.item_key.items():
            outcome = self.item_outcome.get(nodeid, "skipped")  # 沒執行到 = 沒通過
            cur = rules.setdefault(rid, {}).get(key)
            if cur is None or _RANK[outcome] > _RANK[cur]:
                rules[rid][key] = outcome
        path = os.environ.get("YC_RULE_REPORT", "rule-report.json")
        Path(path).write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def pytest_configure(config):
    config.pluginmanager.register(_Reporter(), "yc_rule_reporter")
