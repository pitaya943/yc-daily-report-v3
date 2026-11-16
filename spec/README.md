# 員工日報系統 — 行為規格

| | |
| --- | --- |
| 狀態 | 由 Claude 撰寫。Kuei 於 2026-11-15 同意 AD-1–AD-13 的全部定義，並確認 Q-052–Q-062 的全部暫定答案。 |
| 內容 | 9 個能力域、31 個 feature、137 條規則、251 個 scenario |
| 來源 | Kuei 的決定 Q-001–Q-062，以及 Kuei 同意的 AD-1–AD-13 |
| 讀者 | 看不到舊系統的實作者與驗證者 |
| 範圍 | 使用者與管理員看得到、做得到的行為：欄位、驗證、計算、匯出、錯誤、權限。不規定資料表、API 路徑或部署方式。 |
| 語言 | 說明文字用繁體中文。Gherkin 的關鍵字與步驟用英文，因為要與程式綁定；使用者可見字串保留繁體中文原文，那是要被斷言的值。 |

**系統目的。** 工程隊（瓦斯管線施工）用的工具：員工每日回報工項數量，管理員確認，系統依已確認的回報計算薪資；另含材料庫存與申請、公司流水帳、日月報檔案庫。

## 目錄

| 檔案 | 內容 |
| --- | --- |
| `README.md` | 本檔：寫作規約、結果類別、標籤 |
| `glossary.md` | 通用語言與角色 |
| `capabilities.md` | 能力地圖與 feature 索引 |
| `state-machines.md` | 回報、材料申請、流水帳紀錄、帳戶的狀態轉移 |
| `background.md` | 所有 scenario 共用的固定資料 |
| `features/*.feature` | 31 個 feature，每個一檔 |
| `definitions.md` | 本規格自行定義的 13 條規則（AD-1–AD-13） |
| `appendix-a-catalogues.md` | 工項目錄、預設單價、預設設定 |
| `appendix-b-fields.md` | 欄位限制與錯誤字串 |
| `appendix-c-audit-types.md` | 稽核類型 |
| `appendix-d-non-scenario.md` | 不寫成 scenario 的需求 |
| `appendix-e-decisions.md` | 決策索引 |
| `appendix-f-v2-map.md` | v2 行為 ID 對照 |

## 結構

規格分四層，每個事實只寫在一層。

| 層 | 回答的問題 | 位置 |
| --- | --- | --- |
| Capability | 系統為誰解決什麼問題？ | `capabilities.md` |
| Feature | 使用者能完成哪一件事？ | 每個 `.feature` 檔 |
| Rule | 哪條商業規則必須永遠成立？ | `Rule:` 區塊，ID 如 `PAY-R03` |
| Scenario | 這條規則在具體資料下長怎樣？ | `Scenario`、`Scenario Outline` |
| 參考資料 | 目錄、欄位限制、錯誤字串 | 附錄 A–C，scenario 只引用 |
| 決策 | 為什麼是這個規則？ | 附錄 E；scenario 只帶標籤 |

## Scenario 寫作規約

1. **一個 scenario 只有一個 `When`。** 多個動作就拆成多個 scenario。
2. **宣告式，不寫 UI 步驟。** 寫「員工送出回報」，不寫「點擊送出按鈕」。UI 細節放在附錄 D。
3. **具體資料。** 邊界值用 `Scenario Outline` 加 `Examples` 表，一列就是一個測試。
4. **拒絕案例固定三斷言**：結果類別、完整錯誤字串、資料沒有任何變動。

   ```gherkin
   Then the request is rejected as <OUTCOME> with message "<訊息>"
   And nothing is written
   ```

5. **可測才寫。** 沒有數字的要求（例如「合理的延遲」）不進 scenario，放附錄 D。
6. **來源要標記。** `@provisional` 標示來自 v2 spec 暫定答案的規則；`@assumed @AD-n` 標示本規格定義的規則。兩者都已由 Kuei 於 2026-11-15 確認，標籤保留作為來源追溯；日後 Kuei 改決定時，用標籤找出所有受影響的 scenario。

## 結果類別

規格不規定 API，所以用與傳輸層無關的結果類別描述拒絕；下表把它們綁到 HTTP status（AD-9）。

| 結果類別 | 意義 | HTTP | 寫稽核 |
| --- | --- | --- | --- |
| `UNAUTHENTICATED` | 未登入或 session 過期 | 401 | 否 |
| `FORBIDDEN` | 已登入但角色或擁有權不符 | 403 | 是，`ACCESS_DENIED` |
| `INVALID` | 欄位不合附錄 B，或沒有這個動作 | 422 | 否 |
| `CONFLICT` | 資料合法但目前狀態不允許 | 409 | 否 |
| `LOCKED` | 帳戶鎖定中 | 423 | 是，鎖定當下寫 `ACCOUNT_LOCKOUT` |
| `RATE_LIMITED` | 超過來源位址頻率 | 429 | 否 |
| `BLOCKED` | 前置設定不完整（單價、金鑰） | 409 | 否 |

## 標籤

| 標籤 | 用途 |
| --- | --- |
| `@IAM-F01` | feature ID，每個檔案一個 |
| `@B-044` | 對應 v2 spec 的行為 ID |
| `@Q-041` | 對應 Kuei 的決定（附錄 E） |
| `@provisional` | 來源是 v2 spec 的暫定答案 Q-052–Q-062（已確認） |
| `@assumed @AD-n` | 來源是本規格定義的規則（`definitions.md`，已確認） |
| `@domain`、`@api`、`@ui` | 測試層級：純函式、服務邊界、端到端 |
| `@money` | 影響薪資金額，回歸測試必跑 |
| `@concurrency` | 需要真的平行請求 |

## 與 v2 spec 的關係

這份規格可以單獨閱讀與實作。它與 `yc-daily-report-v2/docs/spec.md` 的差異只有三類：

1. **結構**：規則只寫一次，驗收條件改成一列一個測試的例子表。
2. **13 條新定義**（`definitions.md`）。其中 AD-1（薪資批次）與 AD-4（回報記下工項組）影響資料模型，實作後要改的成本最高。
3. **2 個新錯誤字串**（附錄 B 最後兩列）。

**尚未完成的事。** Kuei 同意了 13 條定義與 11 個暫定答案，但沒有逐條審閱 245 個 scenario。例子裡的數字經過人工驗算，但沒有對照舊系統的實際輸出。Gherkin 還沒有用工具做過語法檢查。
