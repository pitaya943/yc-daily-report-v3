"""「只連本機」的檢查（AGENTS.md 不可違反 #7：絕不連線到共用的 Supabase）。

刻意不依賴任何第三方套件，讓 scripts/dev/* 在安裝套件之前也能用 `python3 -m app.core.local_url` 呼叫。

設計：fail-closed
-----------------
libpq 決定「連到哪裡」的來源不只 URL 的主機名稱。依 PostgreSQL 17/18 文件
（libpq-connect「Connection URIs」「Parameter Key Words」、libpq-envars、libpq-pgservice）
以及本機實際載入的 libpq 18.6（`PQconndefaults()` 列出每個 keyword 對應的環境變數），來源有：

1. 連線字串本身：URI 的 authority（host[:port]，可逗號分隔多主機）與 query 參數
   `host`、`hostaddr`、`service`，以及 libpq 18 的 `oauth_issuer`（會對外連 HTTPS）。
2. service 檔：由 `service` 參數或環境變數 `PGSERVICE` 選定；檔案位置由 `PGSERVICEFILE`
   （預設 `~/.pg_service.conf`）與 `PGSYSCONFDIR`（系統的 `pg_service.conf`）決定。
   文件：「A service file setting overrides the corresponding environment variable」，
   所以 service 檔裡的 host/hostaddr 會蓋過 PGHOST，只輸給連線字串明寫的值。
3. 環境變數：`PGHOST`、`PGHOSTADDR`（在連線字串沒給時補上；`PGHOSTADDR` 即使 URL 有 host 也會生效）。
4. 內建預設：沒有任何 host → Unix socket（Linux），本機。

判斷方式不是「黑名單多擋幾個」，而是「只放行能證明是本機的」：

- URL：照 libpq 的 URI parser（fe-connect.c `conninfo_uri_parse_options` / `conninfo_uri_parse_params`）
  逐字元解析，不用 `urllib.parse.urlsplit`。兩者切 authority 的方式不同，例如
  `postgresql://localhost?@remote/yc`：urlsplit 看到 localhost，libpq 看到 user='localhost?'、host='remote'。
  query 參數只接受 `_ALLOWED_PARAMS` 白名單內、不會改變目標的參數；重複的參數也拒絕。
- 環境變數：`PGSERVICE`／`PGSERVICEFILE`／`PGSYSCONFDIR` 只要存在就拒絕（不去解析 service 檔：
  檔案有使用者／系統兩層、可能不存在、格式與版本有關，無法可靠地確定結果）。
  `PGHOST`／`PGHOSTADDR` 只要有值就必須是本機，不管 URL 是否已給 host。
  其餘以 `PG` 開頭（`PG_` 除外，libpq 從未使用這個前綴）而不在 `_HARMLESS_ENV` 的變數一律拒絕，
  讓未來 libpq 新增的變數預設是「擋」而不是「放」。

錯誤訊息不含密碼，也不含未知參數的值（可能是 secret）。
"""
from __future__ import annotations

import os

LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}
LOOPBACK_ADDRS = {"127.0.0.1", "::1"}

# URI 的 query 參數白名單：都不會改變連線目標。host/hostaddr 會另外逐一檢查。
_ALLOWED_PARAMS = {
    "host", "hostaddr", "port", "dbname", "user", "password",
    "application_name", "connect_timeout", "client_encoding", "options", "sslmode",
}

# 已知「不會改變連線目標」的環境變數。來源：PG17/18 libpq-envars 頁面全部條目，
# 加上 libpq 18.6 的 PQconndefaults() 與 libpq.so 字串中出現、文件未列的 PGOAUTHDEBUG。
# PGDATA 不是 libpq 讀的（initdb／pg_ctl 用），常見於開發者的 shell，所以也放行。
_HARMLESS_ENV = {
    "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGPASSFILE", "PGREQUIREAUTH", "PGCHANNELBINDING",
    "PGOPTIONS", "PGAPPNAME", "PGSSLMODE", "PGREQUIRESSL", "PGSSLNEGOTIATION", "PGSSLCOMPRESSION",
    "PGSSLCERT", "PGSSLKEY", "PGSSLCERTMODE", "PGSSLROOTCERT", "PGSSLCRL", "PGSSLCRLDIR", "PGSSLSNI",
    "PGREQUIREPEER", "PGSSLMINPROTOCOLVERSION", "PGSSLMAXPROTOCOLVERSION",
    "PGMINPROTOCOLVERSION", "PGMAXPROTOCOLVERSION",
    "PGGSSENCMODE", "PGKRBSRVNAME", "PGGSSLIB", "PGGSSDELEGATION",
    "PGCONNECT_TIMEOUT", "PGCLIENTENCODING",
    # 只在「已全部驗證為本機」的主機清單中挑選，不會引入新的目標
    "PGTARGETSESSIONATTRS", "PGLOADBALANCEHOSTS",
    # 連線後的 session 預設值與 libpq 內部用途
    "PGDATESTYLE", "PGTZ", "PGGEQO", "PGLOCALEDIR", "PGOAUTHDEBUG",
    "PGDATA",
}
# 會選定 service 檔、讓 service 檔決定 host 的環境變數：存在即拒絕
_SERVICE_ENV = ("PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR")

