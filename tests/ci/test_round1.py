"""修正第 1 輪（Verifier 的繞過案例）：每一項先有會失敗的測試，再修檢查本身。

對照 PR #5 的 Verifier 判定：問題 2（no-weakened-tests）、4（strings）、5（ticket 分支名稱）、6（tests）。
問題 1（migration-scope）在 test_migration_scope.py 與 test_migration_sandbox.py。
"""
import pytest

from scripts.ci import checks

pytest_plugins = ["pytester"]

# ------------------------------------------------------------------ 問題 2：no-weakened-tests


@pytest.mark.parametrize("code", [
    "import unittest\ndef test_a():\n    raise unittest.SkipTest('x')\n",
    "from unittest import SkipTest\ndef test_a():\n    raise SkipTest('x')\n",
    "from _pytest.outcomes import Skipped\ndef test_a():\n    raise Skipped()\n",
    "import _pytest.outcomes\ndef test_a():\n    raise _pytest.outcomes.Skipped()\n",
    "import pytest\ndef test_a():\n    getattr(pytest, 'sk' + 'ip')('x')\n",
    "import pytest\nNAME = 'skip'\ndef test_a():\n    getattr(pytest, NAME)('x')\n",
    "import pytest\ndef test_a():\n    getattr(pytest, 'skip')('x')\n",
    "def test_a():\n    eval('1')\n",
    "def test_a():\n    exec('import pytest')\n",
    "def test_a():\n    __import__('pytest').skip('x')\n",
    "import importlib\ndef test_a():\n    importlib.import_module('pytest').skip('x')\n",
    "def pytest_collection_modifyitems(config, items):\n    items.clear()\n",
    "def pytest_ignore_collect(collection_path):\n    return True\n",
    "def pytest_runtest_setup(item):\n    pass\n",
    "import pytest\ndef pytest_collection_modifyitems(items):\n    for i in items:\n        i.add_marker(pytest.mark.skip)\n",
])
def test_more_ways_to_skip_are_rejected_inside_tests(repo, code):
    repo.commit({"tests/conftest.py": code})
    assert checks.check_no_weakened_tests(repo.ctx()), code


@pytest.mark.parametrize("path,code", [
    ("conftest.py", "import pytest\ndef pytest_collection_modifyitems(items):\n    for i in items:\n        i.add_marker(pytest.mark.skip)\n"),
    ("conftest.py", "def pytest_collection_modifyitems(items):\n    items.clear()\n"),
    ("conftest.py", "collect_ignore_glob = ['tests/*']\n"),
    ("scripts/ci/conftest.py", "def pytest_collection_modifyitems(items):\n    items.clear()\n"),
])
def test_skips_outside_the_tests_dir_are_rejected(repo, path, code):
    repo.commit({path: code})
    assert checks.check_no_weakened_tests(repo.ctx()), (path, code)


@pytest.mark.parametrize("name,text", [
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--deselect tests/test_x.py::test_a"\n'),
    ("pyproject.toml", "[tool.pytest.ini_options]\naddopts = \"-q -k 'not money'\"\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = ["-m", "not slow"]\n'),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--ignore=tests/unit"\n'),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--ignore-glob=tests/u*"\n'),
    ("pytest.ini", "[pytest]\naddopts = --deselect a::b\n"),
    ("tox.ini", "[pytest]\naddopts = -k nope\n"),
    ("setup.cfg", "[tool:pytest]\naddopts = -m nope\n"),
])
def test_pytest_options_that_deselect_tests_are_rejected(repo, name, text):
    repo.commit({name: text})
    problems = checks.check_no_weakened_tests(repo.ctx())
    assert any(name in p for p in problems), problems


def test_a_workflow_pytest_command_with_deselect_is_rejected(repo):
    repo.commit({".github/workflows/ci.yml": "jobs:\n  tests:\n    steps:\n      - run: python3 -m pytest -k 'not slow'\n"})
    assert checks.check_no_weakened_tests(repo.ctx())


def test_normal_pytest_options_are_fine(repo):
    repo.commit({"pyproject.toml": '[tool.pytest.ini_options]\naddopts = "-rfE"\ntestpaths = ["tests"]\n'})
    assert checks.check_no_weakened_tests(repo.ctx()) == []


def test_getattr_with_a_plain_constant_name_is_fine(repo):
    repo.commit({"tests/test_a.py": "def test_a():\n    assert getattr(object(), 'missing', None) is None\n"})
    assert checks.check_no_weakened_tests(repo.ctx()) == []


