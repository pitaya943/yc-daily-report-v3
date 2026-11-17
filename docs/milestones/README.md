# Milestone 計畫

**狀態：草稿。** 每個 milestone 開始前，Chief 依當時的 repo 狀態重新確認這份計畫中屬於該 milestone 的部分，開一個標 `plan-approval` 的 issue，Kuei 回覆同意後才開工。

## Milestone

| ID | 名稱 | 完成條件 | Ticket 數 | Scenario 數 |
| --- | --- | --- | --- | --- |
| M0 | 基礎建設 | 專案骨架、測試框架、CI 檢查與共用基礎可用；一個冒煙 scenario 從 HTTP 請求走到資料庫並通過。 | 3 | 0 |
| M1 | 身分與純計算 | 員工與管理員可以登入、被鎖定、逾時登出；分配、薪資、保留金、庫存比對四組純函式通過各自規則的全部例子。 | 7 | 19 |
| M2 | 日報 | 員工可以送出、編輯、刪除、查詢並匯出日報；每日上限與共同作業者規則由伺服器強制。 | 6 | 34 |
| M3 | 審核與帳戶管理 | 管理員可以確認或駁回回報並保存份額；帳戶生命週期、OWNER 管理管理員、密碼、銀行帳號遮罩可用。 | 7 | 52 |
| M4 | 薪資 | 管理員可以計算並保存薪資批次、匯出、處理封存帳戶與年度結算；員工可以試算。 | 7 | 71 |
| M5 | 材料與流水帳 | 材料申請、審核、庫存管理、匯入比對，以及流水帳、證據檔與作廢可用。 | 6 | 52 |
| M6 | 檔案庫、稽核與收尾 | 日月報排程、稽核紀錄、完整權限矩陣、並行測試與附錄 D 檢查清單全部通過。 | 5 | 23 |

每個 milestone 的共同完成條件：該 milestone 所有 ticket 的狀態為 `merged`；`milestone/Mx` 分支的 CI 全綠；`docs/milestones/Mx.html` 報告完成；`milestone/Mx → main` 的 PR 已開並指派給 Kuei。

## 順序的理由

依 `spec/capabilities.md` 的依賴圖排列：先有身分才能填日報，先有已確認的回報才能計薪。四組純函式（分配、薪資公式、保留金、庫存比對）沒有任何依賴，放在 M1 與登入平行進行，讓金額計算最早被驗證。材料與流水帳只依賴身分，排在 M5 是為了讓薪資這條主線先完成；如果 Kuei 想提前，M5 可以與 M3、M4 平行。

## Ticket

