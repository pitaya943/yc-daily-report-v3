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
    repo.commit({"spec/a.md": "x\n"})
    problems = checks.check_spec_readonly(repo.ctx(head_ref="ticket/T-404"))
    assert any("找不到" in p for p in problems) and any("spec/a.md" in p for p in problems)


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


# ------------------------------------------------------------------ evidence（D-040、D-041）

CODE_BLOCK = "## 證據\n```\n$ pytest\n3 passed\n```\n## 其他\n"


def test_evidence_fails_when_the_section_is_missing(repo):
    assert checks.check_evidence(repo.ctx(pr_body="## 完成了什麼\n做了\n"))


def test_evidence_fails_when_the_section_only_has_the_template_comment(repo):
    body = "## 證據\n\n<!-- 每一條完成條件的證據。 -->\n\n## Milestone 報告\n"
    assert checks.check_evidence(repo.ctx(pr_body=body)) == ["PR 說明的「證據」一節沒有 code block（CLI 輸出），也沒有指向 docs/evidence/T-900/ 的連結"]


@pytest.mark.parametrize("filler", ["無", "N/A", ".", "見下方", "已驗證，全部通過", "TODO"])
def test_evidence_fails_for_prose_without_a_code_block_or_link(repo, filler):
    """D-041：只寫文字（哪怕很長）不算；至少要一個 code block 或一個指向 docs/evidence/<ticket>/ 的連結。"""
    assert checks.check_evidence(repo.ctx(pr_body=f"## 證據\n{filler}\n"))


def test_evidence_fails_for_an_empty_code_block(repo):
    assert checks.check_evidence(repo.ctx(pr_body="## 證據\n```\n\n```\n"))


def test_evidence_fails_for_a_link_to_another_tickets_directory(repo):
    body = "## 證據\n[截圖](docs/evidence/T-001/login.png)\n"
    assert checks.check_evidence(repo.ctx(pr_body=body))


@pytest.mark.parametrize("body", [
    CODE_BLOCK,
    "## 證據\n~~~\n$ pytest\n~~~\n",
    "## 證據\n[CLI 輸出](docs/evidence/T-900/red-run.txt)\n",
    "## 證據\n[CLI 輸出](https://github.com/o/r/blob/ticket/T-900/docs/evidence/T-900/red-run.txt)\n",
    "## 證據\nhttps://github.com/o/r/tree/ticket/T-900/docs/evidence/T-900/\n",
])
def test_evidence_passes_with_a_code_block_or_a_link_to_its_evidence_directory(repo, body):
    assert checks.check_evidence(repo.ctx(pr_body=body)) == []


def _ticket_with(repo, tid, screens, paths=("app/feature/**",)):
    repo.checkout("milestone/M9")
    repo.commit({f"docs/tickets/{tid}.md": make_ticket(tid, list(paths), screens=screens)})
    repo.branch(f"ticket/{tid}")
    return repo.ctx(head_ref=f"ticket/{tid}", pr_body=CODE_BLOCK.replace("T-900", tid))


def test_evidence_fails_when_the_ticket_has_no_screens_field(repo):
    ctx = _ticket_with(repo, "T-905", screens=None)
    problems = checks.check_evidence(ctx)
    assert problems == ["T-905 的 front matter 沒有 screens: true/false（D-040），無法判定是否涉及畫面"]


@pytest.mark.parametrize("value", ["maybe", "yes", "True", "1", ""])
def test_evidence_fails_when_screens_is_not_true_or_false(repo, value):
    ctx = _ticket_with(repo, "T-906", screens=value)
    assert checks.check_evidence(ctx)


def test_evidence_requires_a_screenshot_when_screens_is_true(repo):
    ctx = _ticket_with(repo, "T-902", screens="true")
    assert checks.check_evidence(ctx) == ["T-902 涉及畫面（screens: true），但 docs/evidence/T-902/ 沒有任何截圖"]
    repo.commit({"docs/evidence/T-902/notes.txt": "not an image\n"})
    assert checks.check_evidence(ctx)  # 非圖片不算
    repo.commit({"docs/evidence/T-902/login.png": "png\n"})
    assert checks.check_evidence(ctx) == []


def test_screens_false_needs_no_screenshot_even_if_the_paths_mention_templates(repo):
    """D-040：不再用路徑字串猜；ticket 說沒有畫面就沒有畫面。"""
    ctx = _ticket_with(repo, "T-907", screens="false", paths=("app/modules/x/templates/**",))
    assert checks.check_evidence(ctx) == []


def test_screens_true_is_required_even_when_the_paths_do_not_mention_templates(repo):
    ctx = _ticket_with(repo, "T-908", screens="true", paths=("app/modules/iam/sign_in/**",))
    assert checks.check_evidence(ctx)


def test_the_m0_tickets_in_the_real_repo_declare_screens_false():
    from pathlib import Path
    for tid in ("T-001", "T-002", "T-003"):
        text = (Path(__file__).resolve().parents[2] / "docs" / "tickets" / f"{tid}.md").read_text(encoding="utf-8")
        assert checks.parse_ticket(text).get("screens") == "false", tid


# ------------------------------------------------------------------ commit-author（D-039：GitHub API 的 author.login）

BOT = {"login": "bullet-bots", "id": 354516064}


def api_commit(sha, login="bullet-bots", parents=1, email="354516064+bullet-bots@users.noreply.github.com"):
    """GitHub API（pulls/{n}/commits）回傳的 commit 物件的縮影。login=None 代表 author 是 null。"""
    return {
        "sha": sha * 40 if len(sha) == 1 else sha,
        "author": {"login": login, "id": 1} if login else None,
        "parents": [{"sha": "p" * 40}] * parents,
        "commit": {"author": {"email": email}},
    }