BDD_PLUGIN = (
    "import pytest\n"
    "def pytest_collection_modifyitems(config, items):\n"
    "    for item in items:\n"
    "        item.add_marker(pytest.mark.skip(reason='not implemented'))\n"
)


def test_the_exemption_covers_only_the_bdd_plugin_unchanged_on_the_base(repo):
    """豁免縮到最小：只有「目標分支上原樣不變」的 tests/support/bdd_plugin.py 可以有 skip（T-001 的 implemented.txt 機制）。"""
    repo.checkout("milestone/M9")
    repo.commit({"tests/support/bdd_plugin.py": BDD_PLUGIN})
    repo._git("checkout", "-q", "-B", "ticket/T-900")
    assert checks.check_no_weakened_tests(repo.ctx()) == []  # 沒動它：豁免成立
    repo.commit({"tests/support/bdd_plugin.py": BDD_PLUGIN + "# changed\n"})
    assert checks.check_no_weakened_tests(repo.ctx())  # 動了哪怕一行：回到一般規則，skip 被抓到


def test_a_skip_in_another_support_file_is_not_exempt(repo):
    repo.commit({"tests/support/other_plugin.py": BDD_PLUGIN})
    assert checks.check_no_weakened_tests(repo.ctx())


# ------------------------------------------------------------------ 問題 4：strings 也掃樣板與前端檔案

APPENDIX = "| 欄位 | 錯誤訊息 |\n| --- | --- |\n| 顯示名稱 | 「請輸入顯示名稱」 |\n"


@pytest.mark.parametrize("path,content", [
    ("app/modules/x/templates/form.html", "<p class=error>請輸入名字</p>\n"),
    ("app/modules/x/templates/form.html", '<input placeholder="請輸入名字">\n'),
    ("app/modules/x/templates/form.html", "<p>請輸入{{ field }}</p>\n"),
    ("app/modules/x/templates/form.html", "{% if bad %}<span>格式不對</span>{% endif %}\n"),
    ("app/templates/base.html", "<title>員工日報</title>\n"),
    ("app/static/app.js", "alert('請輸入名字');\n"),
    ("app/static/app.js", 'const msg = "請輸入名字";\n'),
    ("app/static/app.js", "const msg = `請輸入名字`;\n"),
    ("app/modules/x/static/app.css", "a::after { content: '請輸入名字'; }\n"),
    ("app/modules/x/templates/m.txt", "請輸入名字\n"),
])
def test_strings_fails_for_unlisted_text_in_templates_and_static_files(repo, path, content):
    repo.commit({"spec/appendix-b-fields.md": APPENDIX, path: content})
    problems = checks.check_strings(repo.ctx())
    assert problems and path in problems[0], problems


@pytest.mark.parametrize("path,content", [
    ("app/modules/x/templates/form.html", "<p class=error>請輸入顯示名稱</p>\n"),
    ("app/modules/x/templates/form.html", "<label>顯示名稱</label>\n"),  # 欄位名稱（附錄 B 第一欄）
    ("app/modules/x/templates/form.html", "{# 註解：中文 #}<!-- 註解：中文 --><p>{{ name }}</p>\n"),
    ("app/static/app.js", "// 註解：中文\n/* 註解：中文 */\nalert('請輸入顯示名稱');\n"),
    ("app/static/app.js", "const url = 'http://example.test/x'; fetch(url);\n"),
])
def test_strings_passes_for_listed_text_and_comments_in_templates(repo, path, content):
    repo.commit({"spec/appendix-b-fields.md": APPENDIX, path: content})
    assert checks.check_strings(repo.ctx()) == [], checks.check_strings(repo.ctx())


# ------------------------------------------------------------------ 問題 5：名稱不規範的 ticket/* 分支一律失敗

BAD_BRANCHES = ["ticket/t-900", "ticket/T900", "ticket/foo", "ticket/", "ticket/T-", "ticket/T-9x"]


@pytest.mark.parametrize("branch", BAD_BRANCHES)
def test_spec_readonly_fails_closed_for_a_ticket_branch_with_a_bad_name(repo, branch):
    repo.commit({"spec/a.md": "x\n", "README.md": "y\n"})
    problems = checks.check_spec_readonly(repo.ctx(head_ref=branch))
    assert any("spec/a.md" in p for p in problems), problems  # 至少套用禁止清單，而且不放行
    assert any("ticket" in p and "找不到" in p for p in problems), problems


@pytest.mark.parametrize("branch", BAD_BRANCHES)
def test_path_scope_fails_closed_for_a_ticket_branch_with_a_bad_name(repo, branch):
    repo.commit({"README.md": "y\n"})
    problems = checks.check_path_scope(repo.ctx(head_ref=branch))
    assert problems and any("找不到" in p for p in problems), problems


