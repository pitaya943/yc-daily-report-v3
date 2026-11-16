"""修正第 2 輪：Kuei 在 issue #7 的決定（D-044～D-049）與 Verifier 第 2 輪的問題。

D-044：檢查防的是 agent 的疏忽與常見的偷懶寫法，不防刻意的攻擊；
用允許清單、禁止整類寫法、比對結果的方式設計，不列舉語法。
每一節先寫會失敗的測試（單獨一個 commit），再寫實作。
"""
import pytest

from scripts.ci import checks, run
from tests.ci.conftest import make_ticket

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



# ------------------------------------------------------------------ D-045：migration 不得定義函式、程序、trigger、DO、lo_*

PROCEDURAL = [
    "create function yc_v3.f() returns int language sql as $$ select 1 $$;",
    "CREATE OR REPLACE FUNCTION yc_v3.f() RETURNS int LANGUAGE sql AS $$ SELECT 1 $$;",
    # Verifier 第 2 輪問題 1a：本體寫成單引號字串
    "create function yc_v3.cleanup() returns void language plpgsql as 'begin delete from public.canary; end';",
    "create function yc_v3.f() returns void language plpgsql as E'begin delete from public.canary; end';",
    # 問題 1b：本體裡用別名遮蔽 schema
    "create function yc_v3.touch() returns void language plpgsql as $$ begin perform public.victim() from yc_v3.audit_log as public; end $$;",
    # 問題 1c：本體裡把物件名稱寫在字串參數
    "create function yc_v3.f() returns void language plpgsql as $$ begin perform pg_catalog.setval('public.canary_id_seq', 1); end $$;",
    "create function yc_v3.f() returns int begin atomic select 1; end;",
    "create procedure yc_v3.p() language sql as $$ select 1 $$;",
    "create or replace procedure yc_v3.p() language plpgsql as $$ begin null; end $$;",
    "create trigger tr before insert on yc_v3.t for each row execute function yc_v3.f();",
    "create or replace trigger tr before insert on yc_v3.t for each row execute function yc_v3.f();",
    "create constraint trigger tr after insert on yc_v3.t for each row execute function yc_v3.f();",
    "create event trigger et on ddl_command_start execute function yc_v3.f();",
    "do $$ begin null; end $$;",
    "DO LANGUAGE plpgsql $x$ BEGIN NULL; END $x$;",
    # 問題 1 的 large object：不屬於任何 schema
    "select pg_catalog.lo_create(424242);",
    "select lo_create(0);",
    "SELECT LO_UNLINK(1);",
    "select lo_import('/etc/hostname');",
    "insert into yc_v3.t (o) values (lo_from_bytea(0, 'x'));",
]


@pytest.mark.parametrize("sql", PROCEDURAL)
def test_d045_procedural_code_is_rejected_as_a_class(sql):
    problems = checks.sql_violations(sql)
    assert problems and all("D-045" in p for p in problems if "D-045" in p) and any("D-045" in p for p in problems), (sql, problems)


@pytest.mark.parametrize("sql", [s for s in PROCEDURAL if "public" not in s and "lo_" not in s.lower()])
def test_d045_allow_functions_lifts_the_class_ban_but_not_the_schema_rule(sql):
    assert checks.sql_violations(sql, allow_functions=True) == [], (sql, checks.sql_violations(sql, allow_functions=True))


def test_d045_allow_functions_still_rejects_a_body_that_names_another_schema():
    sql = "create function yc_v3.f() returns void language plpgsql as $$ begin drop table public.victim; end $$;"
    assert checks.sql_violations(sql, allow_functions=True)


def test_d045_the_word_function_in_strings_and_comments_is_fine():
    sql = ("-- create function public.f() ...\n"
           "create table yc_v3.t (note text default 'create function x; do $$ $$; lo_create(1)');\n"
           "comment on column yc_v3.t.note is 'trigger 與 lo_unlink 只是文字';\n")
    assert checks.sql_violations(sql) == [], checks.sql_violations(sql)


VERIFIER_ROUND2 = """\
create table yc_v3.audit_log (id bigint generated always as identity primary key, note text);
create function yc_v3.cleanup() returns void language plpgsql
  as 'begin delete from public.canary; end';
create function yc_v3.touch() returns void language plpgsql
  as $$ begin perform public.victim() from yc_v3.audit_log as public; end $$;
select pg_catalog.lo_create(424242);
"""


@pytest.fixture
def mig_ticket(repo):
    def make(allow_functions=None):
        repo.checkout("milestone/M9")
        repo.commit({"docs/tickets/T-930.md": make_ticket("T-930", ["migrations/**"], migration=True, number='"0002"',
                                                           allow_functions=allow_functions)})
        repo._git("checkout", "-q", "-B", "ticket/T-930")
        return repo
    return make


def test_d045_the_verifiers_round2_migration_fails_migration_scope(mig_ticket):
    repo = mig_ticket()
    repo.commit({"migrations/0002_core.sql": VERIFIER_ROUND2})
    problems = checks.check_migration_scope(repo.ctx(head_ref="ticket/T-930"))
    joined = "\n".join(problems)
    for needle in ("yc_v3.cleanup", "yc_v3.touch", "lo_create"):
        assert any(needle in p and "D-045" in p for p in problems), (needle, joined)


@pytest.mark.parametrize("value", [None, False])
def test_d045_a_ticket_without_allow_functions_true_cannot_add_a_function(mig_ticket, value):
    repo = mig_ticket(allow_functions=value)
    repo.commit({"migrations/0002_f.sql": "create function yc_v3.f() returns int language sql as $$ select 1 $$;\n"})
    assert any("D-045" in p for p in checks.check_migration_scope(repo.ctx(head_ref="ticket/T-930")))


def test_d045_a_ticket_with_allow_functions_true_can_add_a_function(mig_ticket):
    repo = mig_ticket(allow_functions=True)
    repo.commit({"migrations/0002_f.sql": "create function yc_v3.f() returns int language sql as $$ select 1 $$;\n"})
    assert checks.check_migration_scope(repo.ctx(head_ref="ticket/T-930")) == []


def test_d045_a_merged_function_migration_does_not_block_later_tickets(repo):
    """allow_functions 的 ticket 合併後，之後的 ticket（沒有 allow_functions）不會因為那個已合併的檔案失敗。"""
    repo.checkout("milestone/M9")
    repo.commit({"migrations/0001_f.sql": "create function yc_v3.f() returns int language sql as $$ select 1 $$;\n"})
    repo._git("checkout", "-q", "-B", "ticket/T-900")
    repo.commit({"app/feature/a.py": "x = 1\n"})
    assert checks.check_migration_scope(repo.ctx()) == []


def test_d045_the_allow_functions_field_is_read_from_the_target_branch(mig_ticket):
    """PR 自己把 ticket 改成 allow_functions: true 沒有用（ticket 從目標分支讀）。"""
    repo = mig_ticket(allow_functions=False)
    repo.commit({
        "docs/tickets/T-930.md": make_ticket("T-930", ["migrations/**"], migration=True, number='"0002"', allow_functions=True),
        "migrations/0002_f.sql": "create function yc_v3.f() returns int language sql as $$ select 1 $$;\n",
    })
    assert any("D-045" in p for p in checks.check_migration_scope(repo.ctx(head_ref="ticket/T-930")))