_URI_PREFIXES = ("postgresql://", "postgres://")
_HEX = set("0123456789abcdefABCDEF")


class UnsafeDatabaseUrl(RuntimeError):
    pass


def _refuse(what: str) -> UnsafeDatabaseUrl:
    return UnsafeDatabaseUrl(f"refusing to connect: {what}")


def _uri_decode(s: str) -> str:
    """libpq 的 conninfo_uri_decode：只處理 %XX（'+' 不是空白），%00 與不完整的 % 都是錯誤。"""
    out = bytearray()
    i = 0
    raw = s.encode("utf-8")
    while i < len(raw):
        c = raw[i]
        if c == 0x25:  # '%'
            h = raw[i + 1:i + 3].decode("ascii", "replace")
            if len(h) != 2 or not set(h) <= _HEX:
                raise _refuse("invalid percent-encoding in DATABASE_URL")
            b = int(h, 16)
            if b == 0:
                raise _refuse("forbidden %00 in DATABASE_URL")
            out.append(b)
            i += 3
        else:
            out.append(c)
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("percent-encoding in DATABASE_URL is not valid UTF-8") from None


def parse_libpq_uri(url: str) -> dict[str, str]:
    """照 libpq（fe-connect.c）解析 postgresql:// URI，回傳與 PQconninfoParse 相同的 keyword → value。

    不加入環境變數或 service 檔的預設值（那部分由 `_check_env` 處理）。任何 libpq 會報錯、
    或本函式無法確定與 libpq 一致的寫法，一律以 UnsafeDatabaseUrl 拒絕。
    """
    prefix = next((p for p in _URI_PREFIXES if url.startswith(p)), None)
    if prefix is None:
        # 包含 keyword/value DSN（"host=... dbname=..."）與空字串
        raise _refuse("DATABASE_URL must be a postgresql:// URL")
    if any(c.isspace() or not c.isprintable() for c in url):
        # libpq 對空白有自己的修剪規則（差分模糊測試發現 ' localhost' 與 libpq 結果不同）；不模仿，直接拒絕
        raise _refuse("DATABASE_URL contains whitespace or control characters (percent-encode them)")
    s = url[len(prefix):]
    n = len(s)
    out: dict[str, str] = {}

    # 1. user[:password]@ —— libpq 往前找第一個 '@' 或 '/'，遇到 '@' 才算有帳密
    p = 0
    while p < n and s[p] not in "@/":
        p += 1
    if p < n and s[p] == "@":
        cred, start = s[:p], p + 1
        user, sep, password = cred.partition(":")
        if user:
            out["user"] = _uri_decode(user)
        if sep and password:
            out["password"] = _uri_decode(password)
    else:
        start = 0

    # 2. host[:port] 清單（逗號分隔；IPv6 用方括號）
    p = start
    hosts: list[str] = []
    ports: list[str] = []
    while True:
        if p < n and s[p] == "[":
            q = s.find("]", p + 1)
            if q == -1 or q == p + 1:
                raise _refuse("malformed IPv6 host in DATABASE_URL")
            host = s[p + 1:q]
            p = q + 1
            if p < n and s[p] not in ":/?,":
                raise _refuse("unexpected character after IPv6 host in DATABASE_URL")
        else:
            q = p
            while q < n and s[q] not in ":/?,":
                q += 1
            host, p = s[p:q], q
        hosts.append(host)
        term = s[p] if p < n else ""
        if term == ":":
            q = p + 1
            while q < n and s[q] not in "/?,":
                q += 1
            ports.append(s[p + 1:q])
            p = q
            term = s[p] if p < n else ""
        else:
            ports.append("")
        if term != ",":
            break
        p += 1
    hostbuf, portbuf = ",".join(hosts), ",".join(ports)
    if hostbuf:
        out["host"] = _uri_decode(hostbuf)
    if portbuf:
        out["port"] = _uri_decode(portbuf)

    # 3. /dbname
    term = s[p] if p < n else ""
    if term and term != "?":
        q = s.find("?", p + 1)
        q = n if q == -1 else q
        dbname = s[p + 1:q]
        if dbname:
            out["dbname"] = _uri_decode(dbname)
        p = q
        term = s[p] if p < n else ""

    # 4. ?key=value&...（key 與 value 都會 percent-decode；libpq 讓後出現的覆蓋先出現的 → 這裡直接拒絕重複）
    if term:
        seen: set[str] = set()
        for item in s[p + 1:].split("&") if p + 1 < n else []:
            if item.count("=") != 1:
                raise _refuse("malformed query parameter in DATABASE_URL")
            k, v = item.split("=")
            key = _uri_decode(k)
            if key not in _ALLOWED_PARAMS:
                raise _refuse(f"query parameter {key!r} is not allowed")
            if key in seen:
                raise _refuse(f"query parameter {key!r} given more than once")
            seen.add(key)
            if key in out:
                # authority 已給、query 又給（libpq 以後者為準）：兩處說法不同時不猜，直接拒絕
                raise _refuse(f"{key!r} given both in the URL authority and as a query parameter")
            out[key] = _uri_decode(v)
    return out


