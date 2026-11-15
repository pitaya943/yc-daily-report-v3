"""spec-readonly、path-scope、evidence、commit-author：每一項都有「會讓它失敗」的案例（docs/ci-checks.md）。"""
import pytest

from scripts.ci import checks
from tests.ci.conftest import make_ticket

OTHER = "someone@example.com"


# ------------------------------------------------------------------ spec-readonly


@pytest.mark.parametrize("path", [
    "spec/README.md", "AGENTS.md", ".claude/skills/x/SKILL.md", ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/ci.yml", "docs/decisions.md", "docs/board.md",
])
def test_spec_readonly_fails_when_a_forbidden_path_is_modified(repo, path):
    repo.commit({path: "x\n"})
    problems = checks.check_spec_readonly(repo.ctx())
    assert any(path in p for p in problems), problems


def test_spec_readonly_passes_for_a_clean_ticket_pr(repo):
    repo.commit({"app/feature/a.py": "x = 1\n"})
    assert checks.check_spec_readonly(repo.ctx()) == []


def test_spec_readonly_only_applies_to_ticket_branches(repo):
    repo.commit({"spec/README.md": "x\n"})
    assert checks.check_spec_readonly(repo.ctx(head_ref="milestone/M9")) == []


def test_spec_readonly_exception_is_exactly_the_paths_the_ticket_lists():
    """D-031：禁止清單減去 allowed_paths「明確列出」的路徑，不是整個 .github。"""
    assert checks._explicit_pattern(".github/workflows/**")
    assert not checks._explicit_pattern("**")          # 萬用字元不能開後門
    assert not checks._explicit_pattern(".github*")
    assert not checks._explicit_pattern("app/**")


@pytest.fixture
def workflow_ticket(repo):
    repo.checkout("milestone/M9")
    repo.commit({"docs/tickets/T-901.md": make_ticket("T-901", [".github/workflows/**", "scripts/ci/**"])})
    repo.branch("ticket/T-901")
    return repo


def test_spec_readonly_allows_the_workflow_path_the_ticket_lists(workflow_ticket):
    workflow_ticket.commit({".github/workflows/ci.yml": "name: ci\n"})
    assert checks.check_spec_readonly(workflow_ticket.ctx(head_ref="ticket/T-901")) == []


def test_spec_readonly_still_blocks_other_github_paths_for_that_ticket(workflow_ticket):
    workflow_ticket.commit({".github/PULL_REQUEST_TEMPLATE.md": "x\n"})
    assert checks.check_spec_readonly(workflow_ticket.ctx(head_ref="ticket/T-901"))


def test_spec_readonly_blocks_workflows_for_a_ticket_that_does_not_list_them(repo):
    repo.commit({".github/workflows/ci.yml": "name: ci\n"})
    assert checks.check_spec_readonly(repo.ctx())


def test_spec_readonly_fails_closed_when_the_ticket_is_missing(repo):
    repo.branch("ticket/T-404")
    with pytest.raises(checks.CheckError):
        checks.check_spec_readonly(repo.ctx(head_ref="ticket/T-404"))


# ------------------------------------------------------------------ path-scope


def test_path_scope_fails_for_a_file_outside_allowed_paths(repo):
    repo.commit({"app/feature/a.py": "x\n", "app/other/b.py": "y\n"})
    problems = checks.check_path_scope(repo.ctx())
    assert problems == ["app/other/b.py（A）不在 T-900 的 allowed_paths 內"]


def test_path_scope_passes_inside_allowed_paths(repo):
    repo.commit({"app/feature/a.py": "x\n", "app/feature/deep/b.py": "y\n"})
    assert checks.check_path_scope(repo.ctx()) == []


def test_path_scope_cannot_be_widened_by_editing_the_ticket_in_the_pr(repo):
    """ticket 從目標分支讀；PR 自己改 allowed_paths 沒有用，改 ticket 檔本身也算範圍外。"""
    repo.commit({"docs/tickets/T-900.md": make_ticket(paths=("app/**", "docs/tickets/**")), "app/other/b.py": "y\n"})
    problems = checks.check_path_scope(repo.ctx())
    assert any("app/other/b.py" in p for p in problems)
    assert any("docs/tickets/T-900.md" in p for p in problems)


