"""資料庫連線。

只連容器內（本機）的 PostgreSQL。`assert_local_url` 在連線前拒絕任何非本機位址，
這是 AGENTS.md 不可違反 #7（絕不連共用 Supabase）的程式層防線；錯誤訊息不含密碼。
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit

import psycopg

DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5433/yc"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


class UnsafeDatabaseUrl(RuntimeError):
    pass


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def assert_local_url(url: str) -> None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    # 空 host 代表 unix socket；若 query 指定 host=，它必須是絕對路徑（socket 目錄）
    query_host = parse_qs(parts.query).get("host", [""])[0]
    if host in LOCAL_HOSTS and (not query_host or query_host.startswith("/") or query_host in LOCAL_HOSTS):
        return
    # 不回顯整串 URL（可能含密碼），只說主機名稱
    raise UnsafeDatabaseUrl(f"refusing to connect to non-local database host {host or query_host!r}")


def connect() -> psycopg.Connection:
    url = database_url()
    assert_local_url(url)
    # 所有表都在 yc_v3；SQL 仍寫出 schema 名稱，search_path 只是保險。
    return psycopg.connect(url, options="-c search_path=yc_v3")


def get_db():
    """FastAPI dependency：每個請求一條連線，結束時關閉。"""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()
