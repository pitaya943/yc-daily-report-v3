"""pytest plugin：依 tests/implemented.txt 決定哪些 scenario 要執行。

- Scenario 所屬 Rule 的 ID 在清單內 → 正常執行（失敗就是真的失敗）。
- 不在清單內 → skip，原因寫「尚未實作」。skip 不是失敗，也不是預期失敗；
  實作某條規則的 ticket 把 ID 加進清單後，這條規則的 scenario 就必須通過。
- 只管 spec/features 底下的 feature；框架自己的 feature（tests/integration/*.feature）一律執行。
- 沒有 Rule 的 spec scenario（沒有規則 ID 可對照）一律視為尚未實作，避免漏跑也避免誤報失敗。
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import pytest
import pytest_bdd.parser as bdd_parser
from pytest_bdd.scenario import scenario_wrapper_template_registry

from tests.support.implemented import load_implemented, rule_id_of


class _UniqueKeyDict(OrderedDict):
    """pytest-bdd 以 scenario 名稱當 key 存進 feature.scenarios，同一個 .feature 內重名的 scenario
    會被後者默默覆蓋（CFG-F02 有兩個 `Validation`，CFG-R10 的 6 個例子因此從不執行）。
    這裡遇到重名就把 key 改成「名稱 (line N)」，所有 scenario 都保留；ScenarioTemplate.name 不變。
    受 pyproject 的 pytest-bdd>=9,<10 限制；若 pytest-bdd 改了內部結構，
    tests/unit/test_spec_collection.py 會因為收集數量不符而失敗，不會默默少測。
    """

    def __setitem__(self, key, value):
        if key in self:
            key = f"{key} (line {value.line_number})"
        super().__setitem__(key, value)


# FeatureParser 用 `OrderedDict()` 建立 feature.scenarios；換成會處理重名的版本
bdd_parser.OrderedDict = _UniqueKeyDict

DEFAULT_LIST = Path(__file__).resolve().parents[1] / "implemented.txt"
DEFAULT_SPEC_DIR = Path(__file__).resolve().parents[2] / "spec" / "features"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--implemented",
        default=str(DEFAULT_LIST),
        help="已實作規則 ID 清單（預設 tests/implemented.txt）",
    )
    parser.addoption(
        "--spec-features-dir",
        default=str(DEFAULT_SPEC_DIR),
        help="受 implemented.txt 管控的 feature 目錄（預設 spec/features）；其他 .feature（框架自己的測試）一律執行",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    implemented = load_implemented(config.getoption("--implemented"))
    spec_dir = Path(config.getoption("--spec-features-dir")).resolve()
    for item in items:
        # pytest-bdd 把每個 scenario 函式對應到解析後的 ScenarioTemplate（內含所屬 Rule）
        scenario = scenario_wrapper_template_registry.get(getattr(item, "obj", None))
        if scenario is None:
            continue  # 不是 pytest-bdd 的 scenario（單元測試、冒煙測試）
        if spec_dir not in Path(scenario.feature.filename).resolve().parents:
            continue  # 框架自己的 feature（不是 spec）不受清單管控
        rule = scenario.rule
        rid = rule_id_of(getattr(rule, "name", None))
        if rid is None or rid not in implemented:
            label = rid or "no rule id"
            item.add_marker(pytest.mark.skip(reason=f"尚未實作 ({label}; not listed in implemented.txt)"))
