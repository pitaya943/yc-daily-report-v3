---
name: plan-milestone
description: 在 milestone 開始前，把該 milestone 切成 ticket、確認依賴與平行安排，並開 issue 請 Kuei 核准。只有 Chief 使用。
---

# 規劃一個 milestone

## 步驟

1. 依 `AGENTS.md` 的「GitHub 身分」確認登入帳號是 `bullet-bots` 並設定 commit 作者。然後讀 `docs/board.md`、`docs/milestones/README.md`、`docs/decisions.md` 的「待決定」、`docs/pitfalls.md`。
2. 確認前一個 milestone 已合併進 `main`。還沒有就停止並告訴 Kuei。
3. 逐張檢查該 milestone 的 ticket 檔：
   - 依賴的 ticket 是否都已 `merged`。
   - `allowed_paths` 是否符合 repo 現在的目錄結構。
   - 完成條件列出的規則 ID 是否都還存在於 `spec/features/`。
   - 「待決定」的項目是否擋住這張 ticket。
4. 需要調整時修改 ticket 檔，並記下差異。一張 ticket 的 scenario 超過 20 個，或需要改三個以上的模組時，考慮拆開。
5. 排出平行安排：依賴都已完成且路徑不重疊的 ticket 可以同時進行；`migration: true` 的一次一張。
6. 用 `.github/ISSUE_TEMPLATE/plan-approval.md` 開 issue。
7. **等 Kuei 回覆同意。** 在那之前不開任何 Builder session。

## 輸出

一個 `plan-approval` issue，以及更新過的 ticket 檔（放在 `milestone/Mx` 分支上的一個 commit）。

## 不要做

- 不要改 `spec/`。發現規格問題時用 `ask-spec-question`。
- 不要自己決定 ticket 檔沒有授權的資料模型變更。
