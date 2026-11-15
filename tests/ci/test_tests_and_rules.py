"""no-weakened-tests、done-when（含 rule_report plugin）、strings、lint。"""
import json
import textwrap

import pytest

from scripts.ci import checks
from tests.ci.conftest import make_ticket

pytest_plugins = ["pytester"]


# ------------------------------------------------------------------ no-weakened-tests


@pytest.mark.parametrize("code", [
    "import pytest\n@pytest.mark.skip(reason='later')\ndef test_a(): pass\n",
    "import pytest\n@pytest.mark.skipif(True, reason='x')\ndef test_a(): pass\n",
    "import pytest\n@pytest.mark.xfail\ndef test_a(): assert False\n",
    "import pytest\ndef test_a():\n    pytest.skip('no')\n",
    "import pytest\npytestmark = pytest.mark.skip\n",
    "import pytest\nx = pytest.importorskip('nope')\n",
    "import unittest\n@unittest.skip('x')\nclass T(unittest.TestCase): pass\n",
    "import unittest\nclass T(unittest.TestCase):\n    @unittest.expectedFailure\n    def test(self): pass\n",
    "from pytest import skip\n",
    "collect_ignore = ['test_a.py']\n",
])
def test_skip_and_xfail_markers_are_rejected(repo, code):
    repo.commit({"tests/test_a.py": code})
    assert checks.check_no_weakened_tests(repo.ctx()), code


def test_skip_tags_in_feature_files_are_rejected(repo):
    repo.commit({"tests/x.feature": "@skip\nFeature: x\n  Scenario: s\n    Given a\n"})
    assert checks.check_no_weakened_tests(repo.ctx())


def test_the_word_skip_in_strings_and_comments_is_fine(repo):
    repo.commit({"tests/test_a.py": '"""不要 skip 測試。"""\n# pytest.mark.skip is forbidden\nMSG = "xfail"\ndef test_a(): assert MSG\n'})
    assert checks.check_no_weakened_tests(repo.ctx()) == []


def test_removing_a_rule_from_implemented_txt_is_rejected(repo):
    repo.commit({"tests/implemented.txt": "# 空\n"})
    assert checks.check_no_weakened_tests(repo.ctx()) == ["tests/implemented.txt 少了 AAA-R01（只能增加，不能減少）"]


def test_adding_a_rule_to_implemented_txt_is_fine(repo):
    repo.commit({"tests/implemented.txt": "AAA-R01\nAAA-R02\n"})
    assert checks.check_no_weakened_tests(repo.ctx()) == []