def test_a_ticket_branch_whose_ticket_file_is_missing_fails_closed(repo):
    repo.commit({"app/feature/a.py": "x = 1\n"})
    for check in (checks.check_spec_readonly, checks.check_path_scope):
        problems = check(repo.ctx(head_ref="ticket/T-777"))
        assert problems and any("T-777" in p for p in problems), (check.__name__, problems)


def test_branches_that_are_not_ticket_branches_are_still_not_checked(repo):
    repo.commit({"spec/a.md": "x\n"})
    assert checks.check_spec_readonly(repo.ctx(head_ref="milestone/M9")) == []
    assert checks.check_path_scope(repo.ctx(head_ref="milestone/M9")) == []


# ------------------------------------------------------------------ 問題 6：tests 本身要有會失敗的案例

FEATURE = (
    "Feature: Toy\n"
    "  Rule: ZZZ-R01 listed and green\n"
    "    Scenario: green\n      When I do the thing\n      Then it works\n\n"
    "  Rule: ZZZ-R03 listed but broken\n"
    "    Scenario: broken\n      When I do the thing\n      Then it breaks\n"
)
STEPS = (
    "from pytest_bdd import scenarios, when, then\n"
    "scenarios('toy.feature')\n"
    "@when('I do the thing')\ndef _do(): pass\n"
    "@then('it works')\ndef _ok(): pass\n"
    "@then('it breaks')\ndef _bad(): assert False\n"
)


def _toy(pytester, rules):
    pytester.makefile(".feature", toy=FEATURE)
    pytester.makepyfile(test_toy=STEPS)
    pytester.makeini("[pytest]\nbdd_features_base_dir = .\n")
    (pytester.path / "implemented.txt").write_text(rules, encoding="utf-8")
    return [
        "-p", "tests.support.bdd_plugin", "--spec-features-dir", str(pytester.path),
        "--implemented", str(pytester.path / "implemented.txt"),
    ]


def test_pytest_exits_nonzero_when_a_listed_rules_scenario_fails(pytester):
    """tests 這一項的失敗案例：implemented.txt 列出的規則有 scenario 失敗時，pytest 回傳非零，job 因此失敗。"""
    args = _toy(pytester, "ZZZ-R01\nZZZ-R03\n")
    result = pytester.runpytest_inprocess(*args)
    assert result.ret != 0
    result.assert_outcomes(passed=1, failed=1)


def test_pytest_exits_zero_when_every_listed_rule_passes(pytester):
    args = _toy(pytester, "ZZZ-R01\n")
    assert pytester.runpytest_inprocess(*args).ret == 0


TESTS_JOB_OK = (
    "jobs:\n  tests:\n    runs-on: ubuntu-24.04\n    services:\n      postgres:\n        image: postgres:17\n"
    "    steps:\n      - run: python3 -m pytest -p scripts.ci.rule_report\n  lint:\n    runs-on: x\n"
)


@pytest.mark.parametrize("mutation", [
    lambda t: t.replace("postgres:17", "postgres:16"),
    lambda t: t.replace("    services:\n      postgres:\n        image: postgres:17\n", ""),
    lambda t: t.replace("    runs-on: ubuntu-24.04\n", "    runs-on: ubuntu-24.04\n    continue-on-error: true\n", 1),
    lambda t: t.replace("rule_report", "rule_report || true"),
    lambda t: t.replace("rule_report", "rule_report || :"),
    lambda t: t.replace("rule_report", "rule_report; true"),
    lambda t: t.replace("rule_report", "rule_report -k 'not slow'"),
    lambda t: t.replace("rule_report", "rule_report --deselect a::b"),
    lambda t: t.replace("      - run: python3 -m pytest -p scripts.ci.rule_report\n", "      - run: echo skipped\n"),
])
def test_the_tests_job_guard_rejects_a_workflow_that_cannot_fail(repo, mutation):
    repo.commit({".github/workflows/ci.yml": mutation(TESTS_JOB_OK)})
    assert checks.check_tests(repo.ctx()), mutation(TESTS_JOB_OK)


def test_the_tests_job_guard_accepts_a_sound_workflow(repo):
    repo.commit({".github/workflows/ci.yml": TESTS_JOB_OK})
    assert checks.check_tests(repo.ctx()) == []


def test_the_real_workflow_passes_the_tests_job_guard():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    assert checks.check_tests(checks.Ctx(root=root)) == []
