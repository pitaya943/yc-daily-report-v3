"""帳戶生命週期與薪資設定的規則（IAM-R13、R15～R19）。

    create_account(conn, actor, form)        IAM-R13
    update_account(conn, actor, id, form)    IAM-R15（勞健保、固定薪資）、IAM-R16（區域、大表旗標）
    archive_account / restore_account        IAM-R17、R18（AD-13）

規則：
- 權限先判斷（access.py），欄位驗證在後：沒有權限的人只會得到 FORBIDDEN，不會因為內容而探到欄位規則。
- 伺服器重新驗證每個欄位；缺少的值不以預設值補上。唯一的例外是附錄 B 明寫「預設」的欄位：
  大表旗標（預設關），而且只在**建立**時；薪資設定的初始值由資料庫欄位的 default 提供（D-116），不由這裡補。
- 驗證全部通過才寫入；寫入與稽核在同一個 transaction，成功才一起提交。拒絕時除了 ACCESS_DENIED 之外什麼都不寫。
- 錯誤字串逐字出自 spec/appendix-b-fields.md；規格沒有寫字串的拒絕，message 為 None（不替規格發明字串）。
- 金額與比例都是整數：扣除額、固定薪資是 NTD 整數；比例存成「萬分之一」的整數（5 % → 500），
  解析時只用字串與整數運算，不經過浮點數。
"""
from __future__ import annotations

import re

import psycopg

from app.core import audit
from app.core.actor import Actor
from app.core.outcomes import Outcome, OutcomeError
from app.core.session import hash_password
from app.modules.iam.account_lifecycle_and_pay_settings import repo
from app.modules.iam.account_lifecycle_and_pay_settings.access import authorize_account_action

MSG_NAME_EMPTY = "請輸入顯示名稱"
MSG_NAME_TOO_LONG = "顯示名稱最多 50 個字"
MSG_NAME_TAKEN = "此顯示名稱已被使用"
MSG_PASSWORD = "密碼長度須為 6 至 30 個字"
MSG_PASSWORD_MISMATCH = "兩次輸入的密碼不一致"
MSG_ZONE = "請選擇施工區域"
MSG_ROLE = "請選擇角色"
MSG_BIG_METER = "請確認是否為大表帳戶"
MSG_DEDUCTION = "勞健保扣除額須為 0 或正整數"
MSG_DEDUCTION_MIN = "已投保時，扣除額須至少為 1"
MSG_RATE = "未投保扣除比例須為 0 到 100 之間，最多兩位小數"
MSG_FIXED_SALARY = "固定薪資須為 0 或正整數"

ZONES = ("WEST", "SOUTH")
_INT_MAX = 2**31 - 1  # 資料庫欄位是 integer；超過的值當成不合法，而不是讓資料庫丟出 500
_DIGITS = re.compile(r"[0-9]+")
_SIGNED = re.compile(r"-?[0-9]+")
_RATE = re.compile(r"([0-9]{1,3})(?:\.([0-9]{1,2}))?")


class AccountNotFound(Exception):
    """沒有這個帳戶（規格沒有「找不到」的結果類別；router 回 404，D-106）。"""


def _field(form: dict[str, list[str]], key: str) -> str | None:
    """同名欄位取最後一個；沒有送這個欄位回傳 None（與「送了空白」不同）。"""
    values = form.get(key)
    return values[-1] if values else None


def _flag(value: str | None) -> bool | None:
    """on／off → True／False；其他（含沒送）→ None，由呼叫端以該欄位的字串拒絕。"""
    return {"on": True, "off": False}.get(value) if value is not None else None


def load_authorized(conn: psycopg.Connection, actor: Actor, account_id: int, action: str, *, lock: bool = True) -> repo.Account:
    """先判斷「這個人能不能做這件事」（沒有權限的人不能靠 404 與否探到帳戶是否存在），再讀帳戶，再針對這個帳戶判斷一次。"""
    authorize_account_action(actor, action)
    account = repo.get(conn, account_id, lock=lock)
    if account is None:
        raise AccountNotFound(account_id)
    authorize_account_action(actor, action, account)  # T-304 在 access.py 加「只有 OWNER 能動 ADMIN」時，這一行就會生效
    return account


# ───────────────────────── 欄位驗證（純函式，字串進、整數出） ─────────────────────────


