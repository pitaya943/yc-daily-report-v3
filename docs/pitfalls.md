# 踩過的坑

只收「下一個 agent 不知道就會再犯」的事。由 Chief 在 milestone 結束時整理；Builder 與 Verifier 只能在 PR 說明裡提議。上限 30 條。刪除的條目不重新編號（D-092：#5、#7、#11 已被 CI 取代而刪除）。

| # | 情況 | 該怎麼做 | 來源（PR） | 加入於 |
| --- | --- | --- | --- | --- |
| 1 | pytest-bdd 以 scenario 名稱當 key，同一個 .feature 內重名時只留下最後一個，不會警告 | 不要假設收集數正確；`tests/unit/test_spec_collection.py` 會比對 spec 展開後的總數（M0 時 489），數字變了要查原因 | #2 | M0 |
| 2 | 本機資料庫防線是 fail-closed：shell 有 `PGSERVICE`、`PGSERVICEFILE`、`PGSYSCONFDIR` 或不認得的 `PG*` 變數時，`scripts/dev/*` 與測試會拒絕執行 | 看到 `refusing to connect:` 就先 `unset` 該變數；不要放寬 `app/core/local_url.py` | #2 | M0 |
| 3 | 測試會清空 `DATABASE_URL` 指向的本機資料庫中 `yc_v3` 的資料 | 要保留手動試用的資料，測試後重新匯入；不要把 `DATABASE_URL` 指到其他資料庫 | #2 | M0 |
| 4 | FastAPI 新版的 `app.routes` 是巢狀結構；Starlette `TestClient` 需要 `httpx2`，不是 `httpx` | 檢查路由用 `app.openapi()["paths"]`；不要把依賴換回 `httpx` | #2 | M0 |
| 6 | PostgreSQL 有引號的識別字區分大小寫（`"YC_V3"` ≠ `yc_v3`）；migration 不得定義函式、程序、trigger、`DO`、`lo_*`（D-045） | migration 只用小寫、不加引號的 `yc_v3.`；需要函式時先找 Kuei 授權 `allow_functions: true` | #5 | M0 |
| 8 | `no-weakened-tests` 與目標分支的最新 commit 比對結果；分支落後時可能被擋 | 推送前先 `git merge origin/milestone/Mx`（不要 rebase、不要用 GitHub 的 Update branch） | #5 | M0 |
| 9 | PR 說明被編輯時 CI 會重跑（`edited`），`evidence` 檢查靠這個 | 改完 PR 說明後等 CI 重跑；不要推空 commit 來觸發 CI | #5 | M0 |
| 10 | 子 session 不會被 CI 自動叫醒 | Builder 的指示寫明「推送後自己輪詢 check 結果直到全部跑完，再貼交付留言」；Chief 另用 `send_later` 排備援檢查，不要只等子 session 回報 | #5 | M0 |
| 12 | 測試改名會被 `no-weakened-tests` 判為原測試消失（D-046、D-052） | 不要為了整理而改測試名稱；真的需要時由 Chief 在 ticket 寫明舊名對新名，並記錄在 `docs/decisions.md` | #5 | M0 |
| 13 | `tests/unit/test_clock.py` 以文字掃描 `app/` 裡的 `now()`，連 docstring 與註解都會被判違規 | 產品程式的註解不要寫出那個字樣；時間一律用 `app/core/clock.py` | #4 | M0 |
| 14 | `scripts/dev/migrate` 會檢查已套用 migration 的 sha256 | 本機改過 migration 後先跑 `scripts/dev/db-reset` | #4 | M0 |
| 15 | `tests/unit/conftest.py` 會關掉 `world`（資料庫 fixture） | 需要資料庫的單元測試，照 `tests/unit/core/conftest.py` 把它開回來 | #4 | M0 |
| 16 | 本機資料庫時區和 CI（UTC）可能不同 | 不要斷言 psycopg 回傳的 `timestamptz` 的 `utcoffset()`；讓資料庫或 `app/core/clock.py` 換算 | #4 | M0 |
| 17 | `nothing else is written` 只扣掉前面步驟明確斷言過的寫入，目前只有 `an audit row ... is written` 會記錄 | 新增會斷言其他表寫入的步驟時，也要把斷言的列記錄進 recorder，否則產品正確也會失敗 | #4 | M0 |
| 18 | 共用步驟沒有全域載入 | 其他 feature 的步驟檔用 `from tests.steps.common.steps import *`，動作用 `recorder.perform(...)`（用法在 `tests/steps/common/steps.py` 開頭） | #4 | M0 |
| 19 | 碰到 usage 上限時子 session 會中斷，不會自己恢復 | 額度恢復後，Chief 用 `send_message` 請該 session 從中斷處繼續；不要另開新 session 重做 | M0 Chief | M1 |
| 20 | 某個 ticket 在驗證期間推送 milestone 分支，PR 分支就會落後，`no-weakened-tests` 可能擋下 | 驗證期間不推送 `milestone/Mx`；看板的更新等合併時一起推送 | M0 Chief | M1 |
| 21 | Verifier 若把刻意繞過也算進判定，會無謂地消耗修正輪數 | Verifier 的指示寫明 D-044：判 FAIL 只看疏忽與誤擋；刻意繞過另外列出，不影響判定 | M0 Chief | M1 |
| 22 | 有會影響完成條件的 issue 還在等 Kuei 時就開 Verifier，答案一改就白費一輪 | 先等 Kuei 回覆、更新完成條件，再開 Verifier；修正輪數有上限（兩輪） | M0 Chief | M1 |
| 23 | 推送到 `milestone/Mx` 的那次 CI run 有 7 項 skipped，看起來像沒跑完 | 判斷 milestone PR 能否合併，看 `pull_request` 事件那次 run；push 那次的 skipped 是正常的 | M0 Chief | M1 |
| 24 | Verifier 寫在 PR 上的判定留言不會叫醒 Chief（PR 訂閱只送 CI、review 與合併事件）；M1 因此兩度空等 7～20 分鐘 | 開 Verifier 後，用 `send_later` 每 10 分鐘以內檢查一次 PR 留言與子 session 狀態，直到判定出現 | M1 Chief | M1 |
| 25 | `done-when` 會把 ticket「完成條件」裡**加了反引號**的規則 ID 都當成必須在 `tests/implemented.txt` 且通過 | 規劃時，不在本 ticket 轉綠的規則 ID（純函式 ticket、延到後面的規則）不加反引號；改完用 `scripts/ci/checks.py` 的 `rule_ids_in()` 確認 | M1 Chief | M1 |
| 26 | `tests/steps/<feature ID>/` 的步驟要在該目錄 `conftest.py` 用 `pytest_configure` 註冊成 plugin，`tests/test_spec.py` 才看得到；註冊是全域的，同文字的步驟會靜靜覆蓋 | 仿 `tests/steps/IAM-F01/conftest.py`；跑完整 `python3 -m pytest`；新增步驟前先 `grep` 同文字；多個 feature 共用的步驟放 `tests/steps/common/`（例如 `outcome.py`） | #14、#18、#22 | M1 |
| 27 | FastAPI 的 `Form()` 需要 `python-multipart`，專案沒有宣告這個依賴（本機剛好裝著） | 用 `urllib.parse.parse_qs` 解析表單，或先請 Chief 授權修改 `pyproject.toml` | #14 | M1 |
| 28 | `async def` 的路由直接呼叫 scrypt 或同步 DB，會阻塞整個 event loop（4 個同時登入時 `/health` 要 1.9 s） | 需要 session、DB 或 CPU 密集計算的端點用 `def`；讀請求主體放在 async dependency | #14、#18 | M1 |
| 29 | Builder 自己加嚴、超出規格的斷言（例如「登入失敗時整個資料庫不變」）會擋住後續 ticket，而改它要找 Kuei（issue #20、#21） | 比規格更嚴的斷言要在 PR 說明列出；改變寫入行為前先 `grep "diff(\|check_nothing_written" tests/` | #22 | M1 |
| 30 | 金額四捨五入用內建 `round()` 是銀行家捨入，AD-2 的例子會錯；變異抽查時 Python 可能沿用舊的 `.pyc`，判讀錯誤 | 金額用 `Fraction` 與 `(2x+1)//2`；變異抽查時設 `PYTHONDONTWRITEBYTECODE=1` 並清 `__pycache__` | #13、#16 | M1 |
| 31 | HTMX 2 預設不把 4xx 回應換進畫面；`htmx:beforeSwap` 的 `detail.elt` 是換入的目標，不是送出的表單 | 在各頁自己的模板處理 `htmx:beforeSwap`（參考 `app/modules/reports/submit_a_daily_report/templates/reports.html`），用 `detail.target` 判斷是哪張表單；不改 `base.html`。Playwright 讀畫面前要等該次的 `waitForResponse` 與 swap 完成，`networkidle` 不夠 | #26、#28、#32、#34 | M2 |
| 32 | 補充測試寫死了規格已經推翻、只是程式還沒改的行為，下一張 ticket 會被 `no-weakened-tests` 與 D-052 卡住（T-202 第 1 輪 FAIL） | 改規格時，Chief 依 D-103 在同一個 commit 暫時移出受影響的規則並處理寫死舊行為的測試；Builder 的補充測試每個只放一個錯誤原因，不斷言規格已推翻的行為；Verifier 先模擬下一張 ticket 的新規則再跑全部測試 | #33、#36 | M2 |
| 33 | 這個容器的 Playwright 只有 Node 版（`require('playwright')`），`import playwright` 會失敗；只有 `httpx2` 沒有 `httpx`；變異抽查要從 `tests/` 整體用 `-k` 收集 | 瀏覽器腳本用 Node 寫，放 scratchpad；直接打 app 用標準庫 `urllib` 或 `requests`；不要只跑 `tests/test_spec.py`（步驟不會註冊，見 #26） | #26、#28、#32、#33、#34 | M2 |

