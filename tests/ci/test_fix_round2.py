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


# 即使 allow_functions 也維持 fail-closed 的兩種：BEGIN ATOMIC 的本體沒有引號，依分號切開後的片段無法判定（第 1 輪起就是如此）；
# event trigger 是整個資料庫的物件，不在 yc_v3 之內。
@pytest.mark.parametrize("sql", [s for s in PROCEDURAL
                                 if "public" not in s and "lo_" not in s.lower() and "atomic" not in s and "event" not in s])
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


def test_d045_an_event_trigger_is_rejected_even_with_allow_functions():
    assert checks.sql_violations("create event trigger et on ddl_command_start execute function yc_v3.f();", allow_functions=True)


# ------------------------------------------------------------------ D-047：strings 只檢查傳給結果類別的錯誤訊息

APPENDIX_B = "| 欄位 | 錯誤訊息 |\n| --- | --- |\n| 顯示名稱 | 「請輸入顯示名稱」<br>「顯示名稱已被使用」 |\n"
IMPORTS = "from app.core.outcomes import Outcome, OutcomeError\nfrom app.core import outcomes\n"

# T-003（PR #4，ticket/T-003 的 app/core/permissions.py）實際的寫法：稽核說明是 f-string，FORBIDDEN 沒有訊息
T003_PERMISSIONS = (
    "from app.core import audit\n" + IMPORTS +
    "def authorize(actor, action, *rules, resource=None):\n"
    "    if actor is None:\n"
    "        raise OutcomeError(Outcome.UNAUTHENTICATED)\n"
    "    audit.write(actor, 'ACCESS_DENIED', f'嘗試執行但被拒絕：{action}')\n"
    "    raise OutcomeError(Outcome.FORBIDDEN)\n"
)


def _strings(repo, code, path="app/core/x.py"):
    repo.commit({"spec/appendix-b-fields.md": APPENDIX_B, path: code})
    return checks.check_strings(repo.ctx())


def test_d047_t003_audit_descriptions_are_not_checked(repo):
    """Verifier 第 2 輪問題 3：T-003 的稽核說明被誤擋。D-047：稽核說明由附錄 C 管。"""
    assert _strings(repo, T003_PERMISSIONS, "app/core/permissions.py") == []


def test_d047_chinese_text_that_is_not_passed_to_a_result_class_is_not_checked(repo):
    assert _strings(repo, 'LABEL = "某個介面文字"\ndef f():\n    return f"共 {1} 筆"\n') == []


@pytest.mark.parametrize("call", [
    'OutcomeError(Outcome.INVALID, "請輸入名字")',
    'OutcomeError(Outcome.INVALID, message="請輸入名字")',
    'outcomes.OutcomeError(outcomes.Outcome.CONFLICT, "請輸入名字")',
    'OutcomeError(Outcome.INVALID, "請輸入顯示名稱 ")',                       # 逐字：多一個空白也不行
    'OutcomeError(Outcome.INVALID, "請輸入顯示名稱" if a else "請輸入名字")',
])
def test_d047_a_message_that_is_not_in_appendix_b_fails(repo, call):
    problems = _strings(repo, IMPORTS + f"def f(a):\n    raise {call}\n")
    assert problems and "app/core/x.py:4" in problems[0], problems


@pytest.mark.parametrize("call", [
    'OutcomeError(Outcome.INVALID, f"請輸入{a}")',
    'OutcomeError(Outcome.INVALID, "請輸入" + "顯示名稱")',
    'OutcomeError(Outcome.INVALID, a)',
    'OutcomeError(Outcome.INVALID, MESSAGES[a])',
    'OutcomeError(Outcome.INVALID, "請輸入{}".format(a))',
    'OutcomeError(Outcome.INVALID, *a)',
    'OutcomeError(Outcome.INVALID, **a)',
    'OutcomeError(Outcome.INVALID, message=a)',
])
def test_d047_a_message_that_cannot_be_read_as_a_literal_fails(repo, call):
    """無法確定訊息內容（變數、拼接、格式化）一律失敗：訊息要逐字寫成字串常數。"""
    code = IMPORTS + "MESSAGES = {}\n" + f"def f(a):\n    raise {call}\n"
    assert _strings(repo, code), call


