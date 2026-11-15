---
name: add-migration
description: 在 ticket 標示 migration: true 時新增一個純 SQL 的 migration。只有 Builder 使用。
---

# 新增 migration

## 前提

Ticket 的 `migration` 是 `true`。不是的話停止，用 `ask-spec-question`。

## 步驟

1. 檔名：`migrations/<migration_number>_<英文名稱>.sql`，編號用 ticket 檔指定的 `migration_number`。
2. 只操作 `yc_v3`。每個物件都寫出 schema 名稱，不依賴 `search_path`。
3. 只新增，不破壞：不 `DROP`、不 `TRUNCATE`、不修改已合併的 migration 檔。需要改既有的表時，用新的 migration 加欄位。
4. 可以重複執行：用 `IF NOT EXISTS`。
5. 檔案最上方用註解寫明：目的、對應的 ticket、套用後如何檢查（一句可以直接執行的查詢與預期結果）、如何回滾。
6. 在乾淨的資料庫上從第一個 migration 套用到最新，確認成功；再執行一次，確認沒有錯誤。
7. 金額欄位用整數；數量欄位以 0.1 只的整數存；時間欄位存帶時區的時間。

## 不要做

- 不要連線到共用的 Supabase 專案。
- 不要在 migration 裡放資料以外的邏輯（觸發器、函式）除非 ticket 明確要求。
- 不要在同一張 ticket 新增多於一個 migration 檔。

## Kuei 之後會做的事

Milestone 合併後，Kuei 依 milestone 報告的步驟手動把這些檔案套用到共用資料庫。所以檔案開頭的檢查方式與回滾方式要寫到 Kuei 可以直接照做。
