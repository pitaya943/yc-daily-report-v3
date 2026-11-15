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
