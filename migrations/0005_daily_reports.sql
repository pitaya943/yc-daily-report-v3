-- 目的：日報的資料（RPT-F01 送出日報），並一次建好 T-202（編輯、刪除）與 T-203（歷史、匯出）需要的欄位，
--       因為它們不能新增 migration（同一時間只有一張 ticket 新增 migration）。
--       1. yc_v3.reports      一張回報。
--          * submitter_id     提交者（每日上限 RPT-R04 只算這個欄位；共同作業者不算）。
--          * report_date      回報日期，送出後不可改（AD-8）。
--          * catalogue        送出當時的工項組（AD-4）：之後帳戶改區域或大表旗標，既有回報不變。
--          * status           PENDING / CONFIRMED / REJECTED（spec/state-machines.md）；T-201 只寫 PENDING。
--          * custom_name / custom_tenths / custom_price
--                             自訂工項（REV-R20，每張回報最多一個；D-086）：名稱 1–100 字、數量（0.1 只的整數 0–9999）、
--                             單價（整數 ≥ 0）。check 約束要求三者同時為 null 或同時有值。T-201 不寫入。
--          * created_at / updated_at  帶時區；值來自 app/core/clock.py，不用資料庫的 now()。
--       2. yc_v3.report_items 每個工項的數量，以 0.1 只的整數（tenths）存：2.3 只 = 23。
--          只存「送出時有帶的」工項（空白送出存 0）；沒帶的工項沒有列，讀取端視為 0。
--       3. yc_v3.report_crew  共同作業者（不含提交者），position 是提交者選擇的順序（RPT-R05）。
--          一個人在同一張回報只能出現一次。
-- Ticket：T-201（migration 0005）。依賴 0001（yc_v3.accounts）。
-- 套用後檢查（預期 1 列，三個值都是 t）：
--   select to_regclass('yc_v3.reports') is not null as has_reports,
--          to_regclass('yc_v3.report_items') is not null as has_report_items,
--          to_regclass('yc_v3.report_crew') is not null as has_report_crew;
-- 回滾（只在還沒有真實資料、且 Kuei 同意時；會丟掉所有日報）：
--   drop table yc_v3.report_crew;
--   drop table yc_v3.report_items;
--   drop table yc_v3.reports;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0005'
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。
--
-- 設計說明：
--   * 每日上限（RPT-R04）在並行時也成立：靠應用程式在同一個 transaction 內先鎖住提交者的 accounts 列
--     （select ... for no key update）再計數、再寫入，同一個人的並行送出因此排隊。
--     這裡不用 trigger／函式（D-045 不允許），也不用 unique 約束（「最多 3 筆」不是唯一性）。
--   * report_items、report_crew 隨回報刪除（on delete cascade）：刪除回報（T-202）不留孤兒列。
--     reports.submitter_id 與 report_crew.account_id 不 cascade：帳戶只封存、不刪除（附錄 C 沒有 ACCOUNT_DELETE）。
--   * 數量欄位上限 9999（= 999.9 只），下限 0；金額（自訂工項單價）用整數。

create table if not exists yc_v3.reports (
    id             bigint generated always as identity primary key,
    submitter_id   bigint      not null references yc_v3.accounts (id),
    report_date    date        not null,
    catalogue      text        not null,
    status         text        not null,
    custom_name    text,
    custom_tenths  integer,
    custom_price   integer,
    created_at     timestamptz not null,
    updated_at     timestamptz not null,
    constraint reports_catalogue_check check (catalogue in ('WEST', 'SOUTH', 'BIG_METER')),
    constraint reports_status_check check (status in ('PENDING', 'CONFIRMED', 'REJECTED')),
    constraint reports_custom_name_length_check check (custom_name is null or char_length(custom_name) between 1 and 100),
    constraint reports_custom_tenths_range_check check (custom_tenths is null or custom_tenths between 0 and 9999),
    constraint reports_custom_price_check check (custom_price is null or custom_price >= 0),
    constraint reports_custom_item_all_or_none_check check (
        (custom_name is null and custom_tenths is null and custom_price is null)
        or (custom_name is not null and custom_tenths is not null and custom_price is not null)
    ),
    constraint reports_updated_after_created_check check (updated_at >= created_at)
);

-- 每日上限的計數（提交者 + 日期）與 T-203 的歷史查詢
create index if not exists reports_submitter_date_idx on yc_v3.reports (submitter_id, report_date);
create index if not exists reports_date_idx on yc_v3.reports (report_date);

create table if not exists yc_v3.report_items (
    report_id  bigint  not null references yc_v3.reports (id) on delete cascade,
    item_code  text    not null,
    tenths     integer not null,
    primary key (report_id, item_code),
    constraint report_items_tenths_range_check check (tenths between 0 and 9999)
);

create table if not exists yc_v3.report_crew (
    report_id   bigint   not null references yc_v3.reports (id) on delete cascade,
    position    smallint not null,
    account_id  bigint   not null references yc_v3.accounts (id),
    primary key (report_id, position),
    constraint report_crew_position_check check (position between 1 and 6),
    constraint report_crew_account_once_key unique (report_id, account_id)
);

-- 「我是共同作業者」的查詢（RPT-R04 的情境、T-203 的歷史）
create index if not exists report_crew_account_idx on yc_v3.report_crew (account_id);
