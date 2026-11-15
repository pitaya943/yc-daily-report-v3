"""AGENTS.md 不可違反 #7：只連容器內的 PostgreSQL，絕不連共用的 Supabase。"""
import pytest

from app.core.db import UnsafeDatabaseUrl, assert_local_url


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:5433/yc",
    "postgresql://postgres@localhost:5433/yc",
    "postgresql://postgres@[::1]:5433/yc",
    "postgresql:///yc?host=/var/run/postgresql",
])
def test_local_urls_are_accepted(url):
    assert_local_url(url)


@pytest.mark.parametrize("url", [
    "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres",
    "postgresql://postgres.abc:pw@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres",
    "postgresql://u@10.0.0.5:5432/yc",
    "postgresql://u@example.com/yc",
])
def test_remote_urls_are_refused(url):
    with pytest.raises(UnsafeDatabaseUrl):
        assert_local_url(url)


def test_refusal_message_does_not_leak_the_password():
    with pytest.raises(UnsafeDatabaseUrl) as e:
        assert_local_url("postgresql://u:s3cretpw@db.x.supabase.co:5432/postgres")
    assert "s3cretpw" not in str(e.value)


# --- 修正第 1 輪：libpq 的 hostaddr / PGHOST / service 等繞過 host 檢查的路徑 ---

@pytest.mark.parametrize("url", [
    "postgresql://u@localhost/yc?hostaddr=203.0.113.5",           # libpq 以 hostaddr 為準
    "postgresql://u@127.0.0.1/yc?hostaddr=203.0.113.5",
    "postgresql:///yc?hostaddr=203.0.113.5",
    "postgresql://u@localhost/yc?host=db.x.supabase.co",
    "postgresql:///yc?host=db.x.supabase.co",
    "postgresql://localhost,db.x.supabase.co/yc",                 # 多主機
    "postgresql://u@localhost/yc?service=prod",                   # pg_service.conf 可帶任意 host
    "host=db.x.supabase.co dbname=postgres",                      # keyword/value DSN，不是 URL
    "",
])
def test_libpq_bypasses_are_refused(url):
    with pytest.raises(UnsafeDatabaseUrl):
        assert_local_url(url)


@pytest.mark.parametrize("url", [
    "postgresql://u@localhost/yc?hostaddr=127.0.0.1",
    "postgresql://u@localhost/yc?hostaddr=::1",
])
def test_loopback_hostaddr_is_accepted(url):
    assert_local_url(url)


def test_empty_host_follows_PGHOST_so_it_must_be_local(monkeypatch):
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.delenv("PGHOSTADDR", raising=False)
    assert_local_url("postgresql:///yc")  # 沒有 PGHOST：走 unix socket
    monkeypatch.setenv("PGHOST", "db.x.supabase.co")
    with pytest.raises(UnsafeDatabaseUrl):
        assert_local_url("postgresql:///yc")
    monkeypatch.setenv("PGHOST", "/var/run/postgresql")
    assert_local_url("postgresql:///yc")
    monkeypatch.delenv("PGHOST")
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.5")
    with pytest.raises(UnsafeDatabaseUrl):
        assert_local_url("postgresql:///yc")


# --- 修正第 2 輪：環境變數 PGSERVICE（與 service 檔）繞過防線；改為 fail-closed ---
# 情境來自 Verifier 第 2 輪（PR #2 issuecomment-6899883854）。只用 `.invalid` 網域（RFC 6761 保證解析失敗），
# 不會真的連出去。

import os
import subprocess
from pathlib import Path

import app.core.db as dbmod

REPO_ROOT = Path(__file__).resolve().parents[2]

# 測試時要清掉的、可能影響 libpq 連線目標的環境變數（不讓開發者自己的 shell 干擾結果）
_TARGET_ENV = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")


@pytest.fixture
def clean_pg_env(monkeypatch, tmp_path):
    for name in list(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(tmp_path))  # 預設的 ~/.pg_service.conf 也指到乾淨的目錄
    return tmp_path


@pytest.fixture
def evil_service(clean_pg_env):
    svc = clean_pg_env / "svc.conf"
    svc.write_text("[evil]\nhost=remote-db.invalid\n")
    return svc


