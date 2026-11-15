# 進度看板

Chief 是唯一能修改這個檔案的角色。Chief 每次開始工作時先讀這個檔案，不依賴對話紀錄。

狀態：`todo` → `building` → `verifying` → `fixing` → `passed` → `merged`，或 `escalated`（已開 issue 等 Kuei）、`blocked`（依賴的 ticket 尚未完成或被擋住）。

## M0（計畫：issue #1，D-029）

- 同時進行上限：2 張（T-002 ‖ T-003）。
- 模型：Chief claude-opus-5-5；Builder claude-sonnet-5-5；Verifier claude-opus-5-5；修正第二輪 Builder claude-opus-5-5。

| Ticket | Milestone | 標題 | 狀態 | PR | 修正輪數 | 備註 |
| --- | --- | --- | --- | --- | --- | --- |
| T-001 | M0 | 專案骨架與測試框架 | merged | [#2](https://github.com/pitaya943/yc-daily-report-v3/pull/2) | 2 | Builder 第一輪：claude-sonnet-5-5；Verifier 第 1 輪：claude-opus-5-5（FAIL）；修正第 1 輪：claude-sonnet-5-5；Verifier 第 2 輪：claude-opus-5-5（FAIL：PGSERVICE）；修正第 2 輪：claude-opus-5-5（新 session）；Verifier 第 3 輪：claude-opus-5-5（PASS） |
| T-002 | M0 | CI 檢查 | building | — | 0 | Builder 第一輪：claude-sonnet-5-5 |
| T-003 | M0 | 共用基礎：結果類別、稽核寫入、權限檢查 | building | [#4](https://github.com/pitaya943/yc-daily-report-v3/pull/4) | 0 | Builder 第一輪：claude-sonnet-5-5；合併順序在 T-002 之後；PR 已開，等 T-002 合併後跑 CI |
| T-101 | M1 | 登入 | todo | — | — | — |
| T-102 | M1 | 登入鎖定與頻率限制 | todo | — | — | — |
| T-103 | M1 | Session 與登出 | todo | — | — | — |
| T-111 | M1 | 純函式：小組分配 | todo | — | — | — |
| T-112 | M1 | 純函式：薪資公式 | todo | — | — | — |
| T-113 | M1 | 純函式：保留金 | todo | — | — | — |
| T-114 | M1 | 純函式：庫存比對 | todo | — | — | — |
| T-201 | M2 | 送出日報 | todo | — | — | — |
| T-202 | M2 | 回報生命週期 | todo | — | — | — |
| T-203 | M2 | 歷史與匯出 | todo | — | — | — |
| T-301 | M3 | 確認或駁回回報，保存份額 | todo | — | — | — |
| T-302 | M3 | 自訂工項 | todo | — | — | — |
| T-303 | M3 | 帳戶生命週期與薪資設定 | todo | — | — | — |
| T-304 | M3 | OWNER 管理管理員 | todo | — | — | — |
| T-305 | M3 | 密碼變更與重設 | todo | — | — | — |
| T-306 | M3 | 銀行帳號遮罩與顯示 | todo | — | — | — |
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
