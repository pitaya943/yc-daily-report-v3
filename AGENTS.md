# AGENTS.md — 永遠適用的規則

這個檔案每個 session 都會載入，所以只放規則與連結。做法在 skills，細節在 `docs/workflow.md`。

## 專案

- 員工日報系統：日報、審核、薪資、材料、流水帳、檔案庫。
- 技術：FastAPI、Jinja、HTMX、PostgreSQL（schema `yc_v3`）、pytest-bdd。
- 規格：`spec/`。規格是唯一的行為來源；規格不清楚時停下來問，不要猜。

## 角色

| 角色 | 做什麼 | 不做什麼 |
| --- | --- | --- |
| Kuei | 核准每個 milestone 的計畫、回答 issue、審查並合併 `milestone/Mx → main`、手動套用 migration 到共用資料庫 | — |
| Chief | 切 ticket、排順序、開子 session、更新 `docs/board.md`、合併 ticket PR 進 milestone 分支、寫 milestone 報告 | 不寫產品程式 |
| Builder | 一張 ticket 一個全新 session：先讓指定的 scenario 失敗，再實作到通過，開 PR | 不改規格、不改範圍外的檔案、不合併 |
| Verifier | 一個 PR 一個全新 session：從乾淨 checkout 重跑，依檢查表判定 PASS 或 FAIL | 不修產品程式 |

各角色使用的模型由 Kuei 在啟動 Chief session 時指定。Verifier 永遠是全新的 session，只看規格、diff 與測試結果。

## 不可違反

1. **只有 Kuei 合併 `main`。** Chief 只在 CI 全綠且 Verifier 判定 PASS 時，把 ticket PR 合併進 `milestone/Mx`。不 force-push，不改寫別人的分支歷史。
2. **Builder 不得修改** `spec/**`、`AGENTS.md`、`.claude/**`、`.github/**`、`docs/decisions.md`、`docs/board.md`，也不得修改 ticket 的 `allowed_paths` 以外的檔案。唯一的例外：ticket 的 `allowed_paths` 明確列出的 `.github/workflows/**` 可以修改（D-031）。
3. **不得為了通過而弱化測試**：不跳過、不標記預期失敗、不刪除 scenario、不放寬斷言。
4. **先寫會失敗的測試，再寫實作。**
5. **每個拒絕案例斷言三件事**：結果類別、完整錯誤字串、資料沒有任何變動。
6. **伺服器重新驗證每個欄位。** 缺少的值不以預設值補上。
7. **不連線到共用的 Supabase 專案。** 開發、測試、CI 只用容器內的 PostgreSQL。Migration 只碰 `yc_v3`。
8. **不輸出機密。** 程式與紀錄都不印出金鑰、密碼、完整銀行帳號。
9. **CI 是唯一的裁判。** 「我在本地跑過了」不算完成。
10. **有驗證就要有證據。** 任何聲稱「已驗證」「已通過」的地方都附上證據：CLI 的指令與輸出、有畫面的功能附截圖。沒有證據的說法視為沒有驗證。截圖存在 `docs/evidence/<ticket 編號>/`，並在 PR 中連結。
11. **PR 上的驗證留言要寫明模型。** Builder 的交付留言與 Verifier 的判定留言，都要寫出完成這項工作的模型名稱與版本。名稱從 session 的實際設定取得，不可憑印象填寫；取不到時寫「無法取得」並說明原因。

## GitHub 身分

- 所有 GitHub 操作（push、開 PR、開 issue、留言、合併進 `milestone/*`）都以機器帳號 `bullet-bots` 進行。Kuei 的帳號 `pitaya943` 只由 Kuei 本人使用。
- 每個 session 在第一次 commit 之前，先在 repo 內設定作者，並確認設定成功：

  ```bash
  git config user.name "bullet-bots"
  git config user.email "354516064+bullet-bots@users.noreply.github.com"
  ```

- 開始工作前確認目前的 GitHub 登入帳號是 `bullet-bots`。不是的話停止，告訴 Kuei，不要用其他身分繼續。
- `bullet-bots` 只有寫入權限，不能更新 `main`。不要嘗試繞過。

