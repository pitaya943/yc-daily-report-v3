"""資料庫連線。

只連容器內（本機）的 PostgreSQL。`assert_local_url`（app/core/local_url.py）在連線前拒絕任何非本機位址，
包含 libpq 的 hostaddr / PGHOST / service 等繞過路徑，
這是 AGENTS.md 不可違反 #7（絕不連共用 Supabase）的程式層防線；錯誤訊息不含密碼。
"""
from __future__ import annotations

import os

import psycopg

from app.core.local_url import UnsafeDatabaseUrl, assert_local_url  # noqa: F401  (re-export)

DEFAULT_DATABASE_URL = "postgresql://postgres@127.0.0.1:5433/yc"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


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
