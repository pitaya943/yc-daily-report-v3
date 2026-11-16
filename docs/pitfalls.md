# 踩過的坑

只收「下一個 agent 不知道就會再犯」的事。由 Chief 在 milestone 結束時整理；Builder 與 Verifier 只能在 PR 說明裡提議。上限 30 條。

| # | 情況 | 該怎麼做 | 來源（PR） | 加入於 |
| --- | --- | --- | --- | --- |
| 1 | pytest-bdd 以 scenario 名稱當 key，同一個 .feature 內重名時只留下最後一個，不會警告 | 不要假設收集數正確；`tests/unit/test_spec_collection.py` 會比對 spec 展開後的總數（M0 時 489），數字變了要查原因 | #2 | M0 |
| 2 | 本機資料庫防線是 fail-closed：shell 有 `PGSERVICE`、`PGSERVICEFILE`、`PGSYSCONFDIR` 或不認得的 `PG*` 變數時，`scripts/dev/*` 與測試會拒絕執行 | 看到 `refusing to connect:` 就先 `unset` 該變數；不要放寬 `app/core/local_url.py` | #2 | M0 |
| 3 | 測試會清空 `DATABASE_URL` 指向的本機資料庫中 `yc_v3` 的資料 | 要保留手動試用的資料，測試後重新匯入；不要把 `DATABASE_URL` 指到其他資料庫 | #2 | M0 |
| 4 | FastAPI 新版的 `app.routes` 是巢狀結構；Starlette `TestClient` 需要 `httpx2`，不是 `httpx` | 檢查路由用 `app.openapi()["paths"]`；不要把依賴換回 `httpx` | #2 | M0 |
| 5 | `tests/implemented.txt` 打錯規則 ID 不會報錯，該跑的 scenario 會默默 skip | 加入規則 ID 後，確認收集結果中該規則的 scenario 是 passed 而不是 skipped | #2 | M0 |
| 6 | PostgreSQL 有引號的識別字區分大小寫（`"YC_V3"` ≠ `yc_v3`）；migration 不得定義函式、程序、trigger、`DO`、`lo_*`（D-045） | migration 只用小寫、不加引號的 `yc_v3.`；需要函式時先找 Kuei 授權 `allow_functions: true` | #5 | M0 |
| 7 | GitHub 網頁或 API 產生的 merge commit，作者 email 是 `bullet-bots` 帳號的主要 email，不是 noreply | `commit-author` 依 `author.login` 判斷（D-039）；不要改回比對 email | #5 | M0 |
| 8 | `no-weakened-tests` 與目標分支的最新 commit 比對結果；分支落後時可能被擋 | 推送前先 `git merge origin/milestone/Mx`（不要 rebase、不要用 GitHub 的 Update branch） | #5 | M0 |
| 9 | PR 說明被編輯時 CI 會重跑（`edited`），`evidence` 檢查靠這個 | 改完 PR 說明後等 CI 重跑；不要推空 commit 來觸發 CI | #5 | M0 |
| 10 | 子 session 不會被 CI 自動叫醒 | Builder 推送後要自己輪詢 check 結果直到全部跑完，再貼交付留言 | #5 | M0 |
| 11 | ticket front matter 沒有 `screens` 欄位時 `evidence` 判為失敗（D-040） | Chief 規劃 milestone 時替每張 ticket 填 `screens: true/false`；`tests/ci/` 自建 ticket 時用 `make_ticket` | #5 | M0 |
| 12 | 測試改名會被 `no-weakened-tests` 判為原測試消失（D-046） | 不要為了整理而改測試名稱；真的需要時先請 Chief 處理（issue #8） | #5 | M0 |
| 13 | `tests/unit/test_clock.py` 以文字掃描 `app/` 裡的 `now()`，連 docstring 與註解都會被判違規 | 產品程式的註解不要寫出那個字樣；時間一律用 `app/core/clock.py` | #4 | M0 |
| 14 | `scripts/dev/migrate` 會檢查已套用 migration 的 sha256 | 本機改過 migration 後先跑 `scripts/dev/db-reset` | #4 | M0 |
| 15 | `tests/unit/conftest.py` 會關掉 `world`（資料庫 fixture） | 需要資料庫的單元測試，照 `tests/unit/core/conftest.py` 把它開回來 | #4 | M0 |
| 16 | 本機資料庫時區和 CI（UTC）可能不同 | 不要斷言 psycopg 回傳的 `timestamptz` 的 `utcoffset()`；讓資料庫或 `app/core/clock.py` 換算 | #4 | M0 |
| 17 | `nothing else is written` 只扣掉前面步驟明確斷言過的寫入，目前只有 `an audit row ... is written` 會記錄 | 新增會斷言其他表寫入的步驟時，也要把斷言的列記錄進 recorder，否則產品正確也會失敗 | #4 | M0 |
| 18 | 共用步驟沒有全域載入 | 其他 feature 的步驟檔用 `from tests.steps.common.steps import *`，動作用 `recorder.perform(...)`（用法在 `tests/steps/common/steps.py` 開頭） | #4 | M0 |
