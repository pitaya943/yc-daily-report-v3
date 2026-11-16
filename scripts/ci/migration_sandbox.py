"""migration-scope 的第二層：在拋棄式資料庫上真的執行，由 PostgreSQL 自己判定有沒有碰 yc_v3 以外。

做法
1. 用本機資料庫的管理連線（只接受本機位址，與 app/core/db.py 同一道防線）建立拋棄式資料庫與一個「沙盒角色」。
2. 沙盒角色是獨立的登入角色（不是超級使用者、不是用 SET ROLE 切換）：migration 裡寫 `RESET ROLE`、
   `SET ROLE postgres` 都沒有路可退。它對 public 與其他 schema 沒有任何權限，只有資料庫的 CREATE
   （migration 0001 要 `create schema yc_v3`）。
3. 資料庫裡先放「誘餌」：public 與另一個 schema 的資料表、函式。
4. 依檔名順序套用全部 migration（同一個 transaction）；任何錯誤都回報，不吞掉。
5. 套用前後各拍一次 yc_v3 以外的目錄快照（schema、物件、權限、函式本體、資料表內容）；不同就回報。
   這一步抓得到引擎不會擋的事，例如只新建一個別的 schema（`create schema "YC_V3"`）。
6. 不論結果，最後刪掉拋棄式資料庫與角色。

限制：只檢查「migration 執行當下」做了什麼；函式本體日後被呼叫時才會發生的事，由 sql_scope 的靜態檢查負責。
"""
from __future__ import annotations

import secrets

from app.core.local_url import assert_local_url

SYSTEM_SCHEMAS = ("yc_v3", "information_schema")

SNAPSHOT_QUERIES = {
    "schemas": "select nspname, nspowner::regrole::text, nspacl::text from pg_namespace "
    "where nspname !~ '^pg_' and nspname <> all(%(sys)s) order by 1",
    "objects": "select n.nspname, c.relname, c.relkind::text, c.relowner::regrole::text, c.relacl::text, c.reloptions::text, "
    "obj_description(c.oid, 'pg_class') from pg_class c join pg_namespace n on n.oid = c.relnamespace "
    "where n.nspname !~ '^pg_' and n.nspname <> all(%(sys)s) order by 1, 2",
    "columns": "select n.nspname, c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull "
    "from pg_attribute a join pg_class c on c.oid = a.attrelid join pg_namespace n on n.oid = c.relnamespace "
    "where a.attnum > 0 and not a.attisdropped and n.nspname !~ '^pg_' and n.nspname <> all(%(sys)s) order by 1, 2, 3",
    "functions": "select n.nspname, p.proname, p.prokind::text, p.proacl::text, pg_get_functiondef(p.oid) "
    "from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
    "where p.prokind in ('f', 'p') and n.nspname !~ '^pg_' and n.nspname <> all(%(sys)s) order by 1, 2",
    "types": "select n.nspname, t.typname, t.typtype::text from pg_type t join pg_namespace n on n.oid = t.typnamespace "
    "where n.nspname !~ '^pg_' and n.nspname <> all(%(sys)s) and t.typtype in ('e', 'd', 'c') "
    "and not exists (select 1 from pg_class c where c.reltype = t.oid) order by 1, 2",
    "triggers": "select tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) from pg_trigger "
    "where not tgisinternal and tgrelid::regclass::text !~ '^yc_v3\\.' order by 1, 2",
}
CANARY = """
create schema canary_other;
create table canary_other.t (id int);
insert into canary_other.t values (1);
create table public.canary (id int);
insert into public.canary values (1), (2);
create function public.victim() returns int language sql as 'select 1';
"""


def _snapshot(conn) -> dict:
    snap: dict = {}
    for key, sql in SNAPSHOT_QUERIES.items():
        snap[key] = conn.execute(sql, {"sys": list(SYSTEM_SCHEMAS)}).fetchall()
    rows = conn.execute(
        "select quote_ident(n.nspname), quote_ident(c.relname) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where c.relkind = 'r' and n.nspname !~ '^pg_' and n.nspname <> all(%(sys)s) order by 1, 2",
        {"sys": list(SYSTEM_SCHEMAS)},
    ).fetchall()
    snap["data"] = [
        (s, t, conn.execute(f"select count(*), md5(coalesce(string_agg(x::text, ',' order by x::text), '')) from {s}.{t} x").fetchone())
        for s, t in rows
    ]
    return snap


def _diff(before: dict, after: dict) -> list[str]:
    out = []
    for key in before:
        if before[key] != after[key]:
            b, a = set(map(repr, before[key])), set(map(repr, after[key]))
            detail = "; ".join(sorted(a - b)[:2] + [f"（消失）{x}" for x in sorted(b - a)[:2]])
            out.append(f"{key} 在 {'、'.join(SYSTEM_SCHEMAS[:1])} 以外有變動：{detail[:200]}")
    return out


def run_sandbox(admin_url: str, migrations: list[tuple[str, str]]) -> list[str]:
    """回傳違規訊息（空 list = 通過）。migrations 是依序的 (檔名, SQL)。"""
    assert_local_url(admin_url)  # 與 app/core/db.py 相同的防線：絕不連共用的 Supabase
    import psycopg
    from psycopg.conninfo import make_conninfo

    tag = secrets.token_hex(5)
    db, role, password = f"ci_sandbox_{tag}", f"ci_migrator_{tag}", secrets.token_hex(16)
    problems: list[str] = []
    admin = psycopg.connect(admin_url, autocommit=True)
    try:
        admin.execute(f"create database {db}")
        admin.execute(f"create role {role} login password '{password}' nosuperuser nocreatedb nocreaterole")
        setup = psycopg.connect(make_conninfo(admin_url, dbname=db), autocommit=True)
        try:
            setup.execute("revoke all on schema public from public")
            setup.execute(f"grant create on database {db} to {role}")
            setup.execute(CANARY)
            before = _snapshot(setup)
            sandbox = psycopg.connect(make_conninfo(admin_url, dbname=db, user=role, password=password), autocommit=False)
            try:
                for name, sql in migrations:
                    try:
                        sandbox.execute(sql)
                    except psycopg.Error as e:
                        msg = (e.diag.message_primary or str(e)).splitlines()[0]
                        problems.append(f"{name} 在沙盒中執行失敗：{msg}")
                        break
                else:
                    sandbox.commit()
                    problems += [f"沙盒：{d}" for d in _diff(before, _snapshot(setup))]
            finally:
                sandbox.close()
        finally:
            setup.close()
    finally:
        admin.execute(f"drop database if exists {db} with (force)")
        admin.execute(f"drop role if exists {role}")
        admin.close()
    return problems
