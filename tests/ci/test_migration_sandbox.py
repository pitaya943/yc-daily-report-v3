"""migration-scope 的第二層：把 migration 真的套用在拋棄式資料庫上，由 PostgreSQL 自己判定「有沒有碰 yc_v3 以外」。

靜態檢查（checks.sql_violations）再嚴，也追不完 SQL 的每種寫法（引號大小寫、dollar quoting、search_path、動態 SQL…）。
沙盒用沒有任何其他 schema 權限的登入角色執行，執行前後比對 yc_v3 以外的目錄與資料；引擎擋不住的（例如只建一個別的 schema）由比對抓到。
這些測試需要本機 PostgreSQL（與 tests/integration 相同；CI 的 tests job 有 service）。
"""
from pathlib import Path

import pytest

from app.core.db import database_url
from app.core.local_url import UnsafeDatabaseUrl
from scripts.ci import migration_sandbox as sb

ROOT = Path(__file__).resolve().parents[2]
GOOD = "create schema if not exists yc_v3;\ncreate table if not exists yc_v3.t (id int);\ninsert into yc_v3.t values (1);\n"


def run(*files):
    return sb.run_sandbox(database_url(), [(f"{i:04d}_x.sql", sql) for i, sql in enumerate(files, 1)])


def test_the_real_migrations_apply_cleanly_in_the_sandbox():
    migrations = [(p.name, p.read_text(encoding="utf-8")) for p in sorted((ROOT / "migrations").glob("*.sql"))]
    assert migrations and sb.run_sandbox(database_url(), migrations) == []


def test_a_clean_migration_passes():
    assert run(GOOD, "alter table yc_v3.t add column c int;") == []


@pytest.mark.parametrize("sql", [
    "drop table public.canary;",
    "insert into public.canary values (99);",
    "update public.canary set id = 1;",
    "delete from public.canary;",
    "truncate public.canary;",
    "alter table public.canary add column c int;",
    "comment on table public.canary is 'x';",
    "create table public.x (id int);",
    "create table x (id int);",                          # 沒寫 schema：落在 search_path，沙盒角色對 public 沒有 CREATE
    "select victim();",                                  # 沒寫 schema 的函式：看不到 public
    "select public.victim();",
    "create function yc_v3.f() returns void language plpgsql as $$ begin drop table public.canary; end $$; select yc_v3.f();",
    "create function yc_v3.f() returns void language plpgsql as $b$ begin execute 'drop table public.canary'; end $b$; select yc_v3.f();",
    "do $$ begin execute 'drop table public.canary'; end $$;",
    "reset role; drop table public.canary;",             # 想切回超級使用者：沙盒用獨立登入角色，沒有路可退
    "set role postgres; drop table public.canary;",
    "set session authorization postgres; drop table public.canary;",
    "create table canary_other.y (id int);",
])
def test_statements_that_touch_other_schemas_fail_in_the_sandbox(sql):
    problems = run(GOOD, sql)
    assert problems, sql
    assert "0002_x.sql" in problems[0] and "沙盒" in problems[0], problems


@pytest.mark.parametrize("sql", [
    'create schema "YC_V3";',                             # 引擎不擋（角色有資料庫的 CREATE），由前後比對抓到
    "create schema other_schema;",
    "create schema if not exists yc_v3; create schema yc_v4;",
])
def test_creating_a_schema_outside_yc_v3_is_caught_by_the_before_after_diff(sql):
    problems = run(GOOD, sql)
    assert problems and any("yc_v3 以外" in p for p in problems), problems


def test_the_verifiers_script_is_caught():
    script = (
        'CREATE SCHEMA "YC_V3";\nCREATE TABLE "YC_V3".outside (id int);\n'
        "CREATE FUNCTION yc_v3.f() RETURNS void LANGUAGE plpgsql AS $$ BEGIN DROP TABLE public.victim; END $$;\n"
        "SELECT yc_v3.f();\n"
    )
    assert run(GOOD, script)


def test_a_migration_that_fails_on_a_clean_database_is_reported_not_ignored():
    problems = run("select * from yc_v3.does_not_exist;")
    assert problems and "沙盒" in problems[0]


def test_the_sandbox_database_and_role_are_removed_afterwards(db):
    run(GOOD)
    with db.cursor() as cur:
        cur.execute("select count(*) from pg_database where datname like 'ci_sandbox_%'")
        assert cur.fetchone()[0] == 0
        cur.execute("select count(*) from pg_roles where rolname like 'ci_migrator_%'")
        assert cur.fetchone()[0] == 0


def test_the_sandbox_refuses_a_non_local_database():
    with pytest.raises(UnsafeDatabaseUrl):
        sb.run_sandbox("postgresql://postgres:secret@db.example.supabase.co:5432/postgres", [("0001_x.sql", GOOD)])
