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
| D-036 | 附錄 A 的預設值（單價、保留金費率、年度上限）由哪張 ticket 載入？ | 延到 T-401：建立設定表時一併擴充 fixture loader。T-001 只載入時鐘與帳戶。 | 不提前替 T-401 決定設定表的資料模型 | 2026-11-15 | issue #3 選項 1A；T-001 完成條件 4、T-401 完成條件 5 與 `allowed_paths` 已改 |
| D-037 | `yc_v3.accounts` 的約束是否沿用？ | 沿用 `bigint identity` 主鍵、`unique(name)`、role 與 zone 的 check。密碼、session 等欄位由 T-101、T-303 新增。 | 對應附錄 B「顯示名稱全系統唯一」與 IAM-R13 | 2026-11-15 | issue #3 選項 2A |
| D-038 | `.gitignore` 由誰新增？ | T-001 合併後由 Chief 在 `milestone/M0` 新增。 | 不是產品程式，不影響行為 | 2026-11-15 | issue #3 選項 3A |
| D-039 | `commit-author` 如何處理 GitHub 產生的 merge commit？ | 以 GitHub API 讀 PR 每個 commit 的 `author.login`，必須是 `bullet-bots`；不再比對 email。Chief 繼續用 GitHub 合併 ticket PR。 | GitHub 合併產生的 commit 用帳號的主要 email（例如 `84852d9`），歷史不能改寫 | 2026-11-15 | issue #6 選項 1A |
| D-040 | 如何判定 ticket「涉及畫面」？ | ticket front matter 加 `screens: true/false`，由 Chief 在規劃 milestone 時填寫；沒有這個欄位時 `evidence` 判為失敗。M0 的三張都是 `false`；其他 ticket 在各自 milestone 的 plan-approval 補上。 | 路徑字串判斷會讓 feature ticket 永遠不必附截圖 | 2026-11-15 | issue #6 選項 2A |
| D-041 | PR「證據」一節的最低標準？ | 至少一個 code block（CLI 輸出）或一個指向 `docs/evidence/<ticket>/` 的連結。內容的品質仍由 Verifier 判斷。 | 擋下只寫一個字的敷衍寫法 | 2026-11-15 | issue #6 選項 3A |
| D-042 | `migration-scope` 要不要加沙盒實際執行的第二層？ | 要。靜態分析加上在拋棄式 PostgreSQL 17 上用沒有 `public` 權限的角色實際執行 migration，比對前後差異。 | 靜態分析追不完所有寫法；這是防止 migration 碰到共用 Supabase 其他 schema 最強的自動防線 | 2026-11-15 | issue #6 選項 4A；擋不住函式日後被呼叫時才發生的事 |
| D-043 | T-002 第 2 輪 FAIL 後怎麼做？ | 依 D-044～D-049 縮小並明確定義範圍，開修正第 2 輪（新 session，`claude-opus-5-5`）。issue #6 的修改算在修正第 1 輪。再 FAIL 就停止交給 Kuei。 | Kuei 同意 Chief 的輪數算法 | 2026-11-15 | issue #7 選項 1A |
| D-044 | CI 檢查的防護目標？ | 防 agent 的疏忽與常見的偷懶寫法，不防刻意的攻擊；刻意的繞過由 Verifier 審查 diff、Kuei 審查 milestone 擋下。用允許清單、禁止整類寫法、比對結果的方式設計，不列舉語法。 | 列舉語法的方式永遠補不完 | 2026-11-15 | issue #7 選項 2A |
| D-045 | `migration-scope` 怎麼處理函式等程序碼？ | 禁止定義函式、程序、trigger、`DO` 區塊、`lo_*`；ticket front matter 為 `allow_functions: true` 時例外，由 Kuei 親自閱讀 SQL。沙盒層保留。 | 函式本體只能靠靜態分析，而靜態分析不可靠 | 2026-11-15 | issue #7 選項 3A |
| D-046 | `no-weakened-tests` 怎麼判斷？ | 比對結果：目標分支上通過的每個測試 ID，在 PR 上都必須被收集而且通過；沒有報告就失敗；conftest 的 hook 採允許清單。語法掃描保留。 | 讓測試消失的寫法列舉不完，看結果才可靠 | 2026-11-15 | issue #7 選項 4A |
| D-047 | `strings` 的範圍？ | 只檢查傳給結果類別的錯誤訊息。稽核說明由附錄 C 管，逐字格式在 AUD-F02（M6）定義。 | 避免誤擋 T-003 的稽核說明 | 2026-11-15 | issue #7 選項 5A |
| D-048 | 怎麼修改 `tests/support/**`？ | 只有 ticket 的 `allowed_paths` 明確列出該檔案時才能修改，由 Verifier 審查。 | 比照 D-031 | 2026-11-15 | issue #7 選項 6A |
| D-049 | 不是 `ticket/*` 分支的 PR？ | 目標是 `milestone/*` 的 PR，來源分支必須是 `ticket/T-xxx` 且有對應的 ticket 檔，否則判為失敗。 | fail-closed | 2026-11-15 | issue #7 選項 7A |
| D-050 | Migration 什麼時候套用到 Supabase？agent 能不能用 Supabase？ | 延到部署時。agent 與 CI 仍只用拋棄式資料庫，不碰任何 Supabase 專案（不可違反第 7 條不變）。部署前新增「部署準備」ticket：建立 v3 專用的 staging Supabase 專案，由 CI 以權限受限的帳號套用 migration 並跑冒煙測試，處理 pooler 的 prepared statement、SSL、`schema_migrations` 追蹤、角色權限等差異；通過後 Kuei 套用到正式環境。 | 改規則的成本（機密管理、放寬本機防線）現在就要付，好處要到有東西可部署時才出現；共用專案有舊系統的正式資料，不能當拋棄式使用 | 2026-11-16 | Kuei 在 Chief session 選 A；取代 `docs/workflow.md` 原本「每個 milestone 合併後套用」的做法 |
| D-051 | 新增 `tests/support/` 的檔案，算不算 D-048 說的「修改」？ | 不算。只有修改目標分支上已經存在的 `tests/support/` 檔案，才需要 ticket 的 `allowed_paths` 明確列出；新增的檔案由 Verifier 審查內容。 | 新增 helper 不會讓既有的測試變弱，弱化的風險在修改既有檔案；也不必由 Chief 事先預測檔名 | 2026-11-16 | issue #8 選項 1A；`docs/ci-checks.md` 的 `no-weakened-tests` 同步寫明 |
| D-052 | 測試可以改名嗎？ | 不可以。結果比對看測試 ID，改名會被判為原測試消失而失敗，CI 不提供例外。真的需要改名時，由 Chief 在 ticket 寫明舊名對新名的對應，並記錄在本檔。 | 改名很少見，而且正是讓測試悄悄消失的常見方式；PR 說明不能成為繞過的管道 | 2026-11-16 | issue #8 選項 2A；`docs/ci-checks.md` 的 `no-weakened-tests` 同步寫明 |
| D-053 | 沒有有效 anti-forgery token 的請求被拒絕為 `FORBIDDEN` 時，要不要寫 `ACCESS_DENIED`？ | 要。與 `spec/README.md` 的結果類別表、AUD-R03 一致：所有 `FORBIDDEN` 都寫 `ACCESS_DENIED`，沒有例外。 | 規則保持一致，T-003 的自動寫入不必改；偽造請求也留下紀錄 | 2026-11-16 | issue #9 選項 A；`spec/features/IAM-F03-session-and-sign-out.feature` 該 scenario 改為斷言 `ACCESS_DENIED` 與 `nothing else is written`；T-103 完成條件同步更新 |
| D-054 | Branch protection 的必要檢查放在哪些分支？ | 只在 `main` 要求 `docs/ci-checks.md` 的 10 個必要檢查；`milestone/*` 不要求。Ticket PR 合併進 `milestone/*` 的條件不變（D-003：CI 全綠且 Verifier PASS，由 Chief 確認）。 | Kuei 指定 | 2026-11-16 | 方案 A；Kuei 在 M1 的 Chief session 交接事項中指定 |
| D-055 | M1 的 ticket 計畫？ | 照 issue #11 核准：IAM 依序 T-101 → T-103 → T-102；純函式 T-111～T-114 與 IAM 平行；同時進行上限 3 張；共用 session 程式在 `app/core/session.py`，共用登入步驟在 `tests/steps/common/session.py`。 | Kuei 核准 | 2026-11-16 | issue #11 |
| D-056 | 密碼雜湊用什麼？ | Python 標準庫 `hashlib.scrypt`，N=2^17、r=8、p=1（OWASP 最低建議），每個帳戶獨立隨機 salt，以 `hmac.compare_digest` 比對；雜湊字串帶演算法與參數前綴。 | 不新增依賴；前綴讓日後可漸進換演算法 | 2026-11-16 | issue #11 選項 1A；寫入 T-101 完成條件 11 |
| D-057 | 登入後落地頁的路徑？ | 登入頁 `/sign-in`；USER → `/reports`；ADMIN、OWNER → `/review`。M2、M3 的頁面掛在這兩個路徑。 | 規格沒有 URL；事先固定，之後的 ticket 才能沿用 | 2026-11-16 | issue #11 選項 2A；寫入 T-101 完成條件 12 |
| D-058 | IAM-R10 的「Saved data survives a timeout」需要 M2 的回報，怎麼辦？ | T-103 實作閒置逾時、寫好其他 3 個 scenario 的步驟，並以單元測試涵蓋閒置邊界；`IAM-R10` 由 T-201 補上回報步驟後加入 `tests/implemented.txt`。 | `done-when` 以規則為單位；不改規格也讓 M1 的 CI 驗證到逾時 | 2026-11-16 | issue #11 選項 3A；T-103、T-201 的完成條件已改 |
| D-059 | Issue 決定後由誰關閉？ | Chief。把決定記進 `docs/decisions.md` 並推送後，在 issue 留言寫明 D 編號與 commit，然後關閉。寫進 `ask-spec-question`、`plan-milestone` 與 `docs/workflow.md` 第 5 節。 | 原本流程沒有寫，M0 漏關了 #1、#8、#9 | 2026-11-16 | Kuei 在 M1 Chief session 選定；同時關閉 #1、#8、#9、#11 |
| D-060 | 帳戶不在所選群組的名單內時回什麼？ | `INVALID`「請選擇帳戶」（維持 T-101 的實作）；`group` 選填，介面一律帶上。名單公開，不會洩漏額外資訊，與 IAM-R03 不衝突。 | 不改程式；附錄 B 補說明 | 2026-11-16 | issue #15 選項 1A；`spec/appendix-b-fields.md` |
| D-061 | 登入群組的代號與顯示名稱？ | `admin`／`west`／`south`，顯示「管理員／西區／南區」。 | 維持 T-101 的實作 | 2026-11-16 | issue #15 選項 2A；`spec/appendix-b-fields.md` 新增「登入群組」一列 |
| D-062 | HTMX 怎麼供應？ | 把固定版本的 `htmx.min.js` 放進 repo 當靜態檔，記下版本與 sha256；由 M2 規劃時新增一張小 ticket 處理，排在 M2 第一張有畫面的 ticket 之前。 | 不依賴外部 CDN；本機與 CI 測得到 | 2026-11-16 | issue #15 選項 3A；M2 的 plan-approval 要列出這張 ticket |
| D-063 | 怎麼判斷「production」？ | 環境變數 `APP_ENV=production` 時 session cookie 加上 `Secure`。部署準備 ticket 與 README 要寫明 railway 上的設定。 | 一律 `Secure` 會讓 http 的測試與本機開發壞掉 | 2026-11-16 | issue #15 選項 4A；IAM-F03 加註解 |
| D-064 | 「已加保」怎麼判斷？ | 保費 > 0 即視為已加保。 | 符合 PAY-R01 既有範例；不改資料模型 | 2026-11-16 | issue #15 選項 5A；PAY-F01 加註解 |
| D-065 | `exempt` 的範圍？ | 只免除未投保扣除，不影響固定薪資與保險。 | 維持 T-112 的實作 | 2026-11-16 | issue #15 選項 6A；PAY-R01 新增一列範例 |
| D-066 | every-period 的帳戶，非 10 號發薪的那一期扣不扣保險？ | 不扣；保險只在 10 號發薪扣。 | 符合 PAY-R01 的規則標題 | 2026-11-16 | issue #15 選項 7A；PAY-R01 新增一列範例 |
| D-067 | 自訂工項的金額算不算未投保扣除的基數？ | 算。自訂工項也是工項；PAY-R02 的 `only` 排除的是固定薪資。 | 名稱就是「自訂工項」；維持 T-112 的實作 | 2026-11-16 | issue #15 選項 8A；PAY-R02 新增一個 scenario；T-402 改為 25 個 scenario |
| D-068 | 實發為負數時？ | 照實列出負數，由管理員人工處理；不結轉。 | 不新增結轉的規則與資料 | 2026-11-16 | issue #15 選項 9A；PAY-R01 新增一列範例 |
| D-069 | T-102 的登入失敗必須寫入計數，與 IAM-F01 `nobody is signed in` 的「整個資料庫不變」衝突，怎麼辦？ | 只在 IAM-F01 的這個步驟內排除 `0004` 新增的失敗次數表與登入嘗試表；其他表仍須完全不變；IAM-F02 明確斷言這兩張表的寫入，`RATE_LIMITED` 與鎖定期間的拒絕不寫資料。不改共用步驟。 | 規格 IAM-R03 只寫 `nobody is signed in`；「整個資料庫不變」是 T-101 加嚴的；IAM-R05、R07 要求寫入 | 2026-11-16 | issue #20 選項 A（依 Chief 留言收窄）；T-102 完成條件 11、`allowed_paths` 加 `tests/steps/IAM-F01/iam_f01_steps.py` |
| D-070 | 個人費率能不能讓非保留金項目或大表帳戶產生保留金？ | 不能，一律為 0；個人費率只覆寫本來就有保留金的項目。 | 維持 T-113 的實作 | 2026-11-16 | issue #19 選項 1A；PAY-F02 加註解 |
| D-071 | 跨年區間的保留金在哪裡四捨五入？ | 每個年度各自 half-up 到整數再相加。 | 每個年度的累計都是整數，上限比較沒有小數 | 2026-11-16 | issue #19 選項 2A；PAY-F02 加註解 |
| D-072 | 保留金目標可以是負數，上限空間會超過 cap？ | 維持：上限比較的是加上 offset 後的淨額，負的目標代表多出可扣的空間。 | offset 代表管理員調整後的實際保留 | 2026-11-16 | issue #19 選項 3A；PAY-F02 加註解 |
| D-073 | 保留金目標的範圍？ | 整數 −999999～999999；超出為 `INVALID`，沿用「保留金調整須為整數（可為負）」。 | 避免 T-402 定欄位型別後溢位 | 2026-11-16 | issue #19 選項 4A；附錄 B 與 PAY-R14 新增一列範例 |
| D-074 | 一列同時有多個疑點時，likely fault 怎麼填？ | 依序只報第一個：A 不一致 → x < 0（`?`）→ B 不符。 | A 壞了 B 就無從比較 | 2026-11-16 | issue #19 選項 5A；MAT-R20 新增一列範例 |
| D-075 | 「信任 A」的結果不合不變式時？ | 比照 AD-6 拒絕為 `CONFLICT`「A 系統數值不一致，無法採用」，該列留在暫存區。 | 避免之後的核准在壞資料上運算 | 2026-11-16 | issue #19 選項 6A；MAT-R21 新增 scenario；附錄 B、`spec/definitions.md` 新增字串；T-504 改 `app/domain/inventory_import.py` |
| D-076 | 庫存可以是負數嗎？ | 不可以。不變式加上實領量、累計使用量、庫存量都 ≥ 0，用在 AD-6 與 D-075。 | 負庫存沒有業務意義 | 2026-11-16 | issue #19 選項 7A；MAT-R21 新增 scenario；附錄 B 更新 |
| D-077 | T-101 的兩個補充測試（`test_sign_in_details.py`）也斷言登入失敗時整個資料庫不變，與 IAM-R05、R07 衝突？ | 只有這兩個測試改用排除 `0004` 兩張表的比對（範圍同 D-069）；共用的 `_rejected` 維持嚴格。`INVALID` 的請求（欄位驗證就被擋下）不算 IAM-R07 的登入嘗試，不寫資料。 | 與 D-069 同一原因；其他拒絕情況維持最嚴格的斷言 | 2026-11-16 | issue #21 選項 A（依 Chief 留言收窄）；T-102 完成條件 12、`allowed_paths` 加 `tests/steps/IAM-F01/test_sign_in_details.py` |
| D-078 | 什麼請求算 IAM-R10 的「使用」？ | 只有經過 `app/core/session.py` 的 `get_current_actor` 的請求才算使用，才會延長閒置計時。已登入者開登入頁只會被轉走，不延長 session。 | 維持 T-103 的實作；「使用」與「通過身分檢查」一致 | 2026-11-16 | issue #23 選項 1A；不改程式 |
| D-079 | 逾時的 session 要不要清理？ | 現在不清理，交給 M6 的排程處理。 | 逾時的 session 無法使用，只佔空間 | 2026-11-16 | issue #23 選項 2A；不改程式；M6 規劃時列入 |
| D-080 | anti-forgery token 怎麼送？ | 一律用 HTMX 的 `hx-headers` 送標頭 `X-CSRF-Token`；不支援沒有 JS 的純 HTML 表單。 | 檢查不必讀請求主體；與 D-062 放進 repo 的 HTMX 一起決定所有表單的做法 | 2026-11-16 | issue #23 選項 3A；不改程式；M2 的 HTMX ticket 依此提供共用版型 |
| D-081 | 被鎖定而拒絕的請求算不算 IAM-R07 的登入嘗試？ | 不算。 | 符合 D-069「鎖定期間的拒絕不寫資料」；這些請求不做 scrypt，也不洩漏密碼對錯 | 2026-11-16 | issue #23 選項 4A；不改程式 |
| D-082 | IAM-R04「15 分鐘內 5 次」從哪裡起算？ | 從最後一次失敗起算 15 分鐘。 | 與 IAM-R05「15 分鐘沒有再失敗就重置」的文字一致；維持 T-102 的實作 | 2026-11-16 | issue #23 選項 5A；不改程式 |
| D-083 | `@concurrency`「across workers and restarts」要測到什麼程度？ | 維持同一行程內的多個 app 實例，加上直接斷言資料庫的列數。 | 「計數只存在記憶體」的錯誤由其他 scenario 抓到；多行程的並行測試由 M6 的 T-604 負責 | 2026-11-16 | issue #23 選項 6A；不改程式 |
| D-084 | M2 的計畫？ | 核准：新增 T-200（HTMX 與共用版型）；順序 T-200 → T-201 → T-202 ‖ T-203，同時最多 2 張；四張 ticket 的 `screens` 依計畫填寫。模型：Chief claude-opus-5-5、Builder claude-sonnet-5-5、Verifier claude-opus-5-5、修正第二輪 Builder claude-opus-5-5。 | Kuei 核准 | 2026-11-16 | issue #25 |
| D-085 | RPT-R12 需要的份額表要到 M3 才建立？ | RPT-R12 移到 T-301。T-202 實作管理員編輯（CONFIRMED → PENDING，寫 `REPORT_UNCONFIRM` 與 `REPORT_UPDATE`）；T-301 建立份額表後補上刪除份額並讓 RPT-R12 轉綠，`allowed_paths` 加 `app/modules/reports/report_lifecycle/**`、`tests/steps/RPT-F02/**`。 | 不在 REV-R11 實作前決定份額的資料模型 | 2026-11-16 | issue #25 選項 1A；T-202 改為 6 個 scenario，T-301 改為 12 個 |
| D-086 | 自訂工項在 M2 怎麼保存？ | T-201 的 `0005` 在 `reports` 上加三個可為 null 的欄位：名稱（最多 100 字）、數量（0.1 只的整數 0～9999）、單價（≥ 0 的整數），check 約束要求同時為 null 或同時有值。 | REV-R20 一張回報最多一個自訂工項；T-203 的篩選與匯出需要 | 2026-11-16 | issue #25 選項 2A；T-302 在 M3 規劃時確認是否還需要 migration |
| D-087 | 匯出 .xlsx 用什麼？ | `openpyxl`，由 T-203 加進 `pyproject.toml`，固定版本範圍。 | 之後 M4 的匯出可以沿用 | 2026-11-16 | issue #25 選項 3A；T-203 `allowed_paths` 加 `pyproject.toml` |
| D-088 | HTMX 的版本？ | `htmx.org@2.0.11`（npm 的 `latest`）的 `dist/htmx.min.js`，原封不動。 | 4.x 是剛發布的大版本 | 2026-11-16 | issue #25 選項 4A；補充 D-062 |
| D-089 | T-202 與 T-203 都要改 `tests/implemented.txt`，可以平行嗎？ | 可以；`tests/implemented.txt` 是平行規則的例外。後合併的 ticket 在開 Verifier 前先 merge `milestone/M2`。兩張都不得在 `tests/steps/common/` 新增步驟，新增步驟前先 `grep` 同文字。 | 衝突只是各自加幾行規則 ID | 2026-11-16 | issue #25 選項 5A |
| D-090 | M2 頁面與端點的路徑？ | T-201 `GET/POST /reports`；T-202 `GET /reports/{id}/edit`、`POST /reports/{id}`、`POST /reports/{id}/delete`（USER 與管理員共用，伺服器依角色判斷）；T-203 `GET /reports/history`、`/reports/history/export`、`/review/history/ordinary`、`/review/history/big-meter` 與各自的 `/export`。 | 依 D-057；平行的 ticket 事先知道彼此的路徑 | 2026-11-16 | issue #25 選項 6A；已寫進各 ticket |
| D-091 | 怎麼避免 Builder 自己加嚴的斷言擋住後續 ticket（pitfall #29）？ | `.claude/skills/build-ticket/SKILL.md` 的「PR 說明要有」加一條：比規格更嚴格的斷言要逐條列出。 | 每個 milestone 不必再靠 Chief 記得加 | 2026-11-16 | issue #25 選項 7A；Kuei 核准修改 `.claude/**` |
| D-092 | `docs/pitfalls.md` 滿 30 條，刪哪些？ | 刪 #5（`done-when` 已要求規則的 scenario 都 passed）、#7（`commit-author` 依 `author.login`，D-039）、#11（`evidence` 直接報出缺 `screens`）。其他條目不重新編號，避免既有的引用失效。 | 已被 CI 檢查取代 | 2026-11-16 | issue #25 選項 8A |
| D-093 | 共用步驟 `the outcome is <OUTCOME>` 對 `LOCKED` 以外一律斷言 message 為 null，與 RPT-R02、R03 等附錄 B 有字串的拒絕衝突？ | 所有拒絕類別改為：message 必須是附錄 B「錯誤訊息」欄逐字存在的字串，或為 null；`LOCKED` 維持只接受它自己的那一句；資料沒有任何變動的斷言照舊。加單元測試證明附錄 B 沒有的字串會失敗。由 T-201 修改 `tests/steps/common/outcome.py`。 | 之後的 CFG、IAM-F04、MAT、LED 也會用這個步驟判定 `CONFLICT`、`INVALID`；逐字對到正確的句子由各 feature 的 `… with message "…"` scenario 負責 | 2026-11-16 | issue #27 選項 A′；T-201 `allowed_paths` 加 `tests/steps/common/outcome.py`、完成條件 8 |
| D-094 | T-201 的步驟 `the audit description contains "{text}"` 只看 `REPORT_CREATE`，RPT-R11 會失敗？ | 由 T-202 把這個步驟搬到 `tests/steps/common/audit_description.py`，從 `tests/steps/RPT-F01/rpt_f01_steps.py` 移除。新定義：這個動作恰新增 1 列稽核，而且那一列的說明包含指定文字，不限類型。拿掉 T-201 加嚴的「全庫恰 1 列 `REPORT_CREATE`」。 | 對 RPT-R07 檢查的是同一件事；RPT-R11 與 M3 的 IAM-F06 才用得了同一句 | 2026-11-16 | issue #30 選項 A；T-202 `allowed_paths` 與完成條件 8 |
| D-095 | 共用步驟 `the outcome is FORBIDDEN` 要求資料庫完全不變，但規格規定 FORBIDDEN 要寫 `ACCESS_DENIED`？ | 由 T-202 修改 `tests/steps/common/outcome.py`：`FORBIDDEN` 的資料斷言改為「恰好新增 1 列 `ACCESS_DENIED`、行為者是被拒絕的人，其他資料表完全不變」；其他類別維持「完全沒有變動」。加反例單元測試。 | 把 `spec/README.md` 結果類別表與 AUD-R03 寫明的行為變成斷言；AUD-R02（M5）等一併適用 | 2026-11-16 | issue #31 選項 A；T-202 `allowed_paths` 與完成條件 8 |
| D-096 | 全部為 0 的回報算不算數？ | 不算。新增 RPT-R08（送出）與 RPT-R14（編輯）：至少一個工項數量 > 0，否則 `INVALID`「請至少填寫一個工項數量」。自訂工項有數量也算；編輯成全部為 0 也拒絕。RPT-R03 的邊界表加填一個有數量的工項，只檢查 `direct_13` 的邊界。 | 空回報會進審核並佔每日額度 | 2026-11-16 | issue #29 選項 1B（B1 算、B2 拒絕）；字串由 Kuei 在 Chief session 確認；附錄 B 新增一列；T-204 |
| D-097 | 不符資格或重複的共同作業者？ | 拒絕：`INVALID`「共同作業者最多 6 人，且須為同一區域、同一類型的啟用員工」，資料不變。改寫 RPT-R05 的 scenario。 | 不擅自修正輸入；人數影響分配與薪資 | 2026-11-16 | issue #29 選項 2B；附錄 B 更新；T-204 |
| D-098 | 不在附錄 B 的 UI 用語（T-201、T-203 自訂的標題、提示、備用錯誤字串、`EXPORT` 稽核說明格式）？ | 維持 Builder 的寫法。 | Kuei 沒有要求指定文字 | 2026-11-16 | issue #29 第 3、9 項 |
| D-099 | 歷史篩選無效時的畫面？ | 清空清單並停用匯出連結。畫面行為，不寫成 scenario，寫在 RPT-F03 的註解與 T-205 的完成條件。 | 避免使用者以為匯出的是表單上的新條件 | 2026-11-16 | issue #29 選項 4B；T-205 |
| D-100 | 一般歷史的區域篩選依據？ | 依回報送出時記下的工項組（AD-4），新增 RPT-R24。大表歷史的回報工項組是 BIG_METER，不含區域，該頁的區域篩選維持依提交者目前的區域。 | 歷史不因帳戶後來的變動而改變；與兩個頁面的分法一致 | 2026-11-16 | issue #29 選項 5B；大表頁的範圍由 Chief 依 5B 的文字收窄，已在 issue 說明；T-205 |
| D-101 | USER 歷史可用哪些篩選？ | 維持：只接受日期與「有自訂工項」；`zone`、`account` 為 `INVALID`。USER 是某張回報的共同作業者時，那張回報出現在他的歷史中（RPT-R20，已實作）。 | Kuei 在 issue 回覆 6B 後，於 Chief session 更正為 6A 並補充共作者的說明 | 2026-11-16 | issue #29 第 6 項（更正為 6A）；不改程式 |
| D-102 | USER 匯出的工項欄位、帳戶篩選的範圍？ | 維持 T-203 的實作：USER 匯出 = 自己目前的工項組加上看得到的回報所屬的工項組；帳戶篩選包含已封存的 USER，ADMIN、OWNER 的名稱為 `INVALID`。 | 與規格例子一致 | 2026-11-16 | issue #29 選項 7A、8A；不改程式 |
| D-103 | 已實作的規則（RPT-R03、RPT-R05）改規格時，程式還沒改，CI 會變紅？ | Chief 在改規格的同一個 commit，把 RPT-R03、RPT-R05 從 `tests/implemented.txt` 暫時移除，並刪除兩個寫死舊行為的補充測試（`test_ineligible_and_duplicate_collaborators_do_not_count_toward_six`、`test_an_empty_report_with_no_quantities_is_accepted_and_stores_no_items`）。T-204 把兩條規則加回去，`done-when` 強制全部通過；在那之前這兩條規則沒有 Gherkin 把關。T-205 與 T-202 平行時，比照 D-089 只在 `tests/implemented.txt` 重疊。 | 避免 `milestone/M2` 變紅擋住其他 ticket；D-052 不允許 Builder 刪測試 | 2026-11-16 | Kuei 在 Chief session 選定（「暫時移出 implemented」）；RPT-R03 為同一原因一併處理 |
| D-104 | 同一個請求有多個 `INVALID` 原因時，回哪一句？ | 規格不規定順序。目前的實作順序為：日期 → 數量格式 → 至少一個工項 → 共同作業者。scenario 與補充測試每次只放一個錯誤原因；回哪一句只要是附錄 B 的其中一句（D-093）。 | 使用者一次只看到一個錯誤即可；不把實作順序變成規格 | 2026-11-17 | issue #35 選項 1A；不改程式 |
| D-105 | 超過 30 天的回報還能編輯嗎？ | 可以。日期不變就不檢查 30 天（AD-8 只禁止改日期）。 | RPT-R02 只限制送出時的日期 | 2026-11-17 | issue #35 選項 2A；不改程式 |
| D-106 | 編輯或刪除不存在的回報？ | 回 HTTP 404，不是結果類別。`spec/README.md` 註明「找不到資源」不在結果類別表內。 | 維持 T-202 的實作 | 2026-11-17 | issue #35 選項 3A；`spec/README.md` 結果類別表下加註；不改程式 |
| D-107 | 打開別人的編輯頁（GET）被拒絕時，寫不寫 `ACCESS_DENIED`？ | 寫。 | 每個 `FORBIDDEN` 都寫 `ACCESS_DENIED`（AUD-R03、D-095） | 2026-11-17 | issue #35 選項 4A；不改程式 |
| D-108 | 直接開啟帶無效篩選的網址時，畫面怎麼呈現？ | D-099 的範圍是「表單送出的篩選」。直接開啟帶無效篩選的網址回 422 JSON。 | 正常操作碰不到；網址列只推送成功的篩選 | 2026-11-17 | issue #35 選項 5A；RPT-F03 的 D-099 註解加上範圍；不改程式；補充 D-099 |
| D-109 | 編輯時，送出後才變得不合格（封存、改區、改類型）的組員？ | 一律拒絕（D-097 的字串），必須先把那個人移出組員才能存檔。 | 與 D-097「不擅自修正輸入」一致 | 2026-11-17 | issue #35 選項 6A；不改程式 |
| D-110 | M3 的計畫？ | 核准：T-301～T-306 加新增的 T-307；順序 階段 1 T-301 ‖ T-305 ‖ T-307 → 階段 2 T-303 ‖ T-302 → 階段 3 T-306 ‖ T-304，同時最多 3 張；migration `0006`（T-301）、`0007`（T-303）、`0008`（T-306），T-302 不新增 migration，之後的編號往前一號；6 張 M3 功能 ticket `screens: true`。模型：Chief claude-opus-5-5、Builder claude-sonnet-5-5、Verifier claude-opus-5-5、修正第二輪 Builder claude-opus-5-5。 | Kuei 在 issue 回覆選項，並在 Chief session 指示繼續 | 2026-11-17 | issue #38 |
| D-111 | REV-R02、R11、R23 的 scenario 以「計算薪資」判定，但薪資在 M4？ | T-301 在 `app/modules/review/crew_split_and_stored_shares/` 提供「某期間每人已確認的數量」的讀取函式（只讀份額表），T-302 加上自訂工項金額（份額 × 自訂單價）；三條規則的「計算薪資」步驟呼叫它。T-402 的數量只能經由這個函式取得，並把這些步驟改接真正的薪資計算。 | 「份額是已確認數量的唯一來源」從 M3 起就有 Gherkin 把關 | 2026-11-17 | issue #38 選項 1B；T-301、T-302、T-402 完成條件；T-402 `allowed_paths` 加 `tests/steps/REV-F01/**`、`REV-F02/**`、`REV-F03/**` |
| D-112 | 自訂工項的附加、移除與 D-096？ | 比照 RPT-R14：存檔後沒有任何數量 > 0 就拒絕，`INVALID`「請至少填寫一個工項數量」，資料不變。員工的送出路徑不會帶自訂工項（REV-R20 只有管理員能附加），所以 M2 交接第 7 項改為在 T-302 的路徑確認。 | 不留下全部為 0 的回報（D-096 的理由） | 2026-11-17 | issue #38 選項 2A；T-302 完成條件 |
| D-113 | 銀行帳號由誰保存、怎麼加密？ | IAM-R14 從 T-303 移到 T-306。T-306 的 migration 新增銀行帳號（只存密文）與發薪方式；加密用 `cryptography` 的 AES-256-GCM，金鑰從環境變數 `BANK_NUMBER_KEY`（base64 的 32 bytes）讀取，沒有金鑰時依 IAM-R43。T-306 `allowed_paths` 加 `pyproject.toml`。T-303 不碰這兩個欄位。 | 加密與儲存在同一張 ticket，由 IAM-R43 把關 | 2026-11-17 | issue #38 選項 3A；T-303 改 13 個 scenario、T-306 改名並改 9 個；部署檢查表加 `BANK_NUMBER_KEY` |
| D-114 | IAM-R42 的 retention、payroll figures 到 M4 才存在？ | IAM-R42 移到 T-406。T-303、T-306 對自己負責的欄位（勞健保扣除額、未投保比例、銀行帳號）先做 `FORBIDDEN` 並寫 `ACCESS_DENIED`，用補充測試把關；T-402 對保留金與薪資同樣處理。 | 所有欄位都存在時才讓整條規則轉綠 | 2026-11-17 | issue #38 選項 4A；T-406 `allowed_paths` 加 `tests/steps/IAM-F07/**` |
| D-115 | IAM-R20、R22 的權限橫跨 T-303、T-305 的端點？ | T-304 依賴 T-303 與 T-305，`allowed_paths` 加 `app/modules/iam/account_lifecycle_and_pay_settings/**`、`app/modules/iam/password_change_and_reset/**`，由 T-304 加上「只有 OWNER 能動 ADMIN」與自我保護。 | 權限規則只寫一份，由 scenario 把關 | 2026-11-17 | issue #38 選項 5A |
| D-116 | 薪資設定欄位的初始值？ | 發薪方式預設 `CASH`；未投保、個人未投保比例空白（用區域比例）；勞健保扣除額 0、固定薪資 0、未投保免扣與每期發放固定薪資為關（附錄 B）。既有帳戶由 migration 設成同樣的值；建立帳戶時這些欄位不必送。 | `TRANSFER` 需要先有銀行帳號；IAM-R13 建立帳戶只給角色、區域、密碼 | 2026-11-17 | issue #38 選項 6A；T-303（發薪方式的欄位由 T-306 建立，D-113） |
| D-117 | M3 的共用步驟？ | S1：T-305 在 `tests/steps/common/outcome.py` 新增 `the outcome is <outcome> with message "<message>"`：`accepted` 時 message 必須為空、HTTP 200；其他類別逐字比對 message，資料斷言同 `the outcome is X`（`FORBIDDEN` 依 D-095，其他完全不變）；附反例單元測試。S2：T-304 把 `an audit row "X" is written`（不帶 actor）從 `tests/steps/RPT-F02/` 搬到 `tests/steps/common/audit_row.py`，語意為「這個動作新增了一列該類型的稽核，行為者是發出請求的 session 的主人」，RPT-F02 改為 import。 | 步驟是全域註冊的（pitfall #26）；原定義依賴 RPT-F02 的 fixture，IAM-R21 用不了 | 2026-11-17 | issue #38 選項 7A；比照 D-094 |
| D-118 | M3 頁面與端點的路徑？ | T-301 `GET /review`、`GET /review/queue/ordinary`、`/review/queue/big-meter`、`POST /review/reports/confirm`、`/review/reports/reject`（單筆與批次共用）、`POST /review/reports/{id}/unconfirm`（一律 `CONFLICT`）；T-302 `POST /review/reports/{id}/custom-item`；T-303 `GET/POST /accounts`、`GET/POST /accounts/{id}`、`POST /accounts/{id}/archive`、`/restore`、`/delete`、`/deactivate`（後兩者一律 `INVALID`）；T-304 `POST /accounts/{id}/role`；T-305 `GET/POST /account/password`、`POST /accounts/{id}/password`；T-306 `GET /accounts/{id}/bank-number`（遮罩，不寫稽核）、`POST /accounts/{id}/bank-number/reveal`（寫 `BANK_REVEAL`）、`POST /accounts/{id}/bank-number`、`POST /accounts/{id}/payment-method`。 | 平行的 ticket 事先知道彼此的路徑（同 D-090）；顯示完整帳號用 `POST`，不碰 T-200「渲染頁面不寫資料」的斷言 | 2026-11-17 | issue #38 選項 8A；已寫進各 ticket |
| D-119 | CI 的安裝步驟吞掉失敗？ | 改成 `sudo scripts/dev/install-postgres && { sudo systemctl stop postgresql \|\| true; }`，由 Chief 在任何 Builder 開工前直接提交到 `milestone/M3`。 | 安裝失敗要在那一步就失敗，不是到下一步才以「找不到 PostgreSQL 17」出現 | 2026-11-17 | issue #38 選項 9A；Kuei 核准修改 `.github/**` |
| D-120 | D-099 的畫面行為沒有 CI 把關？ | 新增 T-307「CI 的 Playwright 冒煙測試」（M3，無 migration，`screens: false`），在階段 1 與 T-301、T-305 平行。 | 之後改壞 `history.html` 時 CI 會變紅 | 2026-11-17 | issue #38 選項 10A；T-307 `allowed_paths` 含 `.github/workflows/**`（D-031） |
| D-121 | `docs/pitfalls.md` 滿 30 條，刪哪些？ | 刪 #1（`test_spec_collection.py` 已在 CI 比對收集數）、#12（`no-weakened-tests` 已會擋下，D-046、D-052）、#29（D-091 已寫進 `build-ticket` skill；`grep` 共用步驟的提醒在 #26）。不重新編號。 | 已被 CI 或 skill 取代 | 2026-11-17 | issue #38 選項 11A |
| D-122 | 管理員可以重設 OWNER 的密碼嗎？ | 不行。系統內沒有人能重設 OWNER 的密碼（Q-046：在系統外重設）；ADMIN 嘗試時為 `FORBIDDEN` 並寫 `ACCESS_DENIED`。IAM-R20 新增 scenario「Nobody resets the owner's password」。OWNER 自己用 IAM-R30 改密碼。 | ADMIN 不能接管 OWNER 帳戶 | 2026-11-17 | issue #40 選項 1A；T-304 改 7 個 scenario |
| D-123 | 改密碼或被重設後，該帳戶其他已登入的 session？ | 自己改密碼時保留目前這個 session、結束同一帳戶的其他 session；被管理員重設時結束該帳戶全部的 session。新增 IAM-R33（2 個 scenario）。 | 密碼外洩的人在對方改密碼後不能繼續使用 | 2026-11-17 | issue #40 選項 2A；T-308 |
| D-124 | 改密碼時輸入錯誤的目前密碼要計入鎖定嗎？ | 要，與登入共用同一個帳戶失敗計數與鎖定（IAM-R04、R05）；鎖定期間改密碼為 `LOCKED`。不計入來源位址的頻率限制（IAM-R07）。新增 IAM-R34（2 個 scenario）。 | 否則攻擊者可以在登入頁與改密碼頁各試 4 次 | 2026-11-17 | issue #40 選項 3B（共用）；T-308 |
| D-125 | issue #40 新增的 scenario 放哪張 ticket？ | D-122 併進 T-304；D-123、D-124 新增 T-308（排在 T-305 合併之後，與階段 2 平行）。T-305 照原定完成條件驗證與合併。T-304 依賴加上 T-308（兩張都改 `password_change_and_reset/`）。 | T-305 不必重做 | 2026-11-17 | issue #40 選項 4A；`spec/capabilities.md` 與 `spec/README.md` 的合計更正為 139 條規則、259 個 scenario（同時修正 MAT-F03、PAY-F01 先前未更新的列） |
| D-126 | 使用者不小心連續打錯密碼被鎖定，管理員確認是人為失誤時，能不能提前解除？ | 可以。新增 IAM-R08：ADMIN 可以解除 USER 的鎖定，ADMIN 的鎖定只有 OWNER 能解除，OWNER 被鎖定時只能等鎖定結束；解除時鎖定與失敗計數一起清除。稽核沿用 `ACCOUNT_UPDATE`，說明含「解除鎖定」（不新增稽核類型，因此不需要 migration）。來源位址的頻率限制（IAM-R07）不受影響。端點 `POST /accounts/{id}/unlock` 由 T-308 實作；帳戶管理頁的按鈕由 T-304 加上。 | 現場被擋住時不必等 15 分鐘；新增稽核類型要改 `0002` 的 check 約束與 `app/core/audit.py`，會讓 T-308 變成 migration ticket 而不能與 T-303 平行 | 2026-11-17 | Kuei 在 Chief session 提出並選 A（新增解除動作）與 A2（沿用 `ACCOUNT_UPDATE`）；T-308 改 7 個 scenario |
| D-127 | 「設定密碼時」要不要密碼確認欄？ | 要，照附錄 B 字面：改自己的密碼、建立帳戶、管理員重設都要確認欄，不一致時 `INVALID`「兩次輸入的密碼不一致」。建立帳戶由 T-303 加，管理員重設由 T-308 加。 | 附錄 B 第 13 列「設定密碼時」必填 | 2026-11-18 | issue #46 選項 1A |
| D-128 | 新密碼可以和目前密碼相同嗎？ | 可以。 | 規格沒有禁止 | 2026-11-18 | issue #46 選項 2A；不改程式 |
| D-129 | 只寫 `rejected as …`、沒有資料斷言步驟的拒絕 scenario？ | 不改規格。依 AGENTS.md 不可違反第 5 條，Builder 用補充測試斷言資料沒有任何變動（`FORBIDDEN` 只多 1 列 `ACCESS_DENIED`），Verifier 抽查；之後的 ticket 完成條件寫明。 | 行為由測試把關，不必改 9 個 feature 檔 | 2026-11-18 | issue #46 選項 3A；T-303、T-304、T-306、T-308 完成條件 |
| D-130 | USER 送出超過 16KB 的請求到管理員端點，回 `INVALID` 而不是 `FORBIDDEN`？ | 維持：大小檢查在權限檢查之前。 | 不解析過大的請求；規格沒有規定順序 | 2026-11-18 | issue #46 選項 4A；不改程式 |
| D-131 | D-111 的讀取函式可以 join `reports` 取日期與狀態嗎？ | 可以。D-111 的意思是「數量只能來自份額表」。 | 日期與狀態不是數量 | 2026-11-18 | issue #46 選項 5A；補充 D-111 |
| D-132 | 附錄 D 的分頁（歷史、確認佇列每頁 20 列）？ | 交給 M6 的 T-605 一起做。 | 不在任何 M2、M3 ticket 的完成條件 | 2026-11-18 | issue #46 選項 6A；T-605 完成條件 |
| D-133 | CI 的 Node 只固定主版號 `22`？ | 接受；下次有 ticket 改 CI 時固定到完整版本。 | 不影響正確性 | 2026-11-18 | issue #46 選項 7A |
| D-134 | 對 CONFIRMED 的回報存檔但自訂工項沒有變更，要不要退回 PENDING？ | 不退回、不寫資料：沒有變更就不是「改」（AD-10）。T-202 的管理員編輯維持一送出就退回。 | 不必為了沒有改變的存檔讓管理員重新確認 | 2026-11-18 | issue #46 選項 8A；REV-F03 的 AD-10 註解寫明 |
| D-135 | 自訂工項名稱只有空白（含全形空白）？ | 視為清空名稱，移除自訂工項（REV-R21）。 | 維持 T-302 | 2026-11-18 | issue #46 選項 9A；不改程式 |
| D-136 | 自訂工項金額的捨入？ | 讀取函式回傳精確分數（`Fraction`），依 AD-2 在毛額層級四捨五入。 | 每人每張回報先捨入會和 AD-2 不同 | 2026-11-18 | issue #46 選項 10A；T-402 完成條件 |
| D-137 | 欄位缺少時回哪一句？ | 回該欄位在附錄 B 的錯誤字串。 | 與 T-201、T-305 一致 | 2026-11-18 | issue #46 選項 11A；不改程式 |
| D-138 | CI 的 `no-weakened-tests` 逾時？ | `no-weakened-tests` 的 `timeout-minutes` 改為 45，`tests` 改為 30，由 Chief 直接提交到 `milestone/M3`。 | 兩輪全部測試各約 10～11 分鐘，T-303 已跑到 19 分 55 秒 | 2026-11-18 | issue #46 選項 12A；Kuei 核准修改 `.github/**` |
| D-139 | 顯示名稱前後的空白？ | 建立與修改時先去掉前後空白（含全形空白）再檢查長度與重複；只有空白時為「請輸入顯示名稱」。 | `Wen ` 與 `Wen` 在名稱清單上看起來一樣 | 2026-11-18 | issue #46 選項 13A；T-303 完成條件 |
| D-140 | D-124 讓 IAM-R30 的兩列「錯誤的目前密碼」無法通過「資料不變」的共用步驟？ | 改規格：把那兩列移到 IAM-R34 的新 Scenario Outline「A wrong current password is rejected and counted」，斷言「唯一的變動是多一次失敗」，步驟由 T-308 在 `tests/steps/IAM-F06/` 定義；共用步驟不改。IAM-R30 仍為 3 個 scenario，IAM-R34 改為 3 個，規格合計 263 個 scenario。 | 例外寫在規格裡，不藏在共用步驟；記錄 D-124 時漏了這個衝突（D-103 的教訓） | 2026-11-18 | issue #47 選項 B′；T-308 改 8 個 scenario |
| D-141 | 登入比對舊密碼通過後、建立 session 前，密碼被改掉，舊密碼仍拿到 session？ | 由 T-308 修正：`allowed_paths` 加 `app/modules/iam/sign_in/**`；建立 session 前在帳戶鎖內重新確認密碼雜湊沒有改變，改變了就與密碼錯誤相同處理；加並行補充測試。 | 不讓 M3 帶著已知的權限漏洞合併進 `main`；D-123 要在並行時也成立 | 2026-11-18 | issue #49 選項 A；Cursor 資安審查在 PR #48 提出 |
| D-142 | IAM-R20「An ADMIN cannot create an ADMIN」的 `no account is created` 斷言全庫不變，與 FORBIDDEN 必寫 `ACCESS_DENIED` 矛盾？ | 改規格：最後一步改為 `nothing is written except an audit row "ACCESS_DENIED" with actor "Admin1"`，與同一條規則其他 scenario 一致；沒有建立帳戶由 T-304 的補充測試斷言。另外確認 T-304 的保守做法：對象是 OWNER 的角色切換為 `INVALID`、相同角色不寫資料、ADMIN 可降回 USER 並寫 `ACCOUNT_ROLE_CHANGE`；OWNER 不能直接建立 ADMIN（先建 USER 再切換）；帳戶管理頁對 OWNER 另列 ADMIN、ADMIN 只看到 USER；打開 ADMIN／OWNER 的帳戶頁（唯讀）不受 IAM-R20 限制。 | 規格本身不一致，規劃時沒有比對到 | 2026-11-19 | issue #51 選項 A 與 1～4；scenario 數不變 |
| D-143 | 附錄 D 要求封存帳戶前先確認，目前沒有確認步驟？ | 交給 M6 的 T-605 依附錄 D 檢查清單一起補（T-605 完成條件 6） | 不影響資料正確性，與其他附錄 D 項目一起檢查 | 2026-11-19 | issue #53 第 1 項 A |
| D-144 | D-139 的去空白只做在建立？ | 維持；之後若加改名功能沿用同一個檢查 | 目前沒有改名功能 | 2026-11-19 | issue #53 第 2 項 A |
| D-145 | USER 能不能看自己的薪資設定（勞健保、未投保比例）？ | 目前不能；由 M4 的 T-406（個人統計與薪資試算）決定要顯示什麼 | 顯示範圍與薪資試算一起設計 | 2026-11-19 | issue #53 第 3 項 A |
| D-146 | 可以切換已封存帳戶的角色嗎？ | 可以，仍只限 OWNER | 不影響登入（封存帳戶不能登入） | 2026-11-19 | issue #53 第 4 項 A |
| D-147 | 銀行帳號與發薪方式的設定端點受 IAM-R20 限制？ | 是，與其他帳戶設定一致 | — | 2026-11-19 | issue #53 第 5 項 A |
| D-148 | 還沒設定銀行帳號時的顯示文字？ | 「尚未設定」 | 規格沒寫，沿用 T-306 的實作 | 2026-11-19 | issue #53 第 6 項 A |
| D-149 | 沒有金鑰時按「顯示完整帳號」？ | 回 200「無法讀取」，不寫 `BANK_REVEAL` | 沒有顯示任何東西，不算 reveal | 2026-11-19 | issue #53 第 7 項 A |
| D-150 | 沒有金鑰而且帳號格式也錯？ | 回格式錯誤 `INVALID` | D-104：多個錯誤不規定順序 | 2026-11-19 | issue #53 第 8 項 A |
| D-151 | USER 能不能設定自己的銀行帳號與發薪方式？ | 不能，`FORBIDDEN`，只有管理員 | — | 2026-11-19 | issue #53 第 9 項 A |
| D-152 | 已是轉帳的帳戶能不能清除銀行帳號？ | 不提供清除；改回現金才可能不需要帳號 | 0008 的 check 約束要求轉帳一定有帳號 | 2026-11-19 | issue #53 第 10 項 A |
| D-153 | ADMIN 用「管理員重設」重設自己的密碼時，自己的 session 也結束？ | 是（D-123）；改自己的密碼應走「改自己的密碼」 | — | 2026-11-19 | issue #53 第 11 項 A |
| D-154 | 已封存的帳戶可以「解除鎖定」？ | 可以 | 解除後仍因封存不能登入，無害 | 2026-11-19 | issue #53 第 12 項 A |
| D-155 | 帳戶被鎖定時，已登入的 session 仍有效？ | 是，鎖定只限制登入 | — | 2026-11-19 | issue #53 第 13 項 A |

## 待決定

| 項目 | 狀態 |
| --- | --- |
| 容量測試的數字（`spec/appendix-d-non-scenario.md`） | 待 Kuei 提供 |
| 正式的預設材料清單（Q-029） | 待 Kuei 提供 |
| 板信商業銀行薪轉單的樣本檔 | 待 Kuei 提供 |
