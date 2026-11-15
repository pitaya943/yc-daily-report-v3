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
