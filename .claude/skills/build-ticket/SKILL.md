---
name: build-ticket
description: 實作一張 ticket：先讓指定的 scenario 失敗，再實作到通過，然後開 PR。只有 Builder 使用。
---

# 做一張 ticket

## 開始前

1. 讀 ticket 檔，然後只讀它「要讀的檔案」列出的內容。
2. 依 `AGENTS.md` 的「GitHub 身分」設定 commit 作者，並確認登入帳號是 `bullet-bots`。
3. 從 `milestone/Mx` 開出 `ticket/T-xxx` 分支。
4. 有任何一條完成條件看不懂，或規格互相矛盾：停止，用 `ask-spec-question`。不要猜。

## 步驟

1. **先紅。** 把 ticket 的規則 ID 加進 `tests/implemented.txt`，寫步驟實作，執行測試，確認這些 scenario 失敗，而且失敗的原因是功能不存在，不是步驟寫錯。把失敗的輸出留下來，PR 說明要用。
2. **再綠。** 實作到全部通過。一次處理一條規則。
3. **拒絕案例**逐一確認三件事都有被斷言：結果類別、完整錯誤字串、資料沒有任何變動。
4. 執行全部測試，確認沒有弄壞先前的規則。
5. 檢查自己改過的檔案都在 `allowed_paths` 內。
6. 推送並開 PR，目標分支是 `milestone/Mx`。依 `.github/PULL_REQUEST_TEMPLATE.md` 填寫，用繁體中文。
7. 等 CI。CI 沒有全綠就繼續修，直到全綠才算交付。
8. 在 PR 留一則交付留言：完成條件逐條對應的證據，以及你的模型名稱與版本。模型名稱從 session 的實際設定取得，不要憑印象寫。

## 證據

- 每一條完成條件都要有證據，沒有證據就不算完成。
- CLI：貼上指令與輸出。輸出太長時保留開頭、結尾與統計行。
- 有畫面的功能：用瀏覽器實際操作並截圖，存到 `docs/evidence/<ticket 編號>/`，檔名說明內容，在 PR 中連結。
- 「先紅」的失敗輸出也是證據。

## 不要做

- 不要修改 `spec/**`。Scenario 看起來有錯時用 `ask-spec-question`。
- 不要跳過、標記預期失敗、刪除或放寬任何測試。
- 不要讓步驟實作永遠通過。步驟必須真的呼叫產品程式並檢查結果。
- 不要在 `app/domain/` 以外用浮點數計算金額或數量。數量以 0.1 只的整數計。
- 不要直接呼叫系統時間，用 `app/core/clock.py`。
- 不要新增 ticket 沒有授權的 migration。需要時用 `add-migration`（只在 `migration: true` 時）。
- 不要合併自己的 PR。

## PR 說明要有

- 完成了什麼：ticket 編號、規則 ID、scenario 數。
- 如何驗證：指令與預期結果。
- 證據：每條完成條件的 CLI 輸出或截圖路徑；「先紅」時的失敗輸出。
- Milestone 報告的路徑。
- 比規格更嚴格的斷言：逐條列出（例如規格只寫某個步驟，測試卻斷言整個資料庫不變）。這類斷言會被 CI 保護，之後要放寬得經過 Kuei（D-091）。
- 未解問題與想加入 `docs/pitfalls.md` 的提議。
