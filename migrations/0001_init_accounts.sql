-- 目的：建立 yc_v3 schema 與 accounts 表，讓測試框架能載入 spec/background.md 的固定帳戶。
--       只放 background 需要的欄位；密碼、session、稽核等由後續 ticket 的 migration 新增。
-- Ticket：T-001（migration 0001）
-- 套用後檢查（預期 1 列，值為 t）：
--   select to_regclass('yc_v3.accounts') is not null;
-- 回滾（只在還沒有資料、且 Kuei 同意時）：
--   drop table yc_v3.accounts;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0001'
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。

create schema if not exists yc_v3;

create table if not exists yc_v3.accounts (
    id         bigint generated always as identity primary key,
    name       text    not null,
    role       text    not null check (role in ('OWNER', 'ADMIN', 'USER')),
    zone       text    not null check (zone in ('WEST', 'SOUTH')),
    big_meter  boolean not null default false,
    archived   boolean not null default false,
    constraint accounts_name_key unique (name)
);
