# 共用設定，由其他腳本 `source`。不要直接執行。
# 只管理「容器內」的 PostgreSQL 17（D-033）；絕不連線到共用的 Supabase 專案。
set -euo pipefail

PG_VERSION=17
PG_BIN="${PG_BIN:-/usr/lib/postgresql/${PG_VERSION}/bin}"
PG_PORT="${YC_PG_PORT:-5433}"            # 避開 apt 預設叢集使用的 5432
PG_DB="${YC_PG_DB:-yc}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# 資料目錄：root（容器常見）用 /var/lib/yc-pg17，一般使用者用 ~/.local/share/yc-pg17。
if [ "$(id -u)" = "0" ]; then
  PG_DATA="${YC_PG_DATA:-/var/lib/yc-pg17}"
  # PostgreSQL 拒絕以 root 執行，改用 postgres 系統使用者
  as_pg() { runuser -u postgres -- "$@"; }
else
  PG_DATA="${YC_PG_DATA:-$HOME/.local/share/yc-pg17}"
  as_pg() { "$@"; }
fi
PG_LOG="${YC_PG_LOG:-/tmp/yc-pg17.log}"

# 預設連線字串：只聽 127.0.0.1，trust 驗證（不存在任何密碼）
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres@127.0.0.1:${PG_PORT}/${PG_DB}}"

# 防線：非本機位址一律拒絕
assert_local_database_url() {
  # 與 app/core/db.py 同一份檢查（app/core/local_url.py，不依賴第三方套件）；URL 走環境變數，不出現在 ps
  local msg
  if ! msg="$(cd "$REPO_ROOT" && DATABASE_URL="$DATABASE_URL" python3 -m app.core.local_url)"; then
    echo "$msg。本專案只使用容器內的 PostgreSQL。" >&2
    exit 1
  fi
}

require_pg_binaries() {
  if [ ! -x "$PG_BIN/postgres" ]; then
    echo "找不到 PostgreSQL ${PG_VERSION}（$PG_BIN）。先執行：scripts/dev/install-postgres" >&2
    exit 1
  fi
}

psql_app() { PGOPTIONS="-c client_min_messages=warning" "$PG_BIN/psql" "$DATABASE_URL" -v ON_ERROR_STOP=1 -X -q "$@"; }
