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
    "insert into public.whatever values (1);",   # 規則只限制 CREATE／ALTER／DROP／TRUNCATE
])
def test_sql_inside_yc_v3_is_accepted(sql):
    assert checks.sql_violations(sql) == [], sql


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
