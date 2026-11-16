-- 目的：建立稽核紀錄表 yc_v3.audit_log（spec/appendix-c-audit-types.md）。
--       每列：台灣時間、行為者（帳戶或 SYSTEM）、類型、說明文字。類型限定為附錄 C 的 37 種。
-- Ticket：T-003（migration 0002）。依賴 0001（yc_v3.accounts，D-037）。
-- 套用後檢查（預期 1 列，值為 t；表存在且類型的 check 約束有 37 個類型）：
--   select to_regclass('yc_v3.audit_log') is not null;
-- 回滾（只在還沒有資料、且 Kuei 同意時；稽核紀錄是永久保存的，有資料就不要回滾）：
--   drop table yc_v3.audit_log;   -- 然後從 yc_v3.schema_migrations 刪掉 version = '0002'
-- 只碰 yc_v3；可重複執行（IF NOT EXISTS）。
--
-- 設計說明：
--   * actor_account_id 指向 accounts（SYSTEM 時為 null）；actor_name 另存一份名字，
--     因為稽核是歷史紀錄，不應隨帳戶資料而變。
--   * 不放「禁止修改或刪除」的觸發器：AUD-R13 屬於 AUD-F02 的 ticket，不在 T-003 範圍。
--   * occurred_at 存帶時區的時間；寫入的值來自 app/core/clock.py（Asia/Taipei），不用資料庫的 now()。

create table if not exists yc_v3.audit_log (
    id                bigint generated always as identity primary key,
    occurred_at       timestamptz not null,
    actor_account_id  bigint references yc_v3.accounts (id),
    actor_name        text not null,
    type              text not null,
    description       text not null,
    constraint audit_log_type_check check (type in (
        'REPORT_CREATE', 'REPORT_UPDATE', 'REPORT_DELETE', 'REPORT_CONFIRM', 'REPORT_REJECT', 'REPORT_UNCONFIRM',
        'ACCOUNT_CREATE', 'ACCOUNT_UPDATE', 'ACCOUNT_ARCHIVE', 'ACCOUNT_RESTORE', 'ACCOUNT_ROLE_CHANGE',
        'ACCOUNT_LOCKOUT', 'PASSWORD_CHANGE', 'BANK_REVEAL',
        'MATERIAL_REQUEST', 'MATERIAL_CANCEL', 'MATERIAL_ADD', 'MATERIAL_UPDATE', 'MATERIAL_DELETE',
        'MATERIAL_APPROVE', 'MATERIAL_REJECT', 'MATERIAL_IMPORT', 'MATERIAL_RESET', 'MATERIAL_KEEP_A',
        'MATERIAL_SYNC_B',
        'SYSTEM_CONFIG', 'RETENTION_SET', 'RETENTION_RESET', 'RETENTION_YEAR_END',
        'LEDGER_CREATE', 'LEDGER_UPDATE', 'LEDGER_DELETE', 'LEDGER_SETTLE', 'LEDGER_VOID',
        'EXPORT', 'FILE_DOWNLOAD', 'ACCESS_DENIED'
    )),
    -- 沒有帳戶的行為者只能是 SYSTEM
    constraint audit_log_actor_check check (actor_account_id is not null or actor_name = 'SYSTEM')
);

-- 稽核頁依時間與行為者篩選（AUD-R12）
create index if not exists audit_log_occurred_at_idx on yc_v3.audit_log (occurred_at);
create index if not exists audit_log_actor_idx on yc_v3.audit_log (actor_account_id);
