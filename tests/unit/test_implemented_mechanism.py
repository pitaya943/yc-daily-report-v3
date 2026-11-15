"""完成條件 5：只有列在 tests/implemented.txt 的規則 ID 會被執行，其餘是「尚未實作」而非失敗。

用 pytester 在隔離的暫存目錄跑一個迷你 feature，驗證真正的 plugin 行為。
"""
import textwrap

import pytest

from tests.support.implemented import load_implemented, rule_id_of

pytest_plugins = ["pytester"]


def test_rule_id_of():
    assert rule_id_of("IAM-R01 The name list shows only non-archived accounts") == "IAM-R01"
    assert rule_id_of("PAY-R12 something") == "PAY-R12"
    assert rule_id_of("no id here") is None
    assert rule_id_of(None) is None


def test_load_implemented_ignores_comments_and_blank_lines(tmp_path):
    f = tmp_path / "implemented.txt"
    f.write_text("# comment\n\nIAM-R01\n  PAY-R02  # inline\n", encoding="utf-8")
    assert load_implemented(f) == {"IAM-R01", "PAY-R02"}


FEATURE = textwrap.dedent("""\
    Feature: Toy
      Rule: ZZZ-R01 first rule
        Scenario: listed scenario
          When I do the thing
          Then it works

      Rule: ZZZ-R02 second rule
        Scenario: unlisted scenario
          When I do the thing
          Then it works
""")

STEPS = textwrap.dedent("""\
    from pytest_bdd import scenarios, when, then
    scenarios("toy.feature")

    @when("I do the thing")
    def _do(): pass

    @then("it works")
    def _ok(): pass
""")


@pytest.fixture
def toy(pytester):
    pytester.makefile(".feature", toy=FEATURE)
    pytester.makepyfile(test_toy=STEPS)
    pytester.makeini("[pytest]\nbdd_features_base_dir = .\n")
    return pytester


def test_only_listed_rules_run_and_the_rest_are_skipped_not_failed(toy):
    toy.makefile(".txt", implemented="ZZZ-R01\n")
    r = toy.runpytest("-p", "tests.support.bdd_plugin", "--implemented", "implemented.txt", "--spec-features-dir", ".", "-rs")
    r.assert_outcomes(passed=1, skipped=1, failed=0)
    r.stdout.fnmatch_lines(["*尚未實作*ZZZ-R02*"])


def test_empty_list_skips_everything(toy):
    toy.makefile(".txt", implemented="# nothing yet\n")
    r = toy.runpytest("-p", "tests.support.bdd_plugin", "--implemented", "implemented.txt", "--spec-features-dir", ".")
    r.assert_outcomes(passed=0, skipped=2, failed=0)