def test_PGSERVICE_with_hostless_url_is_refused(monkeypatch, evil_service):
    monkeypatch.setenv("PGSERVICEFILE", str(evil_service))
    monkeypatch.setenv("PGSERVICE", "evil")
    with pytest.raises(UnsafeDatabaseUrl, match="PGSERVICE is set"):
        assert_local_url("postgresql:///yc")


def test_db_connect_refuses_PGSERVICE_before_libpq_resolves_anything(monkeypatch, evil_service):
    """Verifier 的重現：connect() 必須以 UnsafeDatabaseUrl 拒絕，而不是讓 libpq 去解析遠端主機。"""
    monkeypatch.setenv("PGSERVICEFILE", str(evil_service))
    monkeypatch.setenv("PGSERVICE", "evil")
    monkeypatch.setenv("DATABASE_URL", "postgresql:///yc")
    with pytest.raises(UnsafeDatabaseUrl):
        dbmod.connect()


def test_PGSERVICE_alone_uses_the_default_service_file_and_is_refused(monkeypatch, clean_pg_env):
    (clean_pg_env / ".pg_service.conf").write_text("[evil]\nhost=remote-db.invalid\n")
    monkeypatch.setenv("PGSERVICE", "evil")
    with pytest.raises(UnsafeDatabaseUrl, match="PGSERVICE is set"):
        assert_local_url("postgresql:///yc")


@pytest.mark.parametrize("name,value", [
    ("PGSERVICE", ""),                    # 設了但是空的：仍然拒絕，不猜 libpq 怎麼處理
    ("PGSERVICEFILE", "/nonexistent/svc.conf"),
    ("PGSYSCONFDIR", "/nonexistent"),
])
def test_service_selection_env_vars_are_refused_even_with_an_explicit_local_host(monkeypatch, clean_pg_env, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(UnsafeDatabaseUrl, match=f"{name} is set"):
        assert_local_url("postgresql://postgres@127.0.0.1:5433/yc")


def test_non_local_PGHOST_is_refused_even_when_the_url_names_a_local_host(monkeypatch, clean_pg_env):
    monkeypatch.setenv("PGHOST", "remote-db.invalid")
    with pytest.raises(UnsafeDatabaseUrl, match="PGHOST"):
        assert_local_url("postgresql://postgres@127.0.0.1:5433/yc")


def test_unrecognised_PG_env_var_is_refused(monkeypatch, clean_pg_env):
    """未來的 libpq 可能新增會改變目標的變數；不認得就拒絕（fail-closed）。"""
    monkeypatch.setenv("PGFUTURETARGET", "remote-db.invalid")
    with pytest.raises(UnsafeDatabaseUrl, match="PGFUTURETARGET"):
        assert_local_url("postgresql://postgres@127.0.0.1:5433/yc")


@pytest.mark.parametrize("name,value", [
    ("PGPORT", "5433"), ("PGUSER", "postgres"), ("PGDATABASE", "yc"), ("PGPASSWORD", "x"),
    ("PGOPTIONS", "-c client_min_messages=warning"), ("PGAPPNAME", "t"), ("PGCONNECT_TIMEOUT", "3"),
    ("PGSSLMODE", "disable"), ("PGTZ", "UTC"), ("PGDATA", "/var/lib/yc-pg17"),
])
def test_env_vars_that_cannot_change_the_target_are_accepted(monkeypatch, clean_pg_env, name, value):
    monkeypatch.setenv(name, value)
    assert_local_url("postgresql://postgres@127.0.0.1:5433/yc")


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:5433/yc?servicefile=/tmp/svc.conf",   # 不在 allowlist 的參數
    "postgresql://postgres@127.0.0.1:5433/yc?%73ervice=evil",             # libpq 會把 key 做 percent-decode
    "postgresql://postgres@127.0.0.1:5433/yc?oauth_issuer=https://remote-db.invalid",  # libpq 18 會對外連線
    "postgresql://postgres@127.0.0.1:5433/yc?ssl=true&service=evil",
    "postgresql://localhost?@remote-db.invalid/yc",   # urlsplit 看到 localhost；libpq 看到 user='localhost?'
    "postgresql://localhost#@remote-db.invalid/yc",   # 同上，'#' 對 libpq 不是特殊字元
    "postgresql:///yc?host=@abstract",                 # abstract namespace socket：用不到，不放行
    "postgresql:// localhost/yc",                      # libpq 會修剪空白，不模仿，直接拒絕
    "postgresql://localhost/yc?host=localhost",        # authority 與 query 都給 host
])
def test_url_shapes_that_could_hide_a_remote_target_are_refused(clean_pg_env, url):
    with pytest.raises(UnsafeDatabaseUrl):
        assert_local_url(url)