## 什麼時候停下來找 Kuei

遇到以下任一情況，停止這張 ticket，依 `ask-spec-question` skill 開一個標 `needs-kuei` 的 issue：

1. 規格不清楚或互相矛盾。
2. 需要改資料模型或公開介面，而 ticket 沒有授權。
3. 修正兩輪後 Verifier 仍判定 FAIL。
4. 要動到權限、金額計算、加密，而沒有 scenario 涵蓋。

**不確定的事不要自己決定。** Issue 裡給出兩到三個選項，說明各自的後果，並標出建議的那一個。不依賴這張 ticket 的其他 ticket 繼續進行。

## 記憶

Context window 用完即丟；要留下的東西一律寫進 repo。

| 檔案 | 內容 | 誰能寫 |
| --- | --- | --- |
| `AGENTS.md`、`spec/**` | 規則與規格 | Kuei 核准後由 Chief 修改 |
| `docs/decisions.md` | Kuei 的決定，只增不改 | Chief |
| `docs/board.md`、`docs/tickets/*.md` | 進度與任務 | Chief |
| PR 說明 | 這張 ticket 做了什麼、證據、未解問題 | Builder、Verifier |
| `docs/pitfalls.md` | 下一個 agent 該知道的坑 | Chief 在 milestone 結束時整理；Builder 只能在 PR 說明裡提議 |
| `docs/milestones/Mx.html` | 給 Kuei 的 milestone 報告 | Chief |

每個 session 只載入自己那張 ticket「要讀的檔案」列出的內容。不要載入整個 `spec/`。

## 語言

- 報告、PR、issue、規格的說明文字、`docs/**`：只用繁體中文，專業術語除外。
- Gherkin 步驟、程式碼識別字、commit 訊息：英文。
- 使用者可見字串：依 `spec/appendix-b-fields.md`，逐字相符。

## 目錄約定

```
app/core/                         時鐘、資料庫、結果類別、稽核、權限檢查
app/domain/                       純函式（不讀資料庫、不讀時鐘）
app/modules/<模組>/<feature>/      router.py、service.py、repo.py、templates/
migrations/NNNN_<名稱>.sql         純 SQL，只碰 yc_v3
tests/steps/<feature ID>/         pytest-bdd 的步驟
tests/unit/                       單元測試
tests/implemented.txt             已實作的規則 ID
spec/                             規格（對 Builder 唯讀）
docs/                             流程、決定、看板、ticket、milestone 報告
```

## 指令

在 repo 根目錄執行。完整說明見 `README.md`（D-030：由 T-001 寫入 README，Chief 搬到這裡）。

```bash
scripts/dev/install-postgres   # 安裝 PostgreSQL 17（PGDG apt，需要 root；D-033）
pip install -e '.[dev]'        # 安裝 Python 套件
scripts/dev/db-start           # 啟動本機資料庫：127.0.0.1:5433，資料庫 yc
scripts/dev/migrate            # 依編號套用 migrations/NNNN_*.sql 到 yc_v3
python3 -m pytest              # 全部測試；會清空本機 yc_v3 的資料
scripts/dev/run                # 啟動應用程式：http://127.0.0.1:8000，GET /health
```

- 其他：`scripts/dev/db-stop`、`scripts/dev/db-reset`。
- 本機防線是 fail-closed：`DATABASE_URL` 只接受本機位址；`PGSERVICE`、`PGSERVICEFILE`、`PGSYSCONFDIR` 或不認得的 `PG*` 環境變數只要有設就拒絕。訊息以 `refusing to connect:` 開頭時，先 `unset` 該變數。

## Skills

| Skill | 誰用 | 何時 |
| --- | --- | --- |
| `plan-milestone` | Chief | milestone 開始前 |
| `build-ticket` | Builder | 做一張 ticket |
| `verify-ticket` | Verifier | 驗證一個 PR |
| `ask-spec-question` | 任何角色 | 遇到「停下來找 Kuei」的情況 |
| `add-migration` | Builder | ticket 標示 `migration: true` |
| `milestone-report` | Chief | milestone 的 ticket 全部合併後 |
