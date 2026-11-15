# 決定

只增不改。改變先前的決定時新增一列，並在「備註」註明取代哪一列。

| # | 問題 | 決定 | 理由 | 日期 | 備註 |
| --- | --- | --- | --- | --- | --- |
| D-001 | 規格以哪一份為準？ | `spec/`（Claude 撰寫的版本）。舊系統與 v2 的 spec 只是參考。 | Kuei 指定 | 2026-11-15 | |
| D-002 | 誰審查什麼？ | Ticket 由 agent 自動驗證；Kuei 只審查 milestone。 | Kuei 指定 | 2026-11-15 | |
| D-003 | Ticket PR 如何合併？ | CI 全綠且 Verifier 判定 PASS 時自動合併進 `milestone/Mx`；`main` 只有 Kuei 合併。 | Kuei 同意 | 2026-11-15 | |
| D-004 | 中途找 Kuei 的情況？ | 四種：規格不清楚、未授權的資料模型或介面變更、修正兩輪仍 FAIL、動到權限／金額／加密而沒有 scenario。 | Kuei 同意 | 2026-11-15 | |
| D-005 | 找 Kuei 的管道？ | GitHub issue。 | Kuei 指定 | 2026-11-15 | |
| D-006 | 用哪些模型？ | 全部用 Claude 系列，依角色分級。不沿用 v2 的「Never Opus」與「不同模型家族」。確切的模型由 Kuei 啟動 Chief 時指定。 | Kuei 指定 | 2026-11-15 | |
| D-007 | 修正第二輪的 Builder？ | 改用較強的模型；Verifier 維持全新 session。 | 第一輪已失敗，換模型比重試更可能修好 | 2026-11-15 | |
| D-008 | 同時進行幾張 ticket？ | 由 Chief 依依賴關係規劃。 | Kuei 指定 | 2026-11-15 | |
| D-009 | 技術棧？ | FastAPI、Jinja、HTMX、pytest-bdd。 | 全專案一種語言，Kuei 最容易自己驗證 | 2026-11-15 | |
| D-010 | 資料庫？ | 共用的 Supabase 專案，新的專用 schema `yc_v3`。 | 與舊系統和 v2 隔離 | 2026-11-15 | schema 名稱是暫定 |
| D-011 | Agent 能否連到共用專案？ | 不能。開發、測試、CI 只用容器內的 PostgreSQL；Kuei 在 milestone 合併後手動套用 migration。 | 共用專案有舊系統的正式資料 | 2026-11-15 | |
| D-012 | Migration 的形式？ | 純 SQL 檔。 | Kuei 套用前能直接讀到要執行的 SQL | 2026-11-15 | |
| D-013 | 帳號與 session 存在哪裡？ | `yc_v3` 內自己的資料表，不使用 Supabase Auth。 | 與共用專案的使用者隔離 | 2026-11-15 | |
| D-014 | Milestone 計畫要不要先核准？ | 要。每個 milestone 開始前 Kuei 核准 ticket 計畫。 | 方向錯誤在寫程式前被擋下 | 2026-11-15 | |
| D-015 | Chief 如何運作？ | 每個 milestone 由 Kuei 開一個 session。 | 開始時間由 Kuei 控制 | 2026-11-15 | |
| D-016 | Ticket 卡住時？ | 不依賴它的 ticket 繼續；依賴它的暫停。 | milestone 不因一個問題停擺 | 2026-11-15 | |
| D-017 | Milestone 審查需要展示環境嗎？ | 不需要。報告說明實際流程，Kuei 自行驗證。 | Kuei 指定 | 2026-11-15 | |
| D-018 | Milestone 報告？ | 每個 milestone 一份 HTML：為何這樣設計、達成哪些 feature、如何審查與驗證。 | Kuei 指定 | 2026-11-15 | |
| D-019 | PR 說明？ | 簡短寫出完成了什麼、如何驗證、milestone 報告的路徑。 | Kuei 指定 | 2026-11-15 | |
| D-020 | 語言？ | 報告、PR、issue、說明文字只用繁體中文；Gherkin、程式碼、commit 訊息用英文。 | Kuei 指定 | 2026-11-15 | |
| D-021 | 不確定的事？ | 不自行決定；給選項並標出建議。 | Kuei 指定 | 2026-11-15 | |
| D-022 | 驗證要附什麼？ | 任何有驗證的任務都附證據：畫面截圖、CLI 輸出等。 | Kuei 指定 | 2026-11-15 | |
| D-023 | PR 的驗證內容要註明模型嗎？ | 要。在 PR 留言寫出完成該任務的模型名稱與版本。 | Kuei 指定 | 2026-11-15 | |
| D-024 | AD-1 到 AD-13？ | 全部同意 `spec/definitions.md` 的定義。 | Kuei 同意 | 2026-11-15 | |
| D-025 | Q-052 到 Q-062 的暫定答案？ | 全部確認。 | Kuei 確認 | 2026-11-15 | |
| D-026 | Agent 用什麼身分操作 GitHub？ | 機器帳號 `bullet-bots`，只有寫入權限。做法是把 Claude 帳號的 GitHub 連結換成這個帳號。 | 讓 GitHub 能區分 Kuei 與 agent：分支規則才擋得住 agent，agent 開的 issue 才會通知 Kuei | 2026-11-15 | |
| D-027 | Commit 的作者？ | 也用 `bullet-bots`。 | Kuei 指定 | 2026-11-15 | |
| D-028 | 誰能更新 `main`？ | 只有 repo 管理員（Kuei），以規則集強制。 | `bullet-bots` 不是管理員，無法合併進 `main` | 2026-11-15 | |
| D-029 | M0 的 ticket 計畫？ | 照 issue #1 核准：T-001 先做，T-002 與 T-003 同時進行，合併時先 T-002、後 T-003。 | Kuei 核准 | 2026-11-15 | issue #1 |
| D-030 | T-001 要寫 `AGENTS.md` 的「指令」一節，但 Builder 不能改 `AGENTS.md`，怎麼辦？ | Builder 寫在 `README.md`；T-001 合併後由 Chief 搬進 `AGENTS.md`。 | 維持「Builder 不改規則檔」 | 2026-11-15 | issue #1 選項 1A |
| D-031 | T-002 要寫 `.github/workflows/**`，怎麼處理？ | ticket 的 `allowed_paths` 明確列出的 `.github/workflows/**` 可以修改；`spec-readonly` 的禁止清單減去 `allowed_paths` 明確列出的路徑。 | 讓 CI 能在 T-002 的 PR 上實際執行 | 2026-11-15 | issue #1 選項 2A；`AGENTS.md` 第 2 條同步修改 |
| D-032 | T-001 合併前沒有 CI，「CI 全綠」怎麼判定？ | 改由 Verifier 在乾淨的 checkout 上照 `README.md` 的指令重跑完整測試並附 CLI 輸出。T-003 照原條件，等 T-002 合併後在真的 CI 上全綠。 | CI 由 T-002 才建立 | 2026-11-15 | issue #1 選項 3A |
| D-033 | 本地與 CI 用哪一版 PostgreSQL？ | 17，與共用 Supabase 專案（17.6.1.127）同一主版本。容器沒有 Docker daemon，從 `apt.postgresql.org` 安裝；CI 用 `postgres:17` service。 | Kuei 套用 migration 時不會因版本不同而出現差異 | 2026-11-15 | issue #1 選項 5A；環境 `yc-daily-report-v3` 已允許 `apt.postgresql.org`、`www.postgresql.org` |
| D-034 | T-003 可以改哪些檔案？ | `allowed_paths` 加上 `migrations/0002_*.sql`（原本漏列）與 `app/main.py`（只註冊 exception handler 與稽核 middleware）。 | migration ticket 必須能新增 migration；HTTP 對應需要在 app 註冊 | 2026-11-15 | issue #1 選項 4A |
| D-035 | Chief 與 Builder 可以推送哪些分支？ | Chief 建立並推送 `milestone/M0`；Builder 推送 `ticket/T-001`、`ticket/T-002`、`ticket/T-003`。 | 符合 `docs/workflow.md` 的分支模型 | 2026-11-15 | issue #1 選項 6A |

## 待決定

| 項目 | 狀態 |
| --- | --- |
| 容量測試的數字（`spec/appendix-d-non-scenario.md`） | 待 Kuei 提供 |
| 正式的預設材料清單（Q-029） | 待 Kuei 提供 |
| 板信商業銀行薪轉單的樣本檔 | 待 Kuei 提供 |