def test_path_scope_checks_both_sides_of_a_rename(repo):
    repo.checkout("milestone/M9")
    repo.commit({"app/old/a.py": "x = 1\n" * 5})
    repo._git("checkout", "-q", "-B", "ticket/T-900")
    (repo.root / "app/feature").mkdir(parents=True)
    repo._git("mv", "app/old/a.py", "app/feature/a.py")
    repo._git("commit", "-q", "-m", "mv")
    problems = checks.check_path_scope(repo.ctx())
    assert problems == ["app/old/a.py（D）不在 T-900 的 allowed_paths 內"]  # 新路徑合規，舊路徑（刪除）在範圍外


def test_path_scope_ignores_non_ticket_branches(repo):
    repo.commit({"anything.txt": "x\n"})
    assert checks.check_path_scope(repo.ctx(head_ref="milestone/M9")) == []


# ------------------------------------------------------------------ evidence


def test_evidence_fails_when_the_section_is_missing(repo):
    assert checks.check_evidence(repo.ctx(pr_body="## 完成了什麼\n做了\n"))


def test_evidence_fails_when_the_section_only_has_the_template_comment(repo):
    body = "## 證據\n\n<!-- 每一條完成條件的證據。 -->\n\n## Milestone 報告\n"
    assert checks.check_evidence(repo.ctx(pr_body=body)) == ["PR 說明的「證據」一節是空的"]


@pytest.mark.parametrize("filler", ["無", "N/A", "-", "TODO"])
def test_evidence_fails_for_placeholder_text(repo, filler):
    assert checks.check_evidence(repo.ctx(pr_body=f"## 證據\n{filler}\n"))


def test_evidence_passes_with_real_content(repo):
    assert checks.check_evidence(repo.ctx(pr_body="## 證據\n```\n$ pytest\n3 passed\n```\n## 其他\n")) == []


def test_evidence_requires_a_screenshot_when_the_ticket_has_screens(repo):
    repo.checkout("milestone/M9")
    repo.commit({"docs/tickets/T-902.md": make_ticket("T-902", ["app/modules/x/templates/**", "docs/evidence/T-902/**"])})
    repo.branch("ticket/T-902")
    ctx = repo.ctx(head_ref="ticket/T-902", pr_body="## 證據\n輸出\n")
    assert checks.check_evidence(ctx) == ["T-902 涉及畫面，但 docs/evidence/T-902/ 沒有任何截圖"]
    repo.commit({"docs/evidence/T-902/notes.txt": "not an image\n"})
    assert checks.check_evidence(ctx)  # 非圖片不算
    repo.commit({"docs/evidence/T-902/login.png": "png\n"})
    assert checks.check_evidence(ctx) == []


# ------------------------------------------------------------------ commit-author


def test_commit_author_fails_for_a_commit_by_someone_else(repo):
    repo.commit({"app/feature/a.py": "1\n"})
    bad = repo.commit({"app/feature/b.py": "2\n"}, author=OTHER)
    problems = checks.check_commit_author(repo.ctx())
    assert len(problems) == 1 and bad[:7] in problems[0] and OTHER in problems[0]


def test_commit_author_passes_when_every_commit_is_the_bot(repo):
    repo.commit({"app/feature/a.py": "1\n"})
    repo.commit({"app/feature/b.py": "2\n"})
    assert checks.check_commit_author(repo.ctx()) == []


def test_commit_author_is_case_insensitive_on_the_email(repo):
    repo.commit({"app/feature/a.py": "1\n"}, author=checks.BOT_EMAIL.upper())
    assert checks.check_commit_author(repo.ctx()) == []


def test_commit_author_includes_merge_commits(repo):
    """GitHub 的 Update branch 會產生 merge commit，作者是按按鈕的人；它也是 PR 中的 commit，要檢查。"""
    repo.commit({"app/feature/a.py": "1\n"})
    repo.checkout("milestone/M9")
    repo.commit({"README.md": "base moved\n"})
    repo.checkout("ticket/T-900")
    repo._git("merge", "-q", "--no-ff", "-m", "Merge branch 'milestone/M9' into ticket/T-900", "milestone/M9", author=OTHER)
    problems = checks.check_commit_author(repo.ctx())
    assert len(problems) == 1 and problems[0].startswith("merge commit ")


def test_commit_author_does_not_blame_commits_that_came_from_the_base(repo):
    """merge 進來的目標分支 commit 屬於目標分支，不算 PR 的 commit。"""
    repo.checkout("milestone/M9")
    repo.commit({"README.md": "by someone else\n"}, author=OTHER)
    repo.checkout("ticket/T-900")
    repo.commit({"app/feature/a.py": "1\n"})
    repo._git("merge", "-q", "--no-ff", "-m", "merge base", "milestone/M9")  # bullet-bots 自己 merge
    assert checks.check_commit_author(repo.ctx()) == []