def _is_local_host(item: str) -> bool:
    # 絕對路徑 = Unix socket 目錄。'@' 開頭（abstract namespace socket）用不到，不放行。
    return item.lower() in LOCAL_NAMES or item.startswith("/")


def _check_hosts(value: str, source: str) -> None:
    for h in value.split(","):
        if h == "" or not _is_local_host(h):
            raise _refuse(f"{source} names a non-local database host {h!r}")


def _check_hostaddrs(value: str, source: str) -> None:
    for a in value.split(","):
        if a not in LOOPBACK_ADDRS:
            raise _refuse(f"{source} names a non-loopback hostaddr {a!r}")


def _looks_like_conninfo(value: str) -> bool:
    # libpq 在某些呼叫方式下會把 dbname 當成連線字串展開；即使目前的呼叫路徑不會，也不放行
    return "=" in value or value.startswith(_URI_PREFIXES)


def _check_env(environ) -> None:
    for name in _SERVICE_ENV:
        if name in environ:
            raise _refuse(f"environment variable {name} is set (a service file can point to any host)")
    if environ.get("PGHOST"):
        _check_hosts(environ["PGHOST"], "PGHOST")
    if environ.get("PGHOSTADDR"):
        _check_hostaddrs(environ["PGHOSTADDR"], "PGHOSTADDR")
    if _looks_like_conninfo(environ.get("PGDATABASE", "")):
        raise _refuse("PGDATABASE looks like a connection string")
    for name in sorted(environ):
        if (name.startswith("PG") and not name.startswith("PG_")
                and name not in _HARMLESS_ENV and name not in ("PGHOST", "PGHOSTADDR")):
            raise _refuse(f"unrecognised libpq environment variable {name} (cannot prove it keeps the target local)")


def assert_local_url(url: str, environ=None) -> None:
    """URL 與環境變數合起來，libpq 的連線目標必須能證明是本機；否則丟出 UnsafeDatabaseUrl。"""
    environ = os.environ if environ is None else environ
    _check_env(environ)
    params = parse_libpq_uri(url)
    if "host" in params:
        _check_hosts(params["host"], "DATABASE_URL")
    if "hostaddr" in params:
        _check_hostaddrs(params["hostaddr"], "DATABASE_URL")
    if _looks_like_conninfo(params.get("dbname", "")):
        raise _refuse("dbname in DATABASE_URL looks like a connection string")
    # 沒有 host 也沒有 hostaddr：service 已被拒絕、PGHOST/PGHOSTADDR 已檢查，剩下的是內建預設（Unix socket）


if __name__ == "__main__":  # scripts/dev/_common.sh 用：python3 -m app.core.local_url（URL 從環境變數讀，避免出現在 ps）
    try:
        assert_local_url(os.environ.get("DATABASE_URL", ""))
    except UnsafeDatabaseUrl as e:
        print(e)
        raise SystemExit(1)
