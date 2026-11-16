# CI 檢查

由 T-002 實作。每一項都要有一個「會讓它失敗」的測試案例，證明檢查真的有效。

**防護目標（D-044）**：這些檢查防的是 agent 的疏忽與常見的偷懶寫法，不是刻意的攻擊。刻意的繞過由 Verifier 審查 diff、Kuei 審查 milestone 擋下。檢查以允許清單、禁止整類寫法、比對結果的方式設計，不靠列舉禁止的語法。

**來源分支（D-049）**：目標是 `milestone/*` 的 PR，來源分支必須是 `ticket/T-xxx`，而且目標分支上要有對應的 `docs/tickets/T-xxx.md`，否則下列每一項都判為失敗。

| 檢查 | 內容 | 失敗時 |
| --- | --- | --- |
| `tests` | 在乾淨的 PostgreSQL 17（D-033）上執行單元測試與 `tests/implemented.txt` 列出的所有規則的 scenario。 | 任何一個失敗 |
| `spec-readonly` | 目標是 `milestone/*` 的 PR 不得修改 `spec/**`、`AGENTS.md`、`.claude/**`、`.github/**`、`docs/decisions.md`、`docs/board.md`；例外是該 ticket 的 `allowed_paths` 明確列出的路徑（D-031）。 | 有任何一個被修改 |
| `path-scope` | 從分支名稱找到 `docs/tickets/T-xxx.md`，PR 修改的每個檔案都要符合它的 `allowed_paths`。 | 有範圍外的檔案 |
| `evidence` | PR 說明的「證據」一節至少有一個 code block（CLI 輸出）或一個指向 `docs/evidence/<ticket 編號>/` 的連結（D-041）；ticket front matter 為 `screens: true` 時，`docs/evidence/<ticket 編號>/` 至少有一張截圖。front matter 沒有 `screens` 欄位時判為失敗（D-040）。 | 缺少證據 |
| `migration-scope` | `migrations/*.sql` 只能操作 `yc_v3`；不得出現對其他 schema 的 `CREATE`、`ALTER`、`DROP`、`TRUNCATE`。只有 `migration: true` 的 ticket 能新增 migration，且檔名編號等於 `migration_number`。已合併的 migration 不得被修改。檢查分兩層（D-042）：靜態分析（有引號的識別字區分大小寫、處理 dollar quoting、語句採允許清單、無法確定時判為失敗），以及在拋棄式 PostgreSQL 17 上用沒有 `public` 權限的角色實際執行全部 migration，比對 `yc_v3` 以外有沒有變化。另外，migration 不得定義函式、程序、trigger，不得有 `DO` 區塊，不得呼叫 `lo_*` 等大型物件函式；只有 ticket front matter 為 `allow_functions: true` 時例外，該 ticket 由 Kuei 依 D-012 親自閱讀 SQL（D-045）。 | 任一條不符 |
| `no-weakened-tests` | 以結果判斷（D-046）：由 `scripts/ci/` 的 plugin 輸出每個測試的結果，與目標分支比對；目標分支上通過的每個測試 ID，在 PR 上都必須被收集而且通過；沒有產生結果報告就判為失敗。conftest 只能定義允許清單內的 hook。測試程式不得出現跳過或預期失敗的標記（語法掃描保留，用來給出易懂的訊息）。`tests/implemented.txt` 只能增加，不能減少。`tests/support/**` 只有在 ticket 的 `allowed_paths` 明確列出該檔案時才能修改（D-048）。 | 任一條不符 |
| `done-when` | Ticket 完成條件列出的規則 ID 都在 `tests/implemented.txt` 中，且對應的 scenario 都被收集並通過。 | 有規則缺漏或沒被執行 |
| `strings` | 傳給結果類別（`app/core` 的拒絕結果）的錯誤訊息，都逐字存在於 `spec/appendix-b-fields.md`。稽核說明不在這一項的範圍內，由附錄 C 管（D-047）。 | 有規格沒有的字串 |
| `commit-author` | PR 中每個 commit 的作者帳號（GitHub API 的 `author.login`）都是 `bullet-bots`；包含 GitHub 產生的 merge commit（D-039）。 | 有其他作者的 commit，或作者無法對應到帳號 |
| `lint` | 格式與靜態檢查。 | 有錯誤 |

Milestone PR（`milestone/Mx → main`）另外檢查：該 milestone 規劃的規則 ID 全部在 `tests/implemented.txt` 中。

## `tests/implemented.txt` 的作用

`spec/features/` 從第一天就有全部 245 個 scenario，但多數還沒實作。這個檔案列出已實作的規則 ID；測試只執行列在其中的規則，其餘顯示為「尚未實作」。每張 ticket 把自己的規則加進去。這樣 CI 可以從第一天就是綠的，而且不需要在測試上加跳過標記。
