# 進度看板

Chief 是唯一能修改這個檔案的角色。Chief 每次開始工作時先讀這個檔案，不依賴對話紀錄。

狀態：`todo` → `building` → `verifying` → `fixing` → `passed` → `merged`，或 `escalated`（已開 issue 等 Kuei）、`blocked`（依賴的 ticket 尚未完成或被擋住）。

## M0（計畫：issue #1，D-029）

- 同時進行上限：2 張（T-002 ‖ T-003）。
- 模型：Chief claude-opus-5-5；Builder claude-sonnet-5-5；Verifier claude-opus-5-5；修正第二輪 Builder claude-opus-5-5。

## M1（計畫：issue #11，D-055）

- 順序：IAM 依序 T-101 → T-103 → T-102；純函式 T-111～T-114 與 IAM 平行。
- 同時進行上限：3 張。第一批 T-101、T-111、T-112；有一張合併就補 T-113、T-114。
- 模型：Chief claude-opus-5-5；Builder claude-sonnet-5-5；Verifier claude-opus-5-5；修正第二輪 Builder claude-opus-5-5。

## M2（計畫：issue #25，D-084～D-092）

- 順序：T-200 → T-201 → T-202 ‖ T-203；issue #29 新增 T-205（‖ T-202）與 T-204（在 T-202 之後）。
- 同時進行上限：2 張（T-202 ‖ T-203、T-202 ‖ T-205 平行；`tests/implemented.txt` 是例外，D-089、D-103）。
- 結果：6 張全部 merged；報告 `docs/milestones/M2.html`；未決 issue #35（不擋 M2）。
- 模型：Chief claude-opus-5-5；Builder claude-sonnet-5-5；Verifier claude-opus-5-5；修正第二輪 Builder claude-opus-5-5。

## M3（計畫：issue #38，D-110～D-121）

- 順序：階段 1 T-301 ‖ T-305 ‖ T-307 → 階段 2 T-303 ‖ T-302 ‖ T-308（T-305 合併後）→ 階段 3 T-306 ‖ T-304；migration 依序 `0006`（T-301）、`0007`（T-303）、`0008`（T-306）。
- 同時進行上限：3 張（階段 1）；之後 2 張。`tests/implemented.txt` 依 D-089 為例外。
- issue #35 已記為 D-104～D-109 並關閉。CI 安裝步驟已修正（D-119）；CI 時限調高（D-138）。
- 模型：Chief claude-opus-5-5；Builder claude-sonnet-5-5；Verifier claude-opus-5-5；修正第二輪 Builder claude-opus-5-5。

