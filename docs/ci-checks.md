# CI 檢查

由 T-002 實作。每一項都要有一個「會讓它失敗」的測試案例，證明檢查真的有效。

| 檢查 | 內容 | 失敗時 |
| --- | --- | --- |
| `tests` | 在乾淨的 PostgreSQL 上執行單元測試與 `tests/implemented.txt` 列出的所有規則的 scenario。 | 任何一個失敗 |
| `spec-readonly` | 來源分支是 `ticket/*` 的 PR 不得修改 `spec/**`、`AGENTS.md`、`.claude/**`、`.github/**`、`docs/decisions.md`、`docs/board.md`。 | 有任何一個被修改 |
| `path-scope` | 從分支名稱找到 `docs/tickets/T-xxx.md`，PR 修改的每個檔案都要符合它的 `allowed_paths`。 | 有範圍外的檔案 |
| `evidence` | PR 說明的「證據」一節不是空的；ticket 涉及畫面時，`docs/evidence/<ticket 編號>/` 至少有一張截圖。 | 缺少證據 |
| `migration-scope` | `migrations/*.sql` 只能操作 `yc_v3`；不得出現對其他 schema 的 `CREATE`、`ALTER`、`DROP`、`TRUNCATE`。只有 `migration: true` 的 ticket 能新增 migration，且檔名編號等於 `migration_number`。已合併的 migration 不得被修改。 | 任一條不符 |
| `no-weakened-tests` | 測試程式不得出現跳過或預期失敗的標記；`tests/implemented.txt` 只能增加，不能減少。 | 任一條不符 |
| `done-when` | Ticket 完成條件列出的規則 ID 都在 `tests/implemented.txt` 中，且對應的 scenario 都被收集並通過。 | 有規則缺漏或沒被執行 |
| `strings` | 產品程式中出現的錯誤訊息都存在於 `spec/appendix-b-fields.md`。 | 有規格沒有的字串 |
| `commit-author` | PR 中每個 commit 的作者都是 `bullet-bots`（`354516064+bullet-bots@users.noreply.github.com`）。 | 有其他作者的 commit |
| `lint` | 格式與靜態檢查。 | 有錯誤 |

Milestone PR（`milestone/Mx → main`）另外檢查：該 milestone 規劃的規則 ID 全部在 `tests/implemented.txt` 中。

## `tests/implemented.txt` 的作用

`spec/features/` 從第一天就有全部 245 個 scenario，但多數還沒實作。這個檔案列出已實作的規則 ID；測試只執行列在其中的規則，其餘顯示為「尚未實作」。每張 ticket 把自己的規則加進去。這樣 CI 可以從第一天就是綠的，而且不需要在測試上加跳過標記。