@pytest.mark.parametrize("url", [
    "postgresql://postgres@127.0.0.1:5433/yc",
    "postgres://postgres@localhost:5433/yc?sslmode=disable&application_name=t",
    "postgresql://postgres@[::1]:5433/yc",
    "postgresql://%2Fvar%2Frun%2Fpostgresql:5433/yc",
    "postgresql:///yc?host=/var/run/postgresql&port=5433",
    "postgresql://localhost,127.0.0.1/yc",
    "postgresql://u@localhost/yc?hostaddr=127.0.0.1",
    "postgresql://localhost?@remote-db.invalid/yc",
    "postgresql://u:p%40ss@127.0.0.1:5433/yc?options=-c%20search_path%3Dyc_v3",
])
def test_our_url_parser_agrees_with_libpq_on_the_target(url):
    """差分測試：自寫的 parser 對 host / hostaddr 的看法必須與 libpq 的 PQconninfoParse 一致。"""
    from psycopg.conninfo import conninfo_to_dict

    from app.core.local_url import parse_libpq_uri

    ours = parse_libpq_uri(url)
    theirs = conninfo_to_dict(url)
    assert ours.get("host") == theirs.get("host")
    assert ours.get("hostaddr") == theirs.get("hostaddr")


def test_parser_agrees_with_libpq_on_random_uris():
    """固定 seed 的差分模糊測試：凡是我們接受的 URI，host/hostaddr 必須與 libpq 一致，而且 libpq 也能解析。"""
    import random

    from psycopg.conninfo import conninfo_to_dict

    from app.core.local_url import parse_libpq_uri

    rng = random.Random(20261115)
    atoms = ["localhost", "127.0.0.1", "[::1]", "remote-db.invalid", "@", "?", "#", ":", "/", ",", "%2F", "%40",
             "%3F", "&", "=", "u", "pw", "5433", "yc", "host=", "hostaddr=", "hostaddr=127.0.0.1",
             "host=remote-db.invalid", "[", "]", "%", "%00", "%zz", "+", " "]
    accepted = 0
    for _ in range(5000):
        url = rng.choice(["postgresql://", "postgres://"]) + "".join(rng.choice(atoms) for _ in range(rng.randint(0, 8)))
        try:
            ours = parse_libpq_uri(url)
        except UnsafeDatabaseUrl:
            continue
        theirs = conninfo_to_dict(url)  # 我們接受的，libpq 一定要能解析
        assert (ours.get("host"), ours.get("hostaddr")) == (theirs.get("host"), theirs.get("hostaddr")), url
        accepted += 1
    assert accepted > 1000  # 確認真的有比對到東西


def test_migrate_script_refuses_PGSERVICE_before_running_psql(evil_service):
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGSERVICEFILE=str(evil_service), PGSERVICE="evil", DATABASE_URL="postgresql:///yc",
               HOME=str(evil_service.parent))
    r = subprocess.run([str(REPO_ROOT / "scripts/dev/migrate")], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 1, r.stderr
    assert "refusing to connect" in r.stderr
    assert "PGSERVICE" in r.stderr
    assert "remote-db.invalid" not in r.stderr   # 防線在 psql 之前擋下，沒有人去解析遠端主機


def test_db_connect_refuses_when_our_parser_and_libpq_disagree(monkeypatch, clean_pg_env):
    """第二道防線：假設 parse_libpq_uri 有 bug、把遠端看成本機，connect() 仍要因與 libpq 不一致而拒絕。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@remote-db.invalid/yc")
    monkeypatch.setattr(dbmod, "assert_local_url", lambda url: None)               # 模擬第一道防線被騙過
    monkeypatch.setattr(dbmod, "parse_libpq_uri", lambda url: {"host": "localhost"})
    with pytest.raises(UnsafeDatabaseUrl, match="differently"):
        dbmod.connect()
