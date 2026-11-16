---
name: ask-spec-question
description: 遇到規格不清楚、需要未授權的變更、修正兩輪失敗、或動到沒有 scenario 涵蓋的敏感程式時，開 issue 請 Kuei 決定。任何角色都可使用。
---

# 請 Kuei 決定

## 什麼時候用

`AGENTS.md`「什麼時候停下來找 Kuei」的四種情況。其他情況不要用；自己能從規格讀出答案的事不要問。

## 步驟

1. 停止這張 ticket 上會受答案影響的工作。已完成且不受影響的部分先提交。
2. 找出確切的出處：規則 ID、檔案與行號、互相矛盾的兩段文字。
3. 想出兩到三個選項。每個選項寫清楚：做法、對使用者的後果、要改哪些 scenario 或檔案、之後反悔的成本。
4. 選一個建議，寫出理由。**不要替 Kuei 決定**，也不要先照建議實作。
5. 用 `.github/ISSUE_TEMPLATE/needs-kuei.md` 開 issue，用繁體中文。
6. Builder 與 Verifier：把 issue 連結回報給 Chief，然後結束。Chief：把 ticket 標為 `escalated`，把依賴它的標為 `blocked`，繼續其他 ticket。

## 好問題的樣子

> **問題**：編輯回報時把數量全部改成 0，要當成刪除嗎？
> **出處**：`RPT-R11`；`spec/features/RPT-F02-report-lifecycle.feature`
> **選項 A（建議）**：保留為數量全為 0 的回報，仍佔當日額度。不需改 scenario。
> **選項 B**：視為刪除並釋放額度。要新增一個 scenario，並影響 `RPT-R04`。

## Kuei 回覆之後（Chief）

1. 在 `docs/decisions.md` 新增一列。
2. 回覆改變規格時，修改 `spec/` 與受影響 ticket 的完成條件，放在同一個 PR。
3. 把 ticket 改回 `todo` 或 `building`，解除 `blocked`。
4. 推送後在 issue 留言寫明記錄在哪個 D 編號與 commit，然後關閉 issue（D-059）。
