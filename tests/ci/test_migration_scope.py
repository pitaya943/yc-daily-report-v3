"""migration-scope：只能操作 yc_v3、編號與 ticket 一致、已合併的 migration 不得被修改。"""
import pytest

from scripts.ci import checks
from tests.ci.conftest import make_ticket

GOOD = "create schema if not exists yc_v3;\ncreate table if not exists yc_v3.t (id int);\n"


@pytest.mark.parametrize("sql", [
    "create table public.x (id int);",
    "create table other.x (id int);",
    "alter table public.accounts add column c int;",
    "drop table public.accounts;",
    "drop table yc_v3.a, public.b;",            # 清單中夾一個別的 schema
    "truncate public.accounts;",
    "truncate table yc_v3.a, other.b restart identity cascade;",
    "create schema other;",
    "drop schema public cascade;",
    "create index ix on public.t (id);",
    "create trigger tr before insert on public.t for each row execute function yc_v3.f();",
    "alter table yc_v3.t set schema public;",
    "create table x (id int);",                  # 沒寫 schema：落在 search_path
    "create temp table x (id int);",
    "create extension pgcrypto;",
    "create role someone;",
    "do $$ begin execute 'drop table public.t'; end $$;",
    "create or replace function public.f() returns int language sql as 'select 1';",
    "alter default privileges in schema public grant all on tables to x;",   # 不認得 → fail-closed
])
def test_sql_that_touches_another_schema_is_rejected(sql):
    assert checks.sql_violations(sql), sql


@pytest.mark.parametrize("sql", [
    GOOD,
    "-- drop table public.x;\ncreate table yc_v3.t (note text default 'drop table public.x');",   # 註解與字串不算
    "create unique index if not exists ix on yc_v3.t (id);",
    "alter table yc_v3.t add constraint c check (id > 0);",
    'create table "yc_v3"."T" (id int);',
    "drop table if exists yc_v3.a, yc_v3.b cascade;",
    "truncate yc_v3.a restart identity cascade;",
    "create trigger tr before insert on yc_v3.t for each row execute function yc_v3.f();",
    "create extension pgcrypto schema yc_v3;",
])
def test_sql_inside_yc_v3_is_accepted(sql):
    # D-045：定義 trigger／函式要 ticket 的 allow_functions: true；這裡驗證的是「只碰 yc_v3」那一部分
    assert checks.sql_violations(sql, allow_functions=True) == [], sql


def test_migration_scope_fails_for_a_migration_touching_public(repo):
    repo.checkout("milestone/M9")
    repo.commit({"docs/tickets/T-910.md": make_ticket("T-910", ["migrations/**"], migration=True, number='"0002"')})
    repo.branch("ticket/T-910")
    repo.commit({"migrations/0002_x.sql": "create table public.x (id int);\n"})
    problems = checks.check_migration_scope(repo.ctx(head_ref="ticket/T-910"))
    assert any("migrations/0002_x.sql" in p and "public" in p for p in problems), problems


@pytest.fixture
def migration_repo(repo):
    """目標分支上已有合併的 0001；T-910 是 migration: true、編號 0002 的 ticket。"""
    repo.checkout("milestone/M9")
    repo.commit({
        "migrations/0001_init.sql": GOOD,
        "docs/tickets/T-910.md": make_ticket("T-910", ["migrations/**"], migration=True, number='"0002"'),
    })
    repo.branch("ticket/T-910")
    return repo


def test_merged_migration_cannot_be_modified(migration_repo):
    migration_repo.commit({"migrations/0001_init.sql": GOOD + "alter table yc_v3.t add column c int;\n"})
    problems = checks.check_migration_scope(migration_repo.ctx(head_ref="ticket/T-910"))
    assert problems == ["migrations/0001_init.sql 已存在於目標分支，不得修改或刪除"]


def test_merged_migration_cannot_be_deleted(migration_repo):
    migration_repo.commit({"migrations/0001_init.sql": None})
    assert checks.check_migration_scope(migration_repo.ctx(head_ref="ticket/T-910"))


def test_a_migration_added_to_the_base_after_the_fork_is_not_blamed_on_the_pr(migration_repo):
    migration_repo.checkout("milestone/M9")
    migration_repo.commit({"migrations/0002_other.sql": GOOD})
    migration_repo.checkout("ticket/T-910")
    migration_repo.commit({"migrations/0003_mine.sql": GOOD})
    problems = checks.check_migration_scope(migration_repo.ctx(head_ref="ticket/T-910"))
    assert not any("0002_other" in p for p in problems)


def test_new_migration_must_use_the_ticket_number(migration_repo):
    migration_repo.commit({"migrations/0005_x.sql": GOOD})
    problems = checks.check_migration_scope(migration_repo.ctx(head_ref="ticket/T-910"))
    assert problems == ["migrations/0005_x.sql 的編號必須是 0002（T-910 的 migration_number）"]


def test_new_migration_with_the_right_number_passes(migration_repo):
    migration_repo.commit({"migrations/0002_x.sql": GOOD})
    assert checks.check_migration_scope(migration_repo.ctx(head_ref="ticket/T-910")) == []


