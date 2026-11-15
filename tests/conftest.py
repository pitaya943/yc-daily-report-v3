"""測試框架的共用 fixture。

每個測試（含每個 scenario）開始前：
  1. 清空 yc_v3 的所有資料表（schema_migrations 除外）；
  2. 載入 spec/background.md 的固定帳戶；
  3. 把時鐘設成 background 指定的時間。
tests/unit/ 底下的純單元測試不需要資料庫，在 tests/unit/conftest.py 關掉這個 fixture。

資料庫必須已啟動並套用 migration（見 README.md）。
"""
from __future__ import annotations

import pytest

from app.core.clock import clock
from app.core.db import connect
from tests.support.background import parse_background

pytest_plugins = ["tests.support.bdd_plugin"]


@pytest.fixture
def db():
    conn = connect()
    yield conn
    conn.close()


def _truncate_all(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "select quote_ident(tablename) from pg_tables "
            "where schemaname = 'yc_v3' and tablename <> 'schema_migrations'"
        )
        tables = [r[0] for r in cur.fetchall()]
        if tables:
            cur.execute("truncate " + ", ".join(f"yc_v3.{t}" for t in tables) + " restart identity cascade")
    conn.commit()


def load_background(conn) -> None:
    bg = parse_background()
    with conn.cursor() as cur:
        for a in bg.accounts:
            cur.execute(
                "insert into yc_v3.accounts(name, role, zone, big_meter, archived) "
                "values (%(name)s, %(role)s, %(zone)s, %(big_meter)s, %(archived)s)",
                a,
            )
    conn.commit()
    clock.set(bg.clock)


@pytest.fixture(autouse=True)
def world(db):
    """乾淨的資料庫 + background 資料 + 固定時鐘。"""
    _truncate_all(db)
    load_background(db)
    yield
    clock.reset()