def test_the_real_repo_passes_no_weakened_tests():
    """現有的 tests/ 沒有任何跳過標記（bdd_plugin 的「尚未實作」機制是唯一的例外）。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    assert checks.check_no_weakened_tests(checks.Ctx(root=root)) == []


# ------------------------------------------------------------------ done-when


@pytest.fixture
def rule_repo(repo):
    done = "1. 下列規則的 3 個 scenario 全部通過：`AAA-R01`（2）、`AAA-R02`（1）。\n2. 沒有規則 ID 的敘述 AAA-R99 不算。"
    repo.checkout("milestone/M9")
    repo.commit({"docs/tickets/T-920.md": make_ticket("T-920", ["app/**"], done=done)})
    repo.branch("ticket/T-920")
    repo.commit({"tests/implemented.txt": "AAA-R01\nAAA-R02\n"})
    return repo


PASSING = {"rules": {"AAA-R01": {"f.feature:3": "passed", "f.feature:9": "passed"}, "AAA-R02": {"f.feature:15": "passed"}}}


def test_done_when_passes_when_every_listed_rule_ran_and_passed(rule_repo):
    assert checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), PASSING) == []


def test_done_when_fails_when_a_rule_is_missing_from_implemented_txt(rule_repo):
    rule_repo.commit({"tests/implemented.txt": "AAA-R01\n"})
    assert checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), PASSING) == ["AAA-R02 不在 tests/implemented.txt"]


def test_done_when_fails_when_a_scenario_was_not_executed(rule_repo):
    report = json.loads(json.dumps(PASSING))
    report["rules"]["AAA-R01"]["f.feature:9"] = "skipped"
    problems = checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), report)
    assert problems == ["AAA-R01 有 1 個 scenario 沒有通過：skipped"]


def test_done_when_fails_when_a_scenario_failed(rule_repo):
    report = json.loads(json.dumps(PASSING))
    report["rules"]["AAA-R02"]["f.feature:15"] = "failed"
    assert checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), report)


def test_done_when_fails_when_no_scenario_was_collected_for_a_rule(rule_repo):
    report = {"rules": {"AAA-R01": PASSING["rules"]["AAA-R01"]}}
    problems = checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), report)
    assert len(problems) == 1 and problems[0].startswith("AAA-R02 沒有任何 scenario 被收集")


def test_done_when_fails_when_the_scenario_count_differs_from_the_ticket(rule_repo):
    report = json.loads(json.dumps(PASSING))
    del report["rules"]["AAA-R01"]["f.feature:9"]
    problems = checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), report)
    assert problems == ["AAA-R01 的 ticket 寫 2 個 scenario，實際收集到 1 個"]


def test_done_when_fails_without_any_report(rule_repo):
    assert checks.check_done_when(rule_repo.ctx(head_ref="ticket/T-920"), None)


def test_done_when_passes_for_a_ticket_without_rule_ids(repo):
    assert checks.check_done_when(repo.ctx(), None) == []


def test_milestone_pr_requires_every_planned_rule(repo):
    done = "1. `AAA-R01`（1）、`AAA-R07`（1）。"
    repo.checkout("milestone/M9")
    repo.commit({"docs/tickets/T-921.md": make_ticket("T-921", ["app/**"], done=done)})
    ctx = repo.ctx(head_ref="milestone/M9", base_ref="main")
    problems = checks.check_done_when(ctx, {"rules": {"AAA-R01": {"f:1": "passed"}}})
    assert problems == ["AAA-R07 不在 tests/implemented.txt"]


FEATURE = textwrap.dedent("""\
    Feature: Toy
      Rule: ZZZ-R01 listed and green
        Scenario: green
          When I do the thing
          Then it works

        Scenario Outline: two examples, one scenario
          When I do the thing
          Then it works
          Examples:
            | n |
            | 1 |
            | 2 |

      Rule: ZZZ-R02 not listed
        Scenario: pending
          When I do the thing
          Then it works

      Rule: ZZZ-R03 listed but broken
        Scenario: broken
          When I do the thing
          Then it breaks
""")

STEPS = textwrap.dedent("""\
    from pytest_bdd import scenarios, when, then
    scenarios("toy.feature")

    @when("I do the thing")
    def _do(): pass

    @then("it works")
    def _ok(): pass

    @then("it breaks")
    def _bad(): assert False
