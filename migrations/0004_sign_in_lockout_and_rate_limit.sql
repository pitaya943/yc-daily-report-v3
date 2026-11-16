-- 目的：登入鎖定與頻率限制（IAM-F02）需要的計數，存在資料庫而不是行程記憶體，
--       讓兩個 worker 與重新啟動之後計數仍然一致（T-102 完成條件 9）。
--       1. yc_v3.sign_in_failures：每個帳戶最多一列，記「目前這一輪」的密碼錯誤次數與鎖定時間。
--          * fail_count      這一輪的密碼錯誤次數（IAM-R04：滿 5 次鎖定）。
--          * last_failed_at  最後一次密碼錯誤的時間；距離現在滿 15 分鐘就視為新的一輪（IAM-R05）。
--          * locked_at       鎖定的起點；沒有鎖定時為 null。鎖定在 locked_at 之後滿 15 分鐘結束（IAM-R04）。
--          登入成功時整列刪除（IAM-R05）。以帳戶計數，與來源位址無關（IAM-R06）。
--       2. yc_v3.sign_in_attempts：被接受評估的登入嘗試，每次一列，依來源位址與時間查詢（IAM-R07：每分鐘 10 次）。
--          過期的列在同一個位址下一次被接受的嘗試時一併刪除，所以表的大小以「每個位址每分鐘 10 列」為上限。
-- Ticket：T-102（migration 0004）。依賴 0001（yc_v3.accounts）。
-- 套用後檢查（預期 1 列，兩個值都是 t）：
--   select to_regclass('yc_v3.sign_in_failures') is not null as has_failures,
--          to_regclass('yc_v3.sign_in_attempts') is not null as has_attempts;
-- 回滾（只在 Kuei 同意時；會讓所有帳戶的鎖定與頻率限制歸零）：
--   drop table yc_v3.sign_in_attempts;
--   drop table yc_v3.sign_in_failures;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0004'
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。
--
-- 設計說明：
--   * 時間欄位存帶時區的時間；寫入的值來自 app/core/clock.py，不用資料庫的 now()。
--   * 序列化靠應用程式在交易內取 advisory lock（帳戶一把、來源位址一把），不靠函式或觸發器（D-045）。
--   * client_address 是文字：IPv4、IPv6 或無法判斷時的固定字串，不在資料庫層解析。

create table if not exists yc_v3.sign_in_failures (
    account_id      bigint      primary key references yc_v3.accounts (id),
    fail_count      integer     not null check (fail_count >= 1),
    last_failed_at  timestamptz not null,
    locked_at       timestamptz,
    constraint sign_in_failures_locked_check check (locked_at is null or fail_count >= 5)
);

create table if not exists yc_v3.sign_in_attempts (
    id              bigint generated always as identity primary key,
    client_address  text        not null check (client_address <> ''),
    attempted_at    timestamptz not null
);

-- 頻率限制：某個位址在最近 60 秒內有幾次
create index if not exists sign_in_attempts_address_time_idx on yc_v3.sign_in_attempts (client_address, attempted_at);