def test_ticket_with_migration_false_cannot_add_a_migration(repo):
    repo.commit({"migrations/0001_x.sql": GOOD})
    problems = checks.check_migration_scope(repo.ctx())
    assert problems == ["T-900 的 migration 是 false，不得新增 migrations/0001_x.sql"]


# ---------------------------------------------------------------- 第 1 輪修正：Verifier 的繞過案例（先紅再修）

VERIFIER_SCRIPT = """
CREATE SCHEMA "YC_V3";
CREATE TABLE "YC_V3".outside (id int);
CREATE FUNCTION yc_v3.f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN DROP TABLE public.victim; END $$;
SELECT yc_v3.f();
INSERT INTO public.other_tbl SELECT 1 WHERE false;
"""


def test_the_exact_script_from_the_verifier_is_rejected_line_by_line():
    problems = checks.sql_violations(VERIFIER_SCRIPT)
    joined = "\n".join(problems)
    for needle in ('CREATE SCHEMA "YC_V3"', 'CREATE TABLE "YC_V3".outside', "DROP TABLE public.victim", "INSERT INTO public.other_tbl"):
        assert needle in joined, (needle, problems)


@pytest.mark.parametrize("sql", [
    # a. 有引號的識別字區分大小寫
    'create schema "YC_V3";',
    'create table "YC_V3".x (id int);',
    'create table "Yc_V3".x (id int);',
    'drop table "YC_V3".x;',
    'create table yc_v3."x" (id int); create table "PUBLIC".y (id int);',
    # b. dollar quoting：函式本體裡的語句
    "create function yc_v3.f() returns void language plpgsql as $$ begin drop table public.victim; end $$;",
    "create function yc_v3.f() returns void language plpgsql as $body$ begin drop table public.victim; end $body$;",
    "create function yc_v3.f() returns void language plpgsql as $a$ begin create table other.t (id int); end $a$;",
    "create function yc_v3.f() returns void language plpgsql as $$ begin insert into public.t values (1); end $$;",
    "create function yc_v3.f() returns void language plpgsql as $$ begin update public.t set a = 1; end $$;",
    "create function yc_v3.f() returns void language plpgsql as $$ begin delete from t; end $$;",
    "create function yc_v3.f() returns void language plpgsql as $$ begin execute 'drop table public.t'; end $$;",
    "create function yc_v3.f() returns void language sql as $$ select public.g() $$;",
    "do $$ begin null; end $$;",
    "do language plpgsql $x$ begin null; end $x$;",
    # c. DML 與其他語句
    "insert into public.other_tbl select 1;",
    "insert into other_tbl select 1;",
    "update public.t set a = 1;",
    "update t set a = 1;",
    "delete from public.t;",
    "delete from t where a = 1;",
    "with x as (select 1) insert into public.t select * from x;",
    "grant all on schema public to someone;",
    "grant select on public.t to someone;",
    "grant select on t to someone;",
    "grant usage on schema other to someone;",
    "revoke all on public.t from someone;",
    "grant someone to other_role;",
    "comment on table public.t is 'x';",
    "comment on table t is 'x';",
    "comment on column public.t.c is 'x';",
    "copy public.t from stdin;",
    "call public.p();",
    "reindex table public.t;",
    "cluster public.t;",
    "security label on table public.t is 'x';",
    "import foreign schema remote from server s into public;",
    "select public.f();",
    "select * from public.t;",
    "select 1 from yc_v3.a join public.b on true;",
    "set search_path = public;",
    "vacuum;",
    "lock table public.t;",
    "refresh materialized view public.m;",
    "create table yc_v3.a (x int references public.b(id));",
    "alter table yc_v3.a add foreign key (x) references other.b(id);",
    "foo bar baz;",                                   # 不認得的語句：fail-closed
    "select 'unterminated;",                           # 解析不了：fail-closed
])
def test_round1_sql_that_must_be_rejected(sql):
    assert checks.sql_violations(sql), sql


@pytest.mark.parametrize("sql", [
    "insert into yc_v3.t (a) values (1);",
    "update yc_v3.t as x set a = 1 where x.b = 2;",
    "delete from yc_v3.t where id = 1;",
    "grant select on yc_v3.t to someone;",
    "grant usage on schema yc_v3 to someone;",
    "comment on table yc_v3.t is 'x';",
    "comment on column yc_v3.t.c is 'x';",
    "select yc_v3.f();",
    "select pg_catalog.now();",
    "set local lock_timeout = '5s';",
    "create or replace function yc_v3.f() returns trigger language plpgsql as $$ begin new.updated := now(); return new; end $$;",
    "create function yc_v3.f() returns void language plpgsql as $tag$ begin insert into yc_v3.t values ('$$'); end $tag$;",
    "create function yc_v3.f() returns int language sql as $$ select count(*) from yc_v3.t x where x.id > 0 $$;",
    "insert into yc_v3.t (note) values ('drop table public.x; $$ do');",     # 字串裡的內容不算語句
    "create table yc_v3.t (n numeric default 1.5, r text default E'it\\'s');",
])
def test_round1_sql_that_must_still_be_accepted(sql):
    # D-045：見 test_sql_inside_yc_v3_is_accepted；函式定義在 allow_functions: false 時的拒絕見 test_fix_round2.py
    assert checks.sql_violations(sql, allow_functions=True) == [], (sql, checks.sql_violations(sql, allow_functions=True))
