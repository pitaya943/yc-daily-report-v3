"""「只連本機」的檢查，刻意不依賴任何第三方套件，讓 scripts/dev/* 在安裝套件之前也能呼叫。

AGENTS.md 不可違反 #7：絕不連線到共用的 Supabase。libpq 有好幾條不經過 URL 主機名稱的路徑
（`hostaddr`、`host=` 參數、空主機時讀 PGHOST/PGHOSTADDR、`service=`、keyword/value DSN），
所以這裡逐一檢查，而不是只看 URL 的 hostname。錯誤訊息不含密碼。
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, urlsplit

LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}


class UnsafeDatabaseUrl(RuntimeError):
    pass


def _is_local_host(item: str) -> bool:
    # 絕對路徑 = unix socket 目錄；空字串由呼叫端另外處理
    return item.lower() in LOCAL_NAMES or item.startswith("/")


def _is_loopback_addr(item: str) -> bool:
    return item in {"127.0.0.1", "::1"}


def _refuse(what: str) -> UnsafeDatabaseUrl:
    return UnsafeDatabaseUrl(f"refusing to connect: {what}")


def assert_local_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("postgresql", "postgres"):
        raise _refuse("DATABASE_URL must be a postgresql:// URL")
    query = parse_qs(parts.query, keep_blank_values=True)
    if "service" in query:
        raise _refuse("'service' is not allowed (it can point to any host)")

    # URL 的主機（可能是逗號分隔的多主機，整串視為一個值，含非本機的一律拒絕）
    url_host = parts.hostname or ""
    hosts = [url_host] if url_host else []
    for value in query.get("host", []):
        hosts.extend(h for h in value.split(","))
    hostaddrs = [a for value in query.get("hostaddr", []) for a in value.split(",")]

    for h in hosts:
        if h == "" or not _is_local_host(h):
            raise _refuse(f"non-local database host {h!r}")
    for a in hostaddrs:
        if not _is_loopback_addr(a):
            raise _refuse(f"non-loopback hostaddr {a!r}")

    # 完全沒有指定主機：libpq 會讀 PGHOST / PGHOSTADDR，這兩個也必須是本機（或沒設）
    if not hosts and not hostaddrs:
        env_host = os.environ.get("PGHOST", "")
        env_addr = os.environ.get("PGHOSTADDR", "")
        if env_host and not all(h and _is_local_host(h) for h in env_host.split(",")):
            raise _refuse(f"PGHOST points to a non-local host {env_host!r}")
        if env_addr and not all(_is_loopback_addr(a) for a in env_addr.split(",")):
            raise _refuse("PGHOSTADDR points to a non-loopback address")
    elif hosts and not hostaddrs:
        # 有 host 沒 hostaddr 時，環境變數 PGHOSTADDR 仍會覆蓋解析結果
        env_addr = os.environ.get("PGHOSTADDR", "")
        if env_addr and not all(_is_loopback_addr(a) for a in env_addr.split(",")):
            raise _refuse("PGHOSTADDR points to a non-loopback address")


if __name__ == "__main__":  # scripts/dev/_common.sh 用：python3 -m app.core.local_url（URL 從環境變數讀，避免出現在 ps）
    try:
        assert_local_url(os.environ.get("DATABASE_URL", ""))
    except UnsafeDatabaseUrl as e:
        print(e)
        raise SystemExit(1)