| Ticket | Milestone | 標題 | 狀態 | PR | 修正輪數 | 備註 |
| --- | --- | --- | --- | --- | --- | --- |
| T-001 | M0 | 專案骨架與測試框架 | merged | [#2](https://github.com/pitaya943/yc-daily-report-v3/pull/2) | 2 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（FAIL）；修正第 1 輪：claude-sonnet-5-5；Verifier 第 2 輪：claude-opus-5-5（FAIL：PGSERVICE）；修正第 2 輪：claude-opus-5-5（新 session）；Verifier 第 3 輪：claude-opus-5-5（PASS） |
| T-002 | M0 | CI 檢查 | merged | [#5](https://github.com/pitaya943/yc-daily-report-v3/pull/5) | 2 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（FAIL）；修正第 1 輪：claude-sonnet-5-5；issue #6 已決定（D-039～D-042）；Verifier 第 2 輪：claude-opus-5-5（FAIL）；issue #7 已決定（D-043～D-049）；修正第 2 輪：claude-opus-5-5（新 session）；Verifier 第 3 輪：claude-opus-5-5（PASS） |
| T-003 | M0 | 共用基礎：結果類別、稽核寫入、權限檢查 | merged | [#4](https://github.com/pitaya943/yc-daily-report-v3/pull/4) | 1 | Builder 第一輪：claude-sonnet-5-5；合併順序在 T-002 之後；CI 全綠；Verifier 第 1 輪：claude-opus-5-5（FAIL：nothing else is written）；修正第 1 輪：claude-sonnet-5-5；Verifier 第 2 輪：claude-opus-5-5（PASS） |
| T-101 | M1 | 登入 | merged | [#14](https://github.com/pitaya943/yc-daily-report-v3/pull/14) | 0 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（PASS）；規格問題 4 項 → issue #15（D-060～D-063） |
| T-102 | M1 | 登入鎖定與頻率限制 | merged | [#22](https://github.com/pitaya943/yc-daily-report-v3/pull/22) | 0 | Builder 第一輪：claude-sonnet-5-5；碰到 usage 上限一次；issue #20 → D-069、issue #21 → D-077；Verifier 第 1 輪：claude-opus-5-5（PASS，12 個變異全抓到） |
| T-103 | M1 | Session 與登出 | merged | [#18](https://github.com/pitaya943/yc-daily-report-v3/pull/18) | 0 | Builder 第一輪：claude-sonnet-5-5；合併 milestone 後 CI 重跑全綠；Verifier 第 1 輪：claude-opus-5-5（PASS）；IAM-R10 延到 T-201（D-058） |
| T-111 | M1 | 純函式：小組分配 | merged | [#12](https://github.com/pitaya943/yc-daily-report-v3/pull/12) | 0 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（PASS） |
| T-112 | M1 | 純函式：薪資公式 | merged | [#13](https://github.com/pitaya943/yc-daily-report-v3/pull/13) | 0 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（PASS；變異 2 個存活，測試缺口記給 T-402）；規格問題 → issue #15（D-064～D-068） |
| T-113 | M1 | 純函式：保留金 | merged | [#17](https://github.com/pitaya943/yc-daily-report-v3/pull/17) | 0 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（PASS）；規格問題見 issue #19 |
| T-114 | M1 | 純函式：庫存比對 | merged | [#16](https://github.com/pitaya943/yc-daily-report-v3/pull/16) | 0 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（PASS）；規格問題見 issue #19 |
| T-200 | M2 | 固定版本的 HTMX 與共用頁面版型 | merged | [#26](https://github.com/pitaya943/yc-daily-report-v3/pull/26) | 0 | Builder 第一輪：claude-sonnet-5-5；CI 第一次因 runner 網路錯誤失敗（install-postgres 的失敗被 `|| true` 吞掉），重跑全綠；Verifier 第 1 輪：claude-opus-5-5（PASS，9 個變異全抓到） |
| T-201 | M2 | 送出日報 | merged | [#28](https://github.com/pitaya943/yc-daily-report-v3/pull/28) | 0 | Builder 第一輪：claude-sonnet-5-5；共用步驟 `the outcome is` 與 RPT-R02／R03 的字串衝突 → issue #27 → D-093（同一個 session 繼續）；Verifier 第 1 輪：claude-opus-5-5（PASS，22 個變異全抓到；拿掉並行鎖的變異是機率性抓到，15 次中 10 次）；規格問題 → issue #29 |
| T-202 | M2 | 回報生命週期 | merged | [#33](https://github.com/pitaya943/yc-daily-report-v3/pull/33) | 1 | Builder 第一輪：claude-sonnet-5-5（20:41 碰到 usage 上限，22:01 繼續）；共用步驟衝突 → issue #30、#31 → D-094、D-095；Verifier 第 1 輪：claude-opus-5-5（FAIL：4 個補充測試寫死被 D-096／D-097 推翻的行為）；修正第 1 輪：claude-sonnet-5-5（同一 session）；Verifier 第 2 輪：claude-opus-5-5（PASS）；PR 說明的測試數字與未解問題第 3 點未更新（Builder 額度中斷），記入 milestone 報告；規格問題 → issue #35 |
| T-203 | M2 | 歷史與匯出 | merged | [#32](https://github.com/pitaya943/yc-daily-report-v3/pull/32) | 0 | Builder 第一輪：claude-sonnet-5-5（20:42 碰到 usage 上限，22:01 繼續）；Verifier 第 1 輪：claude-opus-5-5（PASS，14 個變異全抓到）；規格問題併入 issue #29；加嚴斷言「匯出只寫一列稽核」「一律斷言順序」可能影響 M4 匯出 |
| T-204 | M2 | 至少一個工項與共同作業者資格（規格更新） | merged | [#36](https://github.com/pitaya943/yc-daily-report-v3/pull/36) | 0 | Builder 第一輪：claude-sonnet-5-5；T-205 合併後 merge milestone 重跑 CI；Verifier 第 1 輪：claude-opus-5-5（PASS，7 個變異全抓到）；RPT-R03、R05 已加回（D-103）；規格問題併入 issue #35 第 6、7 項 |
| T-205 | M2 | 歷史篩選調整（規格更新） | merged | [#34](https://github.com/pitaya943/yc-daily-report-v3/pull/34) | 0 | Builder 第一輪：claude-sonnet-5-5；T-202 合併後 merge milestone 重跑 CI；Verifier 第 1 輪：claude-opus-5-5（PASS；產品變異 3/3，畫面變異 2 個只有 Playwright 抓得到）；PR 說明測試數字過時；規格問題併入 issue #35 第 5 項 |
| T-301 | M3 | 確認或駁回回報，保存份額 | merged | [#43](https://github.com/pitaya943/yc-daily-report-v3/pull/43) | 0 | Builder 第一輪：claude-sonnet-5-5；allowed_paths 漏列 `app/modules/review/__init__.py` → issue #42，Chief 依先例補上；Verifier 第 1 輪：claude-opus-5-5（PASS，8 個變異全抓到；並行測試拿掉鎖後 180 輪有 166 輪異常）；規格問題 3 項記入 M3 報告；Builder 在 merge milestone 時碰到 usage 上限（12:44～16:10），恢復後完成 |
| T-302 | M3 | 自訂工項 | merged | [#44](https://github.com/pitaya943/yc-daily-report-v3/pull/44) | 0 | Builder 第一輪：claude-sonnet-5-5（等 T-305 的共用步驟 S1；碰到 usage 上限一次）；Verifier 第 1 輪：claude-opus-5-5（PASS，5 個變異全抓到）；規格問題 → issue #46 第 8～11 項 |
| T-303 | M3 | 帳戶生命週期與薪資設定 | merged | [#45](https://github.com/pitaya943/yc-daily-report-v3/pull/45) | 0 | Builder 第一輪：claude-sonnet-5-5（等 T-305 的共用步驟 S1；碰到 usage 上限兩次；依 D-127、D-129、D-139 補改）；no-weakened-tests 逾時 → D-138；Verifier 第 1 輪：claude-opus-5-5（PASS）；規格問題 3 項記入 M3 報告 |
| T-304 | M3 | OWNER 管理管理員 | todo | — | — | — |
| T-305 | M3 | 密碼變更與重設 | merged | [#41](https://github.com/pitaya943/yc-daily-report-v3/pull/41) | 0 | Builder 第一輪：claude-sonnet-5-5；規格問題 → issue #40（D-122～D-125）；交付後依 Bugbot 意見補表單 `method="post"`；碰到 usage 上限一次；Verifier 第 1 輪：claude-opus-5-5（PASS，9 個變異全抓到）；規格問題 → issue #46 |
| T-306 | M3 | 銀行帳號、發薪方式與遮罩 | todo | — | — | — |
| T-307 | M3 | CI 的 Playwright 冒煙測試 | merged | [#39](https://github.com/pitaya943/yc-daily-report-v3/pull/39) | 0 | Builder 第一輪：claude-sonnet-5-5；CI 第一次 no-weakened-tests 在 PostgreSQL 安裝步驟失敗（D-119 讓失敗直接顯示），重跑全綠；Verifier 第 1 輪：claude-opus-5-5（PASS，4 個變異全抓到）；規格問題：setup-node 只固定主版號 22（M3 報告列出） |
| T-308 | M3 | 改密碼後的 session、鎖定與解除鎖定（規格更新） | building | [#48](https://github.com/pitaya943/yc-daily-report-v3/pull/48) | 0 | issue #40（D-122～D-125）、D-126；issue #47 → D-140（D-124 與 IAM-R30 既有 scenario 衝突，Chief 規劃遺漏）；Builder 第一輪：claude-sonnet-5-5（session_01LCMZdocvCBhsJSuGFNjGhC） |
| T-401 | M4 | 單價與費率設定 | todo | — | — | — |
| T-402 | M4 | 薪資計算與薪資批次 | todo | — | — | — |
| T-403 | M4 | 封存帳戶的薪資 | todo | — | — | — |
| T-404 | M4 | 年度結算 | todo | — | — | — |
| T-405 | M4 | 薪資批次的匯出與現金面額 | todo | — | — | — |
| T-406 | M4 | 個人統計與薪資試算 | todo | — | — | — |
| T-407 | M4 | 跨帳戶統計總表 | todo | — | — | — |
| T-501 | M5 | 庫存管理 | todo | — | — | — |
| T-502 | M5 | 申請材料 | todo | — | — | — |
| T-503 | M5 | 審核材料申請 | todo | — | — | — |
| T-504 | M5 | 庫存匯入與暫存區 | todo | — | — | — |
| T-511 | M5 | 流水帳紀錄與餘額 | todo | — | — | — |
| T-512 | M5 | 證據檔與作廢 | todo | — | — | — |
| T-601 | M6 | 日月報檔案庫 | todo | — | — | — |
| T-602 | M6 | 稽核軌跡 | todo | — | — | — |
| T-603 | M6 | 完整權限矩陣 | todo | — | — | — |
| T-604 | M6 | 並行測試與容量測試 | todo | — | — | — |
| T-605 | M6 | 附錄 D 檢查清單 | todo | — | — | — |