| Ticket | Milestone | 標題 | 依賴 | Feature | Scenario 數 | Migration |
| --- | --- | --- | --- | --- | --- | --- |
| [T-001](../tickets/T-001.md) | M0 | 專案骨架與測試框架 | — | — | 檢查清單 | 是 |
| [T-002](../tickets/T-002.md) | M0 | CI 檢查 | T-001 | — | 檢查清單 | 否 |
| [T-003](../tickets/T-003.md) | M0 | 共用基礎：結果類別、稽核寫入、權限檢查 | T-001 | — | 檢查清單 | 是 |
| [T-101](../tickets/T-101.md) | M1 | 登入 | T-003 | IAM-F01 | 4 | 是 |
| [T-102](../tickets/T-102.md) | M1 | 登入鎖定與頻率限制 | T-101 | IAM-F02 | 7 | 是 |
| [T-103](../tickets/T-103.md) | M1 | Session 與登出 | T-101 | IAM-F03 | 8 | 否 |
| [T-111](../tickets/T-111.md) | M1 | 純函式：小組分配 | T-001 | — | 檢查清單 | 否 |
| [T-112](../tickets/T-112.md) | M1 | 純函式：薪資公式 | T-001 | — | 檢查清單 | 否 |
| [T-113](../tickets/T-113.md) | M1 | 純函式：保留金 | T-001 | — | 檢查清單 | 否 |
| [T-114](../tickets/T-114.md) | M1 | 純函式：庫存比對 | T-001 | — | 檢查清單 | 否 |
| [T-200](../tickets/T-200.md) | M2 | 固定版本的 HTMX 與共用頁面版型 | T-103 | — | 檢查清單 | 否 |
| [T-201](../tickets/T-201.md) | M2 | 送出日報 | T-103, T-200 | RPT-F01 | 14 | 是 |
| [T-202](../tickets/T-202.md) | M2 | 回報生命週期 | T-201 | RPT-F02（RPT-R12 除外） | 6 | 否 |
| [T-203](../tickets/T-203.md) | M2 | 歷史與匯出 | T-201 | RPT-F03 | 8 | 否 |
| [T-204](../tickets/T-204.md) | M2 | 至少一個工項與共同作業者資格（規格更新） | T-202 | RPT-R03、R05、R08、R14 | 8 | 否 |
| [T-205](../tickets/T-205.md) | M2 | 歷史篩選調整（規格更新） | T-203 | RPT-R24 | 1 | 否 |
| [T-301](../tickets/T-301.md) | M3 | 確認或駁回回報，保存份額 | T-202, T-111 | REV-F01、REV-F02、RPT-R12 | 12 | 是 |
| [T-302](../tickets/T-302.md) | M3 | 自訂工項 | T-301 | REV-F03 | 7 | 否 |
| [T-303](../tickets/T-303.md) | M3 | 帳戶生命週期與薪資設定 | T-103 | IAM-F04（IAM-R14 除外） | 13 | 是 |
| [T-304](../tickets/T-304.md) | M3 | OWNER 管理管理員 | T-303, T-305 | IAM-F05 | 6 | 否 |
| [T-305](../tickets/T-305.md) | M3 | 密碼變更與重設 | T-103 | IAM-F06 | 5 | 否 |
| [T-306](../tickets/T-306.md) | M3 | 銀行帳號、發薪方式與遮罩 | T-303 | IAM-F07（IAM-R42 除外）、IAM-R14 | 9 | 是 |
| [T-307](../tickets/T-307.md) | M3 | CI 的 Playwright 冒煙測試 | T-205 | — | 檢查清單 | 否 |
| [T-401](../tickets/T-401.md) | M4 | 單價與費率設定 | T-003 | CFG-F01、CFG-F02 | 11 | 是 |
| [T-402](../tickets/T-402.md) | M4 | 薪資計算與薪資批次 | T-301, T-112, T-113, T-401 | PAY-F01、PAY-F02 | 24 | 是 |
| [T-403](../tickets/T-403.md) | M4 | 封存帳戶的薪資 | T-402, T-303 | PAY-F03 | 7 | 否 |
| [T-404](../tickets/T-404.md) | M4 | 年度結算 | T-402 | PAY-F04 | 4 | 是 |
| [T-405](../tickets/T-405.md) | M4 | 薪資批次的匯出與現金面額 | T-402, T-306 | PAY-F05 | 13 | 否 |
| [T-406](../tickets/T-406.md) | M4 | 個人統計與薪資試算 | T-402 | PAY-F06、IAM-R42 | 8 | 否 |
| [T-407](../tickets/T-407.md) | M4 | 跨帳戶統計總表 | T-301 | PAY-F07 | 4 | 否 |
| [T-501](../tickets/T-501.md) | M5 | 庫存管理 | T-103 | MAT-F04 | 13 | 是 |
| [T-502](../tickets/T-502.md) | M5 | 申請材料 | T-501 | MAT-F01 | 9 | 是 |
| [T-503](../tickets/T-503.md) | M5 | 審核材料申請 | T-502 | MAT-F02 | 7 | 否 |
| [T-504](../tickets/T-504.md) | M5 | 庫存匯入與暫存區 | T-501, T-114 | MAT-F03 | 5 | 是 |
| [T-511](../tickets/T-511.md) | M5 | 流水帳紀錄與餘額 | T-103 | LED-F01 | 10 | 是 |
| [T-512](../tickets/T-512.md) | M5 | 證據檔與作廢 | T-511 | LED-F02 | 8 | 是 |
| [T-601](../tickets/T-601.md) | M6 | 日月報檔案庫 | T-301, T-402 | ARC-F01 | 11 | 是 |
| [T-602](../tickets/T-602.md) | M6 | 稽核軌跡 | T-003 | AUD-F02 | 9 | 否 |
| [T-603](../tickets/T-603.md) | M6 | 完整權限矩陣 | T-512, T-407, T-306 | AUD-F01 | 3 | 否 |
| [T-604](../tickets/T-604.md) | M6 | 並行測試與容量測試 | T-603 | — | 檢查清單 | 否 |
| [T-605](../tickets/T-605.md) | M6 | 附錄 D 檢查清單 | T-603 | — | 檢查清單 | 否 |

137 條規則各自只屬於一張 ticket（M2 依 D-096、D-100 新增 RPT-R08、R14、R24；RPT-R03、R05 改由 T-204 重新驗收，D-103；M3 依 D-113 把 IAM-R14 移到 T-306、依 D-114 把 IAM-R42 移到 T-406）。純函式的 ticket（T-111 到 T-114）以單元測試驗收同一批例子；對應的 Gherkin scenario 在整合的 ticket（T-301、T-402、T-504）才轉綠。

## 平行規則

- 依賴都已 `merged` 的 ticket 可以同時進行。
- 同時進行的 ticket，`allowed_paths` 不得重疊。
- `migration: true` 的 ticket 一次只做一張，依 `migration_number` 的順序。
- 例外：`tests/implemented.txt` 可以重疊；後合併的 ticket 在開 Verifier 前先 merge milestone 分支（D-089）。
- 同時進行的 ticket 數量由 Chief 決定，並記錄在 `docs/board.md`。

## 部署準備 ticket 的檢查表

部署前的「部署準備」ticket（第 1 節，D-050）還沒開。開的時候，完成條件至少包含下列各項（M2 交接，M3 起累積）：

- `APP_ENV=production`（D-063）。
- uvicorn 加上 `--proxy-headers --forwarded-allow-ips`。
- 依序套用全部 migration 並跑各自的檢查：`0003`、`0004` 的檢查與回滾見 `docs/milestones/M1.html` 第 5 節；`0005` 見 `docs/milestones/M2.html` 第 5 節；`0006` 起見各 milestone 報告第 5 節。
- 部署環境能安裝 `openpyxl`（D-087）與 `cryptography`（D-113）。
- 設定 `BANK_NUMBER_KEY`（base64 的 32 bytes，D-113）並另外妥善保存；金鑰遺失時所有銀行帳號都無法讀取（IAM-R43）。
