# 員工日報系統

工程隊用的日報、審核、薪資、材料、流水帳與檔案庫系統。

- 行為規格：[`spec/README.md`](spec/README.md)
- 開發流程：[`docs/workflow.md`](docs/workflow.md)
- Milestone 計畫：[`docs/milestones/README.md`](docs/milestones/README.md)
- 進度：[`docs/board.md`](docs/board.md)
- 決定：[`docs/decisions.md`](docs/decisions.md)

技術：Python 3.12+、FastAPI、Jinja、HTMX、PostgreSQL 17（schema `yc_v3`）、pytest-bdd。

## 開發指令

以下指令在 repo 根目錄執行。容器沒有 Docker daemon，PostgreSQL 17 直接用 apt 安裝（D-033）；
資料庫只聽 `127.0.0.1:5433`，**絕不連線到共用的 Supabase 專案**（腳本與 `app/core/db.py` 都會拒絕非本機位址）。

| 步驟 | 指令 | 說明 |
| --- | --- | --- |
| 1. 安裝 PostgreSQL 17 | `scripts/dev/install-postgres` | 需要 root；從 PGDG（`apt.postgresql.org`，noble-pgdg）安裝 `postgresql-17`。已安裝就略過。 |
| 2. 安裝 Python 套件 | `pip install -e '.[dev]'` | 建議先建立 venv。 |
| 3. 啟動資料庫 | `scripts/dev/db-start` | 專用資料目錄（root：`/var/lib/yc-pg17`；一般使用者：`~/.local/share/yc-pg17`），連接埠 5433，資料庫 `yc`。可重複執行。 |
| 4. 套用 migration | `scripts/dev/migrate` | 依編號套用 `migrations/NNNN_*.sql` 到 `yc_v3`，可重複執行；已套用的檔案被改過會拒絕。 |
| 5. 執行測試 | `python3 -m pytest` | 全部測試。每個測試前清空 `yc_v3` 並載入 `spec/background.md` 的固定資料。 |
| 6. 啟動應用程式 | `scripts/dev/run` | `http://127.0.0.1:8000`；`GET /health` 確認應用程式與資料庫都通。 |

其他：`scripts/dev/db-stop` 停止資料庫（資料保留）；`scripts/dev/db-reset` 刪除並重建資料庫後重新套用 migration。

預設連線字串 `postgresql://postgres@127.0.0.1:5433/yc`（可用環境變數 `DATABASE_URL` 覆寫，但只接受本機位址）。

### 測試怎麼運作

> **注意：** 測試會清空 `DATABASE_URL` 指向的資料庫裡 `yc_v3` 的所有資料表（`schema_migrations` 除外）。開發用的資料和測試共用同一個本機資料庫，跑完測試後開發資料就沒了；要手動試用請在測試之後重新匯入。

- `tests/test_spec.py` 把 `spec/features/*.feature` 的每個 scenario 變成 pytest 測試。
- **`tests/implemented.txt`** 列出已實作的規則 ID（例如 `IAM-R01`，一行一個）。只有列在其中的 Rule 底下的 scenario 會被執行；
  其他一律 skip，原因顯示「尚未實作」，不算失敗。實作一條規則的 ticket 要在同一個 PR 把它的 ID 加進清單。
- 步驟實作放在 `tests/steps/<feature ID>/`；框架自己的測試在 `tests/unit/`、`tests/integration/`。
- 時間一律經過 `app/core/clock.py`：測試用 `clock.set(...)`、`clock.advance(...)`；`tests/unit/test_clock.py` 會掃描 `app/` 確認沒有直接讀系統時間（包含 SQL 的 `now()`）。
- 目前 `tests/implemented.txt` 是空的，所以 spec 的 scenario 全部顯示為「尚未實作」；`42 passed, 489 skipped` 是 T-001 完成時的正常結果（489 = spec 的 245 個 scenario 依 Examples 展開；`tests/unit/test_spec_collection.py` 會確認一個都沒少）。

### 目錄

見 `AGENTS.md` 的「目錄約定」。`app/main.py` 會自動註冊 `app/modules/<模組>/<feature>/router.py` 內名為 `router` 的 `APIRouter`，新增 feature 不需要改 `app/main.py`。

## 目前狀態

M0 進行中。