def parse_deduction_for_enrolled(value: str | None) -> int:
    if value is None or not _SIGNED.fullmatch(value):
        raise OutcomeError(Outcome.INVALID, MSG_DEDUCTION)
    number = int(value)
    if number < 0 or number > _INT_MAX:
        raise OutcomeError(Outcome.INVALID, MSG_DEDUCTION)
    if number < 1:
        raise OutcomeError(Outcome.INVALID, MSG_DEDUCTION_MIN)
    return number


def parse_rate_bp(value: str | None) -> int | None:
    """空白 → None（用區域比例）；0–100、最多兩位小數 → 萬分之一的整數；其他 → INVALID。沒送這個欄位也是 INVALID。"""
    if value is None:
        raise OutcomeError(Outcome.INVALID, MSG_RATE)
    if value == "":
        return None
    m = _RATE.fullmatch(value)
    if m is None:
        raise OutcomeError(Outcome.INVALID, MSG_RATE)
    bp = int(m.group(1)) * 100 + int((m.group(2) or "").ljust(2, "0") or 0)
    if bp > 10000:
        raise OutcomeError(Outcome.INVALID, MSG_RATE)
    return bp


def parse_fixed_salary(value: str | None) -> int:
    if value is None or not _DIGITS.fullmatch(value) or int(value) > _INT_MAX:
        raise OutcomeError(Outcome.INVALID, MSG_FIXED_SALARY)
    return int(value)


# ───────────────────────── IAM-R13 建立 ─────────────────────────


def create_account(conn: psycopg.Connection, actor: Actor, form: dict[str, list[str]]) -> int:
    authorize_account_action(actor, "create an account")
    # D-139：先去掉前後空白（str.strip 含全形空白 U+3000），再檢查空白、長度與重複；存的也是去掉後的名字
    name = (_field(form, "name") or "").strip()
    if not name:
        raise OutcomeError(Outcome.INVALID, MSG_NAME_EMPTY)
    if len(name) > 50:
        raise OutcomeError(Outcome.INVALID, MSG_NAME_TOO_LONG)
    password = _field(form, "password") or ""
    if not 6 <= len(password) <= 30:
        raise OutcomeError(Outcome.INVALID, MSG_PASSWORD)
    # D-127：確認欄缺少視同不一致（不以預設值補上）；逐字比對，不去空白、不分大小寫
    if _field(form, "password_confirm") != password:
        raise OutcomeError(Outcome.INVALID, MSG_PASSWORD_MISMATCH)
    zone = _field(form, "zone")
    if zone not in ZONES:
        raise OutcomeError(Outcome.INVALID, MSG_ZONE)
    # 這個頁面只建立 USER；ADMIN 帳戶在管理員管理頁（T-304，D-115），OWNER 不能選
    if _field(form, "role") != "USER":
        raise OutcomeError(Outcome.INVALID, MSG_ROLE)
    big_meter_raw = _field(form, "big_meter")
    big_meter = False if big_meter_raw is None else _flag(big_meter_raw)  # 附錄 B：建立時預設關
    if big_meter is None:
        raise OutcomeError(Outcome.INVALID, MSG_BIG_METER)
    if repo.name_exists(conn, name):
        raise OutcomeError(Outcome.INVALID, MSG_NAME_TAKEN)
    try:
        account_id = repo.insert(conn, name=name, role="USER", zone=zone, big_meter=big_meter, password_hash=hash_password(password))
    except psycopg.errors.UniqueViolation:  # 兩個人同時建同一個名字：資料庫的唯一約束是最後一道
        conn.rollback()
        raise OutcomeError(Outcome.INVALID, MSG_NAME_TAKEN) from None
    audit.write(actor, "ACCOUNT_CREATE", f"建立帳戶 {name}（USER、{zone}、大表{'開' if big_meter else '關'}）", conn=conn)
    conn.commit()
    return account_id


# ───────────────────────── IAM-R15、R16 修改 ─────────────────────────


def _insurance_label(a: repo.Account) -> str:
    if a.insured:
        return f"已投保（扣除額 {a.insurance_deduction}）"
    if a.uninsured_exempt:
        return "未投保、免扣"
    rate = "區域比例" if a.uninsured_rate_bp is None else f"{format_rate(a.uninsured_rate_bp)}%"
    return f"未投保（{rate}）"