@pytest.mark.parametrize("call", [
    'OutcomeError(Outcome.FORBIDDEN)',
    'OutcomeError(Outcome.FORBIDDEN, None)',
    'OutcomeError(Outcome.INVALID, "請輸入顯示名稱")',
    'OutcomeError(Outcome.CONFLICT, message="顯示名稱已被使用")',
    'OutcomeError(Outcome.INVALID, "請輸入顯示名稱" if a else "顯示名稱已被使用")',
    'OutcomeError(Outcome.INVALID, NAME_REQUIRED)',                          # 模組層級的字串常數
])
def test_d047_messages_copied_verbatim_or_absent_pass(repo, call):
    code = IMPORTS + 'NAME_REQUIRED = "請輸入顯示名稱"\n' + f"def f(a):\n    raise {call}\n"
    assert _strings(repo, code) == [], (call, _strings(repo, code))


def test_d047_a_module_constant_that_is_not_in_appendix_b_fails(repo):
    code = IMPORTS + 'BAD = "請輸入名字"\ndef f():\n    raise OutcomeError(Outcome.INVALID, BAD)\n'
    assert _strings(repo, code)



# ------------------------------------------------------------------ D-046：no-weakened-tests 以結果判斷
# scripts/ci/test_report.py（pytest plugin）輸出每個測試 ID 的結果；目標分支上通過的每個 ID，在 PR 上都必須被收集而且通過。

import json  # noqa: E402
import os  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def _run_with_report(pytester, monkeypatch, out: Path, *args):
    """在子行程裡真的跑 pytest，載入 scripts.ci.test_report（子行程：os._exit 不會殺掉外層的測試）。"""
    # pytester 會把 HOME 換成暫存目錄，子行程因此看不到使用者層級的 site-packages；把目前的 sys.path 一併傳過去
    import sys
    paths = [str(ROOT), str(pytester.path)] + [p for p in sys.path if p and Path(p).is_dir()]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(paths))
    monkeypatch.setenv("YC_TEST_REPORT", str(out))
    return pytester.runpytest_subprocess("-p", "scripts.ci.test_report", "-p", "no:cacheprovider", *args)


def _read(out: Path):
    return checks.load_test_report(out)


def test_d046_the_plugin_records_every_test_id_and_its_outcome(pytester, monkeypatch):
    pytester.makepyfile(test_mix=(
        "import pytest\n"
        "def test_ok(): pass\n"
        "def test_bad(): assert False\n"
        "@pytest.mark.parametrize('n', [1, 2])\ndef test_param(n): pass\n"
        "@pytest.fixture\ndef broken(): raise RuntimeError\n"
        "def test_setup_error(broken): pass\n"
    ))
    out = pytester.path / "report.json"
    _run_with_report(pytester, monkeypatch, out)
    tests = _read(out)["tests"]
    assert tests == {
        "test_mix.py::test_ok": "passed",
        "test_mix.py::test_bad": "failed",
        "test_mix.py::test_param[1]": "passed",
        "test_mix.py::test_param[2]": "passed",
        "test_mix.py::test_setup_error": "failed",
    }


def test_d046_the_plugin_removes_a_stale_report_before_running(pytester, monkeypatch):
    """session 中途死掉時不能留下上一次的報告；沒有報告就判為失敗。"""
    pytester.makeconftest("import os\nos._exit(0)\n")
    pytester.makepyfile(test_a="def test_a(): pass\n")
    out = pytester.path / "report.json"
    out.write_text('{"tests": {"test_a.py::test_a": "passed"}}', encoding="utf-8")
    _run_with_report(pytester, monkeypatch, out)
    assert not out.exists()
    assert checks.load_test_report(out) is None


BASE_PASSED = {"tests": {"t.py::test_ok": "passed", "t.py::test_money": "passed", "t.py::test_was_red": "failed",
                         "t.py::test_not_implemented": "skipped"}}


