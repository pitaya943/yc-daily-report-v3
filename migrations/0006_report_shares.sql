-- 目的：確認回報時保存每個人的份額（REV-F02 REV-R11），並記下誰在何時確認或駁回（REV-F01）。
--       1. yc_v3.reports 新增兩個欄位（既有欄位與資料不動）：
--          * reviewer_id   確認或駁回的管理員（accounts.id）。PENDING 為 null；管理員編輯回到 PENDING 時清回 null。
--          * reviewed_at   確認或駁回的時間，帶時區；值來自 app/core/clock.py，不用資料庫的 now()。
--          兩欄刻意不加「PENDING 一定沒有 reviewer」的約束：T-202、T-203 的測試直接寫入 CONFIRMED 的回報（沒有 reviewer），
--          而且「新增約束」沒有 IF NOT EXISTS，會讓這個檔案不能重複執行。這條不變式由應用程式在同一個 transaction 內維持。
--       2. yc_v3.report_shares        目錄工項的份額：一列 = 一張回報、一個工項、一個人。
--          * tenths   該人在該工項的數量，以 0.1 只的整數存（2.3 只 = 23），0–9999。
--          * position 這個人在作業小組的順位：0 = 提交者，1 起是共同作業者（report_crew.position）。
--                     確認當下就存下來：之後共同作業者被封存、改區域、或回報被改，已存的份額不受影響（AD-7）。
--          * 只存「數量大於 0 的工項」；每個存下的工項，小組的每個人都有一列，包含份額 0 的人
--            （0.1 只分給 3 人 = 0.1、0.0、0.0）。沒有列的工項視為 0。
--       3. yc_v3.report_custom_shares 自訂工項的份額（REV-R11 最後一個 scenario）：每張回報最多一個自訂工項，
--          所以不需要工項代碼；欄位意義同上。單價仍存在 reports.custom_price；自訂工項的金額（份額 × 單價）由 T-302 計算。
--       份額表是「已確認數量」的唯一來源：薪資只讀份額，不再回頭用 report_items 與目前的作業小組重算（D-111）。
-- Ticket：T-301（migration 0006）。依賴 0001（accounts）、0005（reports）。
-- 套用後檢查（預期 1 列，四個值都是 t）：
--   select to_regclass('yc_v3.report_shares') is not null as has_shares,
--          to_regclass('yc_v3.report_custom_shares') is not null as has_custom_shares,
--          exists (select 1 from information_schema.columns where table_schema = 'yc_v3' and table_name = 'reports' and column_name = 'reviewer_id') as has_reviewer,
--          exists (select 1 from information_schema.columns where table_schema = 'yc_v3' and table_name = 'reports' and column_name = 'reviewed_at') as has_reviewed_at;
-- 回滾（只在還沒有真實的確認資料、且 Kuei 同意時；會丟掉所有已保存的份額與審核者）：
--   drop table yc_v3.report_custom_shares;
--   drop table yc_v3.report_shares;
--   alter table yc_v3.reports drop column reviewed_at;
--   alter table yc_v3.reports drop column reviewer_id;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0006'
--   回滾後，已 CONFIRMED 的回報沒有份額：要嘗試補救就把它們改回 PENDING 再重新確認，不要手算份額。
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。
--
-- 設計說明：
--   * 為什麼不用「只記份額規則，薪資時再算」：份額會因小組成員被封存、改區域、回報被編輯而變；
--     存下來才能保證「確認時的數字就是薪資用的數字」。代價是多兩張表，而且 CONFIRMED → PENDING（管理員編輯）時
--     必須刪掉份額（RPT-R12），否則會留下與內容不符的份額；刪除回報則靠 on delete cascade 一併刪除。
--   * 「份額只存一次」靠主鍵：同一張回報的同一個工項、同一個人只能有一列，並行的兩次確認不可能存兩份
--     （應用程式還會先鎖回報，第二個請求看到 CONFIRMED 就略過，不會走到寫入）。
--   * 份額的總和等於工項數量由應用程式（app/domain/split.py）保證，不在資料庫用約束檢查：
--     那需要跨表的彙總約束，只能靠 trigger 或函式，D-045 不允許。測試會比對總和。
--   * account_id 不 cascade：帳戶只封存、不刪除（附錄 C 沒有 ACCOUNT_DELETE）。

alter table yc_v3.reports add column if not exists reviewer_id bigint references yc_v3.accounts (id);
alter table yc_v3.reports add column if not exists reviewed_at timestamptz;

create table if not exists yc_v3.report_shares (
    report_id   bigint   not null references yc_v3.reports (id) on delete cascade,
    item_code   text     not null,
    account_id  bigint   not null references yc_v3.accounts (id),
    position    smallint not null,
    tenths      integer  not null,
    primary key (report_id, item_code, account_id),
    constraint report_shares_position_check check (position between 0 and 6),
    constraint report_shares_tenths_range_check check (tenths between 0 and 9999),
    constraint report_shares_position_once_key unique (report_id, item_code, position)
);

create table if not exists yc_v3.report_custom_shares (
    report_id   bigint   not null references yc_v3.reports (id) on delete cascade,
    account_id  bigint   not null references yc_v3.accounts (id),
    position    smallint not null,
    tenths      integer  not null,
    primary key (report_id, account_id),
    constraint report_custom_shares_position_check check (position between 0 and 6),
    constraint report_custom_shares_tenths_range_check check (tenths between 0 and 9999),
    constraint report_custom_shares_position_once_key unique (report_id, position)
);

-- 「某人在某期間的數量」（薪資的讀取函式）從帳戶出發
create index if not exists report_shares_account_idx on yc_v3.report_shares (account_id);
create index if not exists report_custom_shares_account_idx on yc_v3.report_custom_shares (account_id);