def format_rate(bp: int) -> str:
    """萬分之一的整數 → 顯示用的百分比字串（500 → "5"、325 → "3.25"、50 → "0.5"）。"""
    whole, frac = divmod(bp, 100)
    return str(whole) if frac == 0 else f"{whole}.{frac:02d}".rstrip("0")


def update_account(conn: psycopg.Connection, actor: Actor, account_id: int, form: dict[str, list[str]]) -> bool:
    """回傳是否真的有改變（值都相同時不寫、不稽核，仍算接受）。"""
    target = load_authorized(conn, actor, account_id, "update an account")
    changes: dict[str, object] = {}
    notes: list[str] = []

    zone = _field(form, "zone")
    if zone is not None:
        if zone not in ZONES:
            raise OutcomeError(Outcome.INVALID, MSG_ZONE)
        if zone != target.zone:
            changes["zone"] = zone
            notes.append(f"區域 {target.zone} → {zone}")

    big_meter = _field(form, "big_meter")
    if big_meter is not None:
        value = _flag(big_meter)
        if value is None:
            raise OutcomeError(Outcome.INVALID, MSG_BIG_METER)
        if target.role != "USER":  # IAM-R16：大表旗標只適用 USER；規格沒有為這個拒絕寫字串
            raise OutcomeError(Outcome.INVALID)
        if value != target.big_meter:
            changes["big_meter"] = value
            notes.append(f"大表旗標 {'開' if target.big_meter else '關'} → {'開' if value else '關'}")

    choice = _field(form, "insurance")
    if choice is not None:
        if choice == "enrolled":
            new = {"insured": True, "insurance_deduction": parse_deduction_for_enrolled(_field(form, "deduction")), "uninsured_exempt": False}
        elif choice == "not_enrolled_rate":
            new = {"insured": False, "insurance_deduction": 0, "uninsured_exempt": False, "uninsured_rate_bp": parse_rate_bp(_field(form, "rate"))}
        elif choice == "not_enrolled_exempt":
            new = {"insured": False, "insurance_deduction": 0, "uninsured_exempt": True}
        else:
            raise OutcomeError(Outcome.INVALID)  # 不認得的選項：規格沒有字串
        before = _insurance_label(target)
        merged = repo.Account(**{**target.__dict__, **new})
        after = _insurance_label(merged)
        diff = {k: v for k, v in new.items() if getattr(target, k) != v}
        if diff:
            changes.update(diff)
            notes.append(f"勞健保設定 {before} → {after}")

    fixed_salary = _field(form, "fixed_salary")
    if fixed_salary is not None:
        value = parse_fixed_salary(fixed_salary)
        if value != target.fixed_salary:
            changes["fixed_salary"] = value
            notes.append(f"固定薪資 {target.fixed_salary} → {value}")

    if not any(k in form for k in ("zone", "big_meter", "insurance", "fixed_salary")):
        raise OutcomeError(Outcome.INVALID)  # 什麼欄位都沒送：不是「沒有變動」，而是壞請求
    if not changes:
        return False
    repo.update(conn, account_id, changes)
    audit.write(actor, "ACCOUNT_UPDATE", f"修改帳戶 {target.name}：{'；'.join(notes)}", conn=conn)
    conn.commit()
    return True


# ───────────────────────── IAM-R17、R18 封存與復原 ─────────────────────────


def archive_account(conn: psycopg.Connection, actor: Actor, account_id: int) -> repo.Account:
    target = load_authorized(conn, actor, account_id, "archive an account")
    if target.archived:
        raise OutcomeError(Outcome.CONFLICT)  # 資料合法但狀態不允許；規格沒有字串
    repo.set_archived(conn, account_id, True)
    repo.delete_sessions(conn, account_id)  # AD-13：現有的 session 立即失效；也避免之後復原時舊 cookie 又活過來
    audit.write(actor, "ACCOUNT_ARCHIVE", f"封存帳戶 {target.name}", conn=conn)
    conn.commit()
    return target


def restore_account(conn: psycopg.Connection, actor: Actor, account_id: int) -> repo.Account:
    target = load_authorized(conn, actor, account_id, "restore an account")
    if not target.archived:
        raise OutcomeError(Outcome.CONFLICT)
    repo.set_archived(conn, account_id, False)
    audit.write(actor, "ACCOUNT_RESTORE", f"復原帳戶 {target.name}", conn=conn)
    conn.commit()
    return target
