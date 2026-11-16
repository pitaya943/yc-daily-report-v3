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

## 待決定

| 項目 | 狀態 |
| --- | --- |
| 容量測試的數字（`spec/appendix-d-non-scenario.md`） | 待 Kuei 提供 |
| 正式的預設材料清單（Q-029） | 待 Kuei 提供 |
| 板信商業銀行薪轉單的樣本檔 | 待 Kuei 提供 |