@pytest.mark.parametrize("head,needle", [
    ({"t.py::test_ok": "passed"}, "test_money"),                                           # 消失
    ({"t.py::test_ok": "passed", "t.py::test_money": "failed"}, "test_money"),           # 變紅
    ({"t.py::test_ok": "passed", "t.py::test_money": "skipped"}, "test_money"),          # 被跳過
    ({"t.py::test_ok": "passed", "t.py::test_money": "xfailed"}, "test_money"),          # 預期失敗
    ({"t.py::test_ok": "passed", "t.py::test_money": "not-run"}, "test_money"),          # 收集了但沒執行
    ({"t.py::test_ok": "passed", "t.py::test_money_renamed": "passed"}, "test_money"),   # 改名 = 舊 ID 消失
])
def test_d046_a_test_that_passed_on_the_target_must_be_collected_and_pass(head, needle):
    problems = checks.compare_test_results(BASE_PASSED, {"tests": head})
    assert problems and any(needle in p for p in problems), problems


def test_d046_only_tests_that_passed_on_the_target_are_required():
    head = {"tests": {"t.py::test_ok": "passed", "t.py::test_money": "passed", "t.py::test_new": "passed"}}
    assert checks.compare_test_results(BASE_PASSED, head) == []


@pytest.mark.parametrize("base,head", [(None, {"tests": {}}), ({"tests": {}}, None), (None, None)])
def test_d046_a_missing_report_fails(base, head):
    problems = checks.compare_test_results(base, head)
    assert problems and any("報告" in p for p in problems), problems


@pytest.mark.parametrize("content", ["", "not json", "[]", '{"no_tests": 1}', '{"tests": []}'])
def test_d046_an_unreadable_report_counts_as_missing(tmp_path, content):
    p = tmp_path / "r.json"
    p.write_text(content, encoding="utf-8")
    assert checks.load_test_report(p) is None


# Verifier 第 2 輪問題 2 的四種寫法：會失敗的測試消失，pytest 仍回傳 0。用真的 pytest 在「目標分支」與「PR」各跑一次。
SABOTAGE = {
    "pycollect_makeitem": {"conftest.py": (
        "def pytest_pycollect_makeitem(collector, name, obj):\n"
        "    if 'money' in name:\n        return []\n")},
    "sessionstart_exit": {"conftest.py": (
        "import pytest\ndef pytest_sessionstart(session):\n    pytest.exit('done', returncode=0)\n")},
    "os_exit": {"conftest.py": "import os\nos._exit(0)\n"},
    "plugin_in_app": {
        "pytest.ini": "[pytest]\naddopts = -p app_plug\n",
        "app_plug.py": "def pytest_collection_modifyitems(items):\n    items[:] = [i for i in items if 'money' not in i.nodeid]\n",
    },
}


@pytest.mark.parametrize("name", sorted(SABOTAGE))
def test_d046_the_verifiers_four_ways_to_make_a_test_vanish_are_caught_by_results(pytester, monkeypatch, name):
    pytester.makepyfile(test_t="def test_ok(): pass\ndef test_money(): assert 1 + 1 == 2\n")
    base_out = pytester.path / "base.json"
    _run_with_report(pytester, monkeypatch, base_out)
    base = _read(base_out)
    assert base["tests"]["test_t.py::test_money"] == "passed"
    for path, text in SABOTAGE[name].items():
        (pytester.path / path).write_text(text, encoding="utf-8")
    (pytester.path / "test_t.py").write_text("def test_ok(): pass\ndef test_money(): assert 1 + 1 == 3\n", encoding="utf-8")
    head_out = pytester.path / "head.json"
    _run_with_report(pytester, monkeypatch, head_out)
    problems = checks.compare_test_results(base, _read(head_out))
    assert problems, name


def test_d046_run_py_fails_without_reports(monkeypatch, capsys):
    for var in ("CI_BASE_REF", "CI_HEAD_REF", "CI_BASE_SHA", "YC_BASE_TEST_REPORT", "YC_HEAD_TEST_REPORT"):
        monkeypatch.delenv(var, raising=False)
    assert run.main(["run.py", "no-weakened-tests"]) == 1
    assert "報告" in capsys.readouterr().out


