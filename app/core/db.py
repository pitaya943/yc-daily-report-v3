"""資料庫連線。

只連容器內（本機）的 PostgreSQL。`assert_local_url`（app/core/local_url.py）在連線前拒絕任何非本機位址，
包含 libpq 的 hostaddr、PGHOST、PGSERVICE／service 檔等繞過路徑（判斷方式見 local_url.py 的 docstring），
這是 AGENTS.md 不可違反 #7（絕不連共用 Supabase）的程式層防線；錯誤訊息不含密碼。
connect() 另外用 libpq 自己的 PQconninfoParse 交叉比對 host／hostaddr，兩邊解析不一致就拒絕。
"""
from __future__ import annotations

import os

import psycopg
from psycopg.conninfo import conninfo_to_dict

from app.core.local_url import UnsafeDatabaseUrl, assert_local_url, parse_libpq_uri  # noqa: F401  (re-export)

DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5433/yc"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def connect() -> psycopg.Connection:
    url = database_url()
    assert_local_url(url)
    _assert_libpq_agrees(url)
    # 所有表都在 yc_v3；SQL 仍寫出 schema 名稱，search_path 只是保險。
    return psycopg.connect(url, options="-c search_path=yc_v3")


def _assert_libpq_agrees(url: str) -> None:
    """第二道防線：local_url 的 parser 是照 libpq 原始碼重寫的，若與實際載入的 libpq 看法不同就不連。"""
    try:
        theirs = conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        raise UnsafeDatabaseUrl("refusing to connect: libpq cannot parse DATABASE_URL") from None
    ours = parse_libpq_uri(url)
    for key in ("host", "hostaddr"):
        if ours.get(key) != theirs.get(key):
            raise UnsafeDatabaseUrl(f"refusing to connect: libpq reads {key} differently from the local-only check")


def get_db():
    """FastAPI dependency：每個請求一條連線，結束時關閉。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