def test_commit_author_fails_for_a_commit_by_another_account():
    problems = checks.check_commit_author([api_commit("a"), api_commit("b", login="pitaya943")])
    assert problems == ["commit bbbbbbb 的作者帳號是 pitaya943，必須是 bullet-bots"]


def test_commit_author_fails_when_the_author_cannot_be_mapped_to_an_account():
    problems = checks.check_commit_author([api_commit("a", login=None, email="stranger@example.com")])
    assert len(problems) == 1 and "無法對應到 GitHub 帳號" in problems[0] and "stranger@example.com" in problems[0]


def test_commit_author_fails_for_a_merge_commit_by_another_account():
    problems = checks.check_commit_author([api_commit("a"), api_commit("c", login="pitaya943", parents=2)])
    assert problems == ["merge commit ccccccc 的作者帳號是 pitaya943，必須是 bullet-bots"]


def test_commit_author_accepts_a_github_generated_merge_commit_of_the_bot_whatever_its_email():
    """84852d9：GitHub 網頁合併，commit 的 email 是 bulletforbot@gmail.com，API 仍對應到 bullet-bots。"""
    merge = api_commit("84852d9ba4a449c77eb80c30cd356cd128adaa9a", parents=2, email="bulletforbot@gmail.com")
    assert checks.check_commit_author([api_commit("a"), merge]) == []


def test_commit_author_login_is_case_insensitive():
    assert checks.check_commit_author([api_commit("a", login="Bullet-Bots")]) == []


def test_commit_author_fails_closed_on_an_empty_list_and_on_the_api_cap():
    assert checks.check_commit_author([])
    assert checks.check_commit_author([api_commit("a")] * checks.API_MAX_COMMITS)


def test_the_email_is_no_longer_what_decides():
    """反向：email 是機器帳號的 noreply 但 API 說是別人 → 失敗（以帳號為準）。"""
    assert checks.check_commit_author([api_commit("a", login="pitaya943", email=checks.BOT_EMAIL)])


class FakeResponse:
    def __init__(self, payload):
        import json
        self._data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def fake_urlopen(pages, seen):
    def urlopen(req, timeout=None):
        seen.append(req)
        return FakeResponse(pages[len(seen) - 1])
    return urlopen


def test_fetch_pr_commits_pages_through_the_api_with_a_bearer_token():
    full = [api_commit(f"{i:040x}") for i in range(checks.API_PAGE)]
    seen = []
    commits = checks.fetch_pr_commits("o/r", 5, "TOKEN123", "https://api.example.test", fake_urlopen([full, [api_commit("z")]], seen))
    assert len(commits) == checks.API_PAGE + 1
    assert [r.full_url for r in seen] == [
        "https://api.example.test/repos/o/r/pulls/5/commits?per_page=100&page=1",
        "https://api.example.test/repos/o/r/pulls/5/commits?per_page=100&page=2",
    ]
    assert seen[0].get_header("Authorization") == "Bearer TOKEN123"


def test_fetch_pr_commits_fails_closed_without_leaking_the_token():
    def boom(req, timeout=None):
        raise OSError("connection refused for Bearer TOKEN123")
    with pytest.raises(checks.CheckError) as e:
        checks.fetch_pr_commits("o/r", 5, "TOKEN123", urlopen=boom)
    assert "TOKEN123" not in str(e.value)


def test_fetch_pr_commits_rejects_a_non_list_response():
    with pytest.raises(checks.CheckError):
        checks.fetch_pr_commits("o/r", 5, "T", urlopen=fake_urlopen([{"message": "Not Found"}], []))


def test_commit_author_range_checks_the_local_git_range_against_recorded_api_logins(repo):
    repo.commit({"app/feature/a.py": "1\n"})
    repo.commit({"app/feature/b.py": "2\n"}, author="someone@example.com")
    shas = checks.git(repo.ctx(), "rev-list", "milestone/M9..HEAD").stdout.split()
    ok = {sha: "bullet-bots" for sha in shas}
    assert checks.check_commit_author_range(repo.ctx(), ok, "milestone/M9..HEAD") == []
    wrong = dict(ok, **{shas[0]: "pitaya943"})
    assert checks.check_commit_author_range(repo.ctx(), wrong, "milestone/M9..HEAD")
    assert checks.check_commit_author_range(repo.ctx(), dict(ok, **{shas[0]: None}), "milestone/M9..HEAD")
    missing = {shas[0]: "bullet-bots"}
    assert checks.check_commit_author_range(repo.ctx(), missing, "milestone/M9..HEAD")  # 沒有紀錄 = fail-closed


def test_the_recorded_api_logins_for_main_to_milestone_m0_all_map_to_the_bot():
    """本地確認：origin/main..origin/milestone/M0 的 20 個 commit（含 GitHub 產生的 merge commit 84852d9）
    用 GitHub API 查到的作者帳號全是 bullet-bots（紀錄在 docs/evidence/T-002/milestone-M0-api-logins.json）。"""
    import json
    from pathlib import Path
    logins = json.loads((Path(__file__).resolve().parents[2] / "docs/evidence/T-002/milestone-M0-api-logins.json").read_text(encoding="utf-8"))
    assert len(logins) == 20 and "84852d9ba4a449c77eb80c30cd356cd128adaa9a" in logins
    commits = [{"sha": sha, "author": {"login": login} if login else None, "parents": []} for sha, login in logins.items()]
    assert checks.check_commit_author(commits) == []
