"""修正第 2 輪：Kuei 在 issue #7 的決定（D-044～D-049）與 Verifier 第 2 輪的問題。

D-044：檢查防的是 agent 的疏忽與常見的偷懶寫法，不防刻意的攻擊；
用允許清單、禁止整類寫法、比對結果的方式設計，不列舉語法。
每一節先寫會失敗的測試（單獨一個 commit），再寫實作。
"""
import pytest

from scripts.ci import checks, run

pytest_plugins = ["pytester"]

GOOD_BODY = "## 證據\n```\n$ pytest\n3 passed\n```\n"


def _fails(fn, *args) -> bool:
    """檢查判為失敗：回傳違規，或丟 CheckError（run.py 一律當作失敗）。"""
    try:
        return bool(fn(*args))
    except checks.CheckError:
        return True


# ------------------------------------------------------------------ D-049：目標是 milestone/* 的 PR，來源必須是 ticket/T-xxx

NOT_TICKET_BRANCHES = ["feature/x", "milestone/M9", "main", "T-900", "ticket/T-900-extra", "ticket/t-900", "ticket/T-900/x"]


@pytest.mark.parametrize("branch", NOT_TICKET_BRANCHES)
def test_d049_every_ticket_based_check_fails_for_a_non_ticket_branch_into_a_milestone(repo, branch):
    repo.commit({"app/feature/a.py": "x = 1\n"})
    ctx = repo.ctx(head_ref=branch, pr_body=GOOD_BODY)
    for name, fn, args in [
        ("spec-readonly", checks.check_spec_readonly, (ctx,)),
        ("path-scope", checks.check_path_scope, (ctx,)),
        ("evidence", checks.check_evidence, (ctx,)),
        ("migration-scope", checks.check_migration_scope, (ctx,)),
        ("no-weakened-tests", checks.check_no_weakened_tests, (ctx,)),
        ("done-when", checks.check_done_when, (ctx, {"rules": {}})),
    ]:
        assert _fails(fn, *args), (branch, name)
    assert checks.branch_gate(ctx), branch


def test_d049_a_ticket_branch_whose_ticket_file_is_not_on_the_target_fails(repo):
    repo.branch("ticket/T-777")
    repo.commit({"app/feature/a.py": "x = 1\n"})
    gate = checks.branch_gate(repo.ctx(head_ref="ticket/T-777"))
    assert gate and "T-777" in gate[0], gate


def test_d049_a_proper_ticket_branch_passes_the_gate(repo):
    assert checks.branch_gate(repo.ctx()) == []


def test_d049_pr_into_main_is_not_a_ticket_pr(repo):
    """milestone/Mx → main 是 milestone PR，不受 D-049 限制（也不套用單一 ticket 的範圍）。"""
    repo.commit({"spec/a.md": "x\n"})
    ctx = repo.ctx(head_ref="milestone/M9", base_ref="main")
    assert checks.branch_gate(ctx) == []
    assert checks.check_spec_readonly(ctx) == []


@pytest.mark.parametrize("name", run.NAMES)
@pytest.mark.parametrize("branch", ["feature/x", "ticket/T-999"])
def test_d049_run_py_fails_every_check(monkeypatch, capsys, name, branch):
    """CLI 的每一項（含 tests、strings、lint、commit-author）在目標是 milestone/* 而來源不合規時都判為失敗。"""
    monkeypatch.setenv("CI_BASE_REF", "milestone/M0")
    monkeypatch.setenv("CI_HEAD_REF", branch)
    monkeypatch.setenv("CI_BASE_SHA", "HEAD")
    assert run.main(["run.py", name]) == 1
    assert "D-049" in capsys.readouterr().out


def test_d049_run_py_lets_a_proper_ticket_branch_through(monkeypatch, capsys):
    monkeypatch.setenv("CI_BASE_REF", "milestone/M0")
    monkeypatch.setenv("CI_HEAD_REF", "ticket/T-002")
    monkeypatch.setenv("CI_BASE_SHA", "HEAD")
    assert run.main(["run.py", "strings"]) == 0, capsys.readouterr().out