def test_d046_run_py_compares_the_two_reports(monkeypatch, capsys, tmp_path):
    for var in ("CI_BASE_REF", "CI_HEAD_REF", "CI_BASE_SHA"):
        monkeypatch.delenv(var, raising=False)
    base, head = tmp_path / "b.json", tmp_path / "h.json"
    base.write_text(json.dumps(BASE_PASSED), encoding="utf-8")
    monkeypatch.setenv("YC_BASE_TEST_REPORT", str(base))
    monkeypatch.setenv("YC_HEAD_TEST_REPORT", str(head))
    head.write_text(json.dumps({"tests": {"t.py::test_ok": "passed"}}), encoding="utf-8")
    assert run.main(["run.py", "no-weakened-tests"]) == 1
    assert "test_money" in capsys.readouterr().out
    head.write_text(json.dumps({"tests": {"t.py::test_ok": "passed", "t.py::test_money": "passed"}}), encoding="utf-8")
    assert run.main(["run.py", "no-weakened-tests"]) == 0, capsys.readouterr().out


def test_d046_the_results_script_runs_a_tree_and_writes_a_report(tmp_path):
    """scripts/ci/test-results <原始碼目錄> <輸出>：CI 用它在同一個 job 裡跑出目標分支與 PR 的結果。"""
    import subprocess

    tree = tmp_path / "tree"
    (tree / "tests").mkdir(parents=True)
    (tree / "tests" / "test_a.py").write_text("def test_a(): pass\ndef test_b(): assert False\n", encoding="utf-8")
    out = tmp_path / "out.json"
    env = {k: v for k, v in os.environ.items() if k not in ("YC_TEST_REPORT", "DATABASE_URL")}
    r = subprocess.run([str(ROOT / "scripts" / "ci" / "test-results"), str(tree), str(out)], env=env,
                       capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr       # 測試失敗由比對判斷，腳本本身不因此失敗
    assert checks.load_test_report(out)["tests"] == {"tests/test_a.py::test_a": "passed", "tests/test_a.py::test_b": "failed"}


def test_d046_the_workflow_runs_the_target_branch_itself_in_the_same_job():
    """目標分支的結果要在同一個 job 裡實際跑出來，不使用 PR 提供的檔案或其他 job 的 artifact。"""
    import re

    wf = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = re.search(r"(?ms)^  no-weakened-tests:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", wf).group(1)
    assert re.search(r"(?m)^\s*image:\s*postgres:17\s*$", job)
    assert "download-artifact" not in job and "needs:" not in job
    assert re.search(r'git worktree add --detach "\$RUNNER_TEMP/base" "\$CI_BASE_SHA"', job)
    assert re.search(r'scripts/ci/test-results "\$RUNNER_TEMP/base" "\$YC_BASE_TEST_REPORT"', job)
    assert re.search(r'scripts/ci/test-results "\$GITHUB_WORKSPACE" "\$YC_HEAD_TEST_REPORT"', job)
    assert "run.py no-weakened-tests" in job


# ------------------------------------------------------------------ D-046：conftest 的 hook 採允許清單（語法掃描保留，給易懂的訊息）

@pytest.mark.parametrize("path", ["tests/conftest.py", "tests/unit/conftest.py", "conftest.py", "app/conftest.py"])
@pytest.mark.parametrize("hook", [
    "pytest_pycollect_makeitem(collector, name, obj)", "pytest_collection(session)", "pytest_sessionstart(session)",
    "pytest_itemcollected(item)", "pytest_make_collect_report(collector)", "pytest_runtestloop(session)",
    "pytest_bdd_apply_tag(tag, function)", "pytest_deselected(items)",
])
def test_d046_a_conftest_hook_outside_the_allowlist_is_rejected(repo, path, hook):
    repo.commit({path: f"def {hook}:\n    return None\n"})
    problems = checks.check_no_weakened_tests(repo.ctx())
    assert any(hook.split("(")[0] in p and "允許清單" in p for p in problems), problems


@pytest.mark.parametrize("code", [
    "def pytest_addoption(parser):\n    parser.addoption('--x')\n",
    "def pytest_configure(config):\n    config.addinivalue_line('markers', 'slow: x')\n",
    "def pytest_generate_tests(metafunc):\n    pass\n",
    "def pytest_bdd_before_scenario(request, feature, scenario):\n    pass\n",
    "pytest_plugins = ['tests.steps.common.steps']\n",
])
def test_d046_allowlisted_hooks_are_fine(repo, code):
    repo.commit({"tests/conftest.py": code})
    assert checks.check_no_weakened_tests(repo.ctx()) == []


@pytest.mark.parametrize("code", [
    "import pytest\ndef test_a():\n    pytest.exit('bye', returncode=0)\n",
    "import os\nos._exit(0)\n",
])
def test_d046_session_exits_get_a_readable_message(repo, code):
    repo.commit({"tests/conftest.py": code})
    assert checks.check_no_weakened_tests(repo.ctx())


def test_d046_the_real_conftests_pass_the_allowlist():
    assert checks.check_no_weakened_tests(checks.Ctx(root=ROOT)) == []


# ------------------------------------------------------------------ D-048：tests/support/** 只有 allowed_paths 明確列出時才能修改

SUPPORT = "tests/support/bdd_plugin.py"
SUPPORT_TEXT = ("import pytest\ndef pytest_collection_modifyitems(config, items):\n"
                "    for item in items:\n        item.add_marker(pytest.mark.skip(reason='not implemented'))\n")


@pytest.fixture
def support_repo(repo):
    def make(paths):
        repo.checkout("milestone/M9")
        repo.commit({SUPPORT: SUPPORT_TEXT, "tests/support/other.py": "X = 1\n",
                     "docs/tickets/T-940.md": make_ticket("T-940", paths)})
        repo._git("checkout", "-q", "-B", "ticket/T-940")
        return repo
    return make


@pytest.mark.parametrize("paths", [["tests/**"], ["tests/support/**"], ["tests/support/*.py"], ["tests/support/other.py"]])
def test_d048_modifying_a_support_file_not_listed_explicitly_fails(support_repo, paths):
    repo = support_repo(paths)
    repo.commit({SUPPORT: SUPPORT_TEXT + "# changed\n"})
    problems = checks.check_no_weakened_tests(repo.ctx(head_ref="ticket/T-940"))
    assert any("D-048" in p and SUPPORT in p for p in problems), problems


def test_d048_deleting_a_support_file_not_listed_explicitly_fails(support_repo):
    repo = support_repo(["tests/**"])
    repo.commit({"tests/support/other.py": None})
    assert any("D-048" in p for p in checks.check_no_weakened_tests(repo.ctx(head_ref="ticket/T-940")))


def test_d048_a_ticket_that_lists_the_file_explicitly_may_modify_it(support_repo):
    """明確列出時可以修改，由 Verifier 審查 diff；結果比對仍然生效。不再要求「與目標分支完全相同」。"""
    repo = support_repo(["tests/**", SUPPORT])
    repo.commit({SUPPORT: SUPPORT_TEXT + "# changed\n"})
    assert checks.check_no_weakened_tests(repo.ctx(head_ref="ticket/T-940")) == []


def test_d048_the_listing_is_read_from_the_target_branch(support_repo):
    repo = support_repo(["tests/**"])
    repo.commit({SUPPORT: SUPPORT_TEXT + "# changed\n", "docs/tickets/T-940.md": make_ticket("T-940", ["tests/**", SUPPORT])})
    assert any("D-048" in p for p in checks.check_no_weakened_tests(repo.ctx(head_ref="ticket/T-940")))


def test_d048_adding_a_new_support_file_is_not_a_modification(support_repo):
    """T-001 就是新增 tests/support/ 的 ticket。新檔案不是「修改」；它若讓既有測試消失，結果比對會抓到。"""
    repo = support_repo(["tests/**"])
    repo.commit({"tests/support/new_plugin.py": SUPPORT_TEXT})
    assert checks.check_no_weakened_tests(repo.ctx(head_ref="ticket/T-940")) == []