""")


def test_rule_report_plugin_records_one_result_per_scenario(pytester, monkeypatch):
    """真的跑 pytest：Outline 的兩個例子只算一個 scenario；沒列在清單的規則是 skipped；失敗的規則是 failed。"""
    pytester.makefile(".feature", toy=FEATURE)
    pytester.makepyfile(test_toy=STEPS)
    pytester.makeini("[pytest]\nbdd_features_base_dir = .\n")
    (pytester.path / "implemented.txt").write_text("ZZZ-R01\nZZZ-R03\n", encoding="utf-8")
    out = pytester.path / "report.json"
    monkeypatch.setenv("YC_RULE_REPORT", str(out))  # monkeypatch 會還原外層（真正的 CI 執行）設定的值
    pytester.runpytest_inprocess(
        "-p", "tests.support.bdd_plugin", "-p", "scripts.ci.rule_report",
        "--spec-features-dir", str(pytester.path), "--implemented", str(pytester.path / "implemented.txt"),
    )
    rules = json.loads(out.read_text(encoding="utf-8"))["rules"]
    assert sorted(rules["ZZZ-R01"].values()) == ["passed", "passed"]      # green + outline 兩個例子合成一個
    assert list(rules["ZZZ-R02"].values()) == ["skipped"]
    assert list(rules["ZZZ-R03"].values()) == ["failed"]


# ------------------------------------------------------------------ strings


def _app(repo, code):
    repo.commit({"spec/appendix-b-fields.md": "| 欄位 | 「請輸入顯示名稱」<br>「密碼長度須為 6 至 30 個字」 |\n", "app/m.py": code})


def test_strings_fails_for_a_message_that_is_not_in_the_spec(repo):
    _app(repo, 'ERROR = "請輸入名字"\n')
    problems = checks.check_strings(repo.ctx())
    assert len(problems) == 1 and "請輸入名字" in problems[0]


def test_strings_passes_for_a_message_copied_verbatim(repo):
    _app(repo, 'ERROR = "請輸入顯示名稱"\nOTHER = "密碼長度須為 6 至 30 個字"\n')
    assert checks.check_strings(repo.ctx()) == []


def test_strings_fails_for_a_message_built_at_runtime(repo):
    _app(repo, 'def f(n):\n    return f"密碼長度須為 {n} 個字"\n')
    assert checks.check_strings(repo.ctx())


def test_strings_ignores_docstrings_and_comments_and_ascii(repo):
    _app(repo, '"""模組說明。"""\n# 註解：中文\ndef f():\n    """函式說明。"""\n    return "ok"\n')
    assert checks.check_strings(repo.ctx()) == []


def test_the_real_app_passes_strings():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    assert checks.check_strings(checks.Ctx(root=root)) == []


# ------------------------------------------------------------------ lint


def test_lint_fails_for_an_unused_import(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    problems = checks.check_lint(checks.Ctx(root=tmp_path))
    assert any("a.py" in p and "F401" in p for p in problems), problems


def test_lint_fails_for_a_syntax_error(tmp_path):
    (tmp_path / "a.py").write_text("def f(:\n", encoding="utf-8")
    assert checks.check_lint(checks.Ctx(root=tmp_path))


def test_lint_fails_for_a_broken_shell_script(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x").write_text("#!/usr/bin/env bash\nif then fi (\n", encoding="utf-8")
    problems = checks.check_lint(checks.Ctx(root=tmp_path))
    assert any("bash 語法錯誤" in p for p in problems), problems


def test_lint_passes_for_clean_code(tmp_path):
    (tmp_path / "a.py").write_text("print('ok')\n", encoding="utf-8")
    assert checks.check_lint(checks.Ctx(root=tmp_path)) == []


def test_the_real_repo_passes_lint():
    from pathlib import Path
    assert checks.check_lint(checks.Ctx(root=Path(__file__).resolve().parents[2])) == []


# ------------------------------------------------------------------ workflow 與 docs/ci-checks.md 對得上


def test_every_check_in_ci_checks_md_has_a_job_a_cli_entry_and_a_failing_test_module():
    """docs/ci-checks.md 的每一項：workflow 有同名的 job，CLI 認得，而且 tests/ci/ 有針對它的案例。"""
    import re
    from pathlib import Path

    from scripts.ci import run

    root = Path(__file__).resolve().parents[2]
    doc = (root / "docs" / "ci-checks.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `([a-z-]+)` \|", doc, re.M)
    assert names == ["tests", "spec-readonly", "path-scope", "evidence", "migration-scope",
                     "no-weakened-tests", "done-when", "strings", "commit-author", "lint"]
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    sources = "".join(p.read_text(encoding="utf-8") for p in (root / "tests" / "ci").glob("test_*.py"))
    for name in names:
        assert re.search(rf"^  {name}:$", workflow, re.M), f"workflow 缺少 job {name}"
        assert name in run.NAMES, f"run.py 不認得 {name}"
        assert f"check_{name.replace('-', '_')}" in sources, f"tests/ci 沒有針對 {name} 的案例"
