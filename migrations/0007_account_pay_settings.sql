-- 目的：帳戶的薪資設定（IAM-F04：勞健保、未投保比例、固定薪資），給 T-303 的帳戶管理頁讀寫，
--       也是之後薪資計算（PAY 系列）要讀的輸入。全部加在 yc_v3.accounts 上，一個帳戶一組設定。
--       * insured                          是否已投保（IAM-R15 三選一的第一個維度）。
--       * insurance_deduction              勞健保扣除額，整數 NTD；未投保為 0，已投保至少 1。
--       * uninsured_rate_bp                個人未投保扣除比例，以「萬分之一」的整數存：5 % = 500、3.25 % = 325。
--                                          null 表示空白，用區域比例（附錄 B「未投保扣除比例」）。
--                                          不用浮點數、也不用 numeric：比例要乘上金額，整數可以用精確的整數運算。
--       * uninsured_exempt                 未投保免扣旗標。
--       * fixed_salary                     固定薪資，整數 NTD ≥ 0。
--       * pays_fixed_salary_every_period   每期發放固定薪資旗標。
--       不包含銀行帳號與發薪方式：那是 T-306 的（D-113）。
-- 初始值（D-116）：扣除額 0、未投保、個人比例空白、免扣關、固定薪資 0、每期發放關。
--       欄位的 default 就是這組初始值，而且 `add column ... default` 會把它寫進「既有的帳戶」，
--       所以不必另外 update；日後建立帳戶時不送這些欄位，也得到同樣的值。
-- Ticket：T-303（migration 0007）。依賴 0001（yc_v3.accounts）。
-- 套用後檢查（預期 1 列，值為 t；表示六個欄位都在，而且沒有任何帳戶偏離初始值）：
--   select (select count(*) from information_schema.columns
--            where table_schema = 'yc_v3' and table_name = 'accounts'
--              and column_name in ('insured', 'insurance_deduction', 'uninsured_rate_bp',
--                                  'uninsured_exempt', 'fixed_salary', 'pays_fixed_salary_every_period')) = 6
--          and (select count(*) from yc_v3.accounts
--                where insured or insurance_deduction <> 0 or uninsured_rate_bp is not null
--                   or uninsured_exempt or fixed_salary <> 0 or pays_fixed_salary_every_period) = 0;
--   （套用後若已有人用帳戶管理頁改過設定，第二個條件會是 f；那是正常的，不代表 migration 有問題。）
-- 回滾（只在 Kuei 同意時；會丟掉所有帳戶已設定的勞健保、未投保比例與固定薪資）：
--   alter table yc_v3.accounts
--       drop column pays_fixed_salary_every_period,
--       drop column fixed_salary,
--       drop column uninsured_exempt,
--       drop column uninsured_rate_bp,
--       drop column insurance_deduction,
--       drop column insured;
--   然後從 yc_v3.schema_migrations 刪掉 version = '0007'。
-- 只碰 yc_v3；可重複執行（`add column if not exists`：欄位已存在時整句略過，欄位上的約束也一併略過）。
--
-- 設計說明：
--   * 「未投保為 0、已投保至少 1」寫成資料庫約束（accounts_insurance_deduction_check）：
--     應用程式的驗證是第一道，資料庫是最後一道防線。PostgreSQL 允許欄位層級的 check 參照同一列的其他欄位，
--     所以約束直接寫在欄位定義上：欄位已存在時整句略過，可重複執行，也不需要 drop（add-migration：不 DROP；D-045：不用 DO 區塊）。
--   * 比例的範圍 0–10000（0 %–100 %）；兩位小數由「萬分之一整數」自然保證，不必另外檢查。

alter table yc_v3.accounts
    add column if not exists insured boolean not null default false,
    add column if not exists insurance_deduction integer not null default 0
        constraint accounts_insurance_deduction_check
        check ((insured and insurance_deduction >= 1) or (not insured and insurance_deduction = 0)),
    add column if not exists uninsured_rate_bp integer
        constraint accounts_uninsured_rate_bp_check check (uninsured_rate_bp is null or uninsured_rate_bp between 0 and 10000),
    add column if not exists uninsured_exempt boolean not null default false,
    add column if not exists fixed_salary integer not null default 0
        constraint accounts_fixed_salary_check check (fixed_salary >= 0),
    add column if not exists pays_fixed_salary_every_period boolean not null default false;
