-- 目的：帳戶的銀行帳號（只存密文）與發薪方式（IAM-F04 的 IAM-R14、IAM-F07，D-113）。
--       * bank_number_cipher  銀行帳號的密文：12 bytes 的隨機 nonce ‖ AES-256-GCM 的密文 ‖ 16 bytes 驗證標籤。
--                             null 表示還沒有設定。資料庫裡永遠沒有明文，也沒有金鑰；金鑰在環境變數 BANK_NUMBER_KEY，
--                             加解密都在應用程式內（app/modules/iam/bank_number_masking_and_reveal/crypto.py）。
--                             至少 12 + 16 + 14 = 42 bytes（14 位數字的明文）；check 約束擋掉明顯不是密文的值。
--       * payment_method      發薪方式：TRANSFER（轉帳）或 CASH（現金）。既有的帳戶一律是 CASH（D-116）：
--                             欄位的 default 就是 CASH，而且 `add column ... default` 會把它寫進既有的帳戶，所以不必另外 update。
-- 資料庫的最後防線：發薪方式為 TRANSFER 時一定要有銀行帳號（IAM-R14「改為轉帳前須有帳號」）。
--       應用程式的驗證是第一道，這條約束是最後一道。
-- Ticket：T-306（migration 0008）。依賴 0001（yc_v3.accounts）。
-- 套用後檢查（預期 1 列，值為 t；兩個欄位都在，而且沒有任何帳戶是 TRANSFER 卻沒有帳號）：
--   select (select count(*) from information_schema.columns
--            where table_schema = 'yc_v3' and table_name = 'accounts'
--              and column_name in ('bank_number_cipher', 'payment_method')) = 2
--          and (select count(*) from yc_v3.accounts
--                where payment_method = 'TRANSFER' and bank_number_cipher is null) = 0;
--   （套用後若已有人設定過銀行帳號或改成轉帳，各帳戶的值會不同；這個查詢只檢查結構與約束，不受影響。）
-- 回滾（只在 Kuei 同意時；會丟掉所有帳戶已設定的銀行帳號密文與發薪方式，且無法從資料庫復原）：
--   alter table yc_v3.accounts
--       drop column payment_method,
--       drop column bank_number_cipher;
--   然後從 yc_v3.schema_migrations 刪掉 version = '0008'。
-- 部署前置：應用程式環境要有 BANK_NUMBER_KEY（base64 的 32 bytes）。沒有時應用程式照常運作，
--       銀行帳號顯示「無法讀取」、不能設定（IAM-R43）；金鑰一旦丟失，已存的密文就無法解開。
-- 只碰 yc_v3；可重複執行（`add column if not exists`：欄位已存在時整句略過，欄位上的約束也一併略過）。
--
-- 設計說明：
--   * 為什麼用 bytea、不用 text：密文是任意位元組，不需要再編碼成 base64 才能存；也避免有人把它當成可讀字串。
--   * 為什麼 check 約束寫在欄位上：PostgreSQL 允許欄位層級的 check 參照同一列的其他欄位，欄位已存在時整句略過，
--     可重複執行，也不需要 drop（add-migration：不 DROP；D-045：不用 DO 區塊）。

alter table yc_v3.accounts
    add column if not exists bank_number_cipher bytea
        constraint accounts_bank_number_cipher_check check (bank_number_cipher is null or octet_length(bank_number_cipher) >= 42),
    add column if not exists payment_method text not null default 'CASH'
        constraint accounts_payment_method_check
        check (payment_method in ('TRANSFER', 'CASH') and (payment_method = 'CASH' or bank_number_cipher is not null));
