-- 目的：登入需要的資料（IAM-F01），並一次建好 T-103（Session 與登出）需要的欄位，因為 T-103 不能新增 migration（D-037）。
--       1. yc_v3.accounts 加 password_hash：密碼雜湊字串，格式 `<演算法>$<參數>$<salt>$<雜湊>`（D-056：scrypt）。
--       2. 建立 yc_v3.sessions：登入後發出的 session。
--          * token_hash          只存 session 憑證的 SHA-256，資料庫外洩時不能直接拿來當憑證用。
--          * anti_forgery_token  T-103 的 anti-forgery 檢查要比對的值（每個 session 一個，可明文存放）。
--          * created_at          發出的時間。
--          * last_used_at        最後使用時間，T-103 的 30 分鐘閒置逾時（IAM-R10）要用。
-- Ticket：T-101（migration 0003）。依賴 0001（yc_v3.accounts）。
-- 套用後檢查（預期 1 列，兩個值都是 t）：
--   select to_regclass('yc_v3.sessions') is not null as has_sessions,
--          exists (select 1 from information_schema.columns
--                  where table_schema = 'yc_v3' and table_name = 'accounts' and column_name = 'password_hash') as has_password_hash;
-- 回滾（只在還沒有真實資料、且 Kuei 同意時；會讓所有人登出，並丟掉已設定的密碼）：
--   drop table yc_v3.sessions;
--   alter table yc_v3.accounts drop column password_hash;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0003'
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。
--
-- 設計說明：
--   * password_hash 可為 null：既有帳戶還沒設定密碼時不能登入（等同密碼錯誤），不是「空密碼」。
--     check 約束只要求帶有「演算法$」前綴（D-056，日後可漸進換演算法），並擋掉不小心寫進去的明文密碼。
--   * 時間欄位存帶時區的時間；寫入的值來自 app/core/clock.py，不用資料庫的 now()。
--   * 帳戶只封存、不刪除（附錄 C 沒有 ACCOUNT_DELETE），所以 account_id 不設 on delete cascade。

-- 約束寫在欄位上：欄位已存在時整句略過，所以可重複執行，也不必先 drop 再加。
alter table yc_v3.accounts
    add column if not exists password_hash text
    constraint accounts_password_hash_format_check check (password_hash is null or position('$' in password_hash) > 1);

create table if not exists yc_v3.sessions (
    id                  bigint generated always as identity primary key,
    account_id          bigint      not null references yc_v3.accounts (id),
    token_hash          text        not null,
    anti_forgery_token  text        not null,
    created_at          timestamptz not null,
    last_used_at        timestamptz not null,
    constraint sessions_token_hash_key unique (token_hash),
    constraint sessions_last_used_check check (last_used_at >= created_at)
);

create index if not exists sessions_account_idx on yc_v3.sessions (account_id);
