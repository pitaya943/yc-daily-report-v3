---
name: milestone-report
description: 在 milestone 的 ticket 全部合併後，寫給 Kuei 的 HTML 報告並開 milestone PR。只有 Chief 使用。
---

# 寫 milestone 報告

## 前提

該 milestone 的每張 ticket 都是 `merged`，`milestone/Mx` 的 CI 全綠。

## 步驟

1. 複製 `docs/milestones/report-template.html` 為 `docs/milestones/Mx.html`。
2. 依樣板的每一節填寫。資料來源只用 repo 與 GitHub 上看得到的東西：ticket 檔、PR 說明、Verifier 留言、CI 結果、`docs/decisions.md`。不要憑印象寫。
3. 數字要能被重算：寫「通過 47 個 scenario」時，附上產生這個數字的指令與輸出。報告中每一個「已驗證」的說法都連到證據：CLI 輸出，或 `docs/evidence/` 下的截圖。
4. 「如何驗證」一節寫成 Kuei 可以照做的步驟：指令、預期輸出、手動操作的流程。Kuei 會用自己選的模型與環境驗證，所以不要假設他用的是這個 repo 的 agent。
5. 「為何這樣設計」一節寫出真的比較過的選項與放棄的理由。只有一種合理做法的地方不用硬湊選項。
6. 「agent 自行做的判斷」一節不可省略。列出規格沒有明說、由 agent 決定的每一件事；沒有就寫「無」。
7. 整理 `docs/pitfalls.md`：從各 PR 的提議中挑選，遵守上限。
8. 開 `milestone/Mx → main` 的 PR，指派給 Kuei。PR 說明簡短，並指向報告的路徑。
9. 關閉這個 milestone 所有已完成的子 session。

## 寫作規則

- 只用繁體中文，專業術語除外。
- 先講結論。讀者是 Kuei，他沒有看過任何一張 ticket 的過程。
- 沒做到的事直接寫沒做到，不要寫成「後續可以改善」。
- 不要誇大。測試通過只代表符合規格，不代表規格是對的。
