"""銀行帳號遮罩與顯示（IAM-R40、R41、R43）與銀行帳號、發薪方式的設定（IAM-R14）。

    show_masked(conn, actor, id)       IAM-R40  預設只顯示末四碼，不寫稽核
    reveal(conn, actor, id)            IAM-R41  顯示全碼，寫 BANK_REVEAL
    set_bank_number(conn, actor, id, form)     IAM-R14（格式）、IAM-R43（沒有金鑰不能改）
    set_payment_method(conn, actor, id, form)  IAM-R14（改為轉帳前須有帳號）

規則：
- 權限先判斷，欄位驗證在後；沒有權限的人只會得到 FORBIDDEN（並寫 ACCESS_DENIED），不會因為內容探到欄位規則。
  查看與顯示：持有人自己或管理員（OWNER 含在內）；USER 看別人的 → FORBIDDEN（D-114，IAM-R42 的把關在 T-406 轉綠）。
  設定：只有帳戶管理的權限（access.py 的 `authorize_account_action`；T-304 在那裡加「只有 OWNER 能動 ADMIN」時，這裡自動生效）。
- 沒有金鑰（或格式不對）時：查看顯示「無法讀取」；設定 → BLOCKED。其他功能完全不碰這個模組，所以照常運作（IAM-R43）。
- 沒有東西可以顯示時不寫 `BANK_REVEAL`：稽核記的是「顯示了全碼」，沒有顯示就沒有紀錄。
- 全碼只存在於這個函式的區域變數與回應內文：不寫進稽核說明、不寫進紀錄、不回傳給呼叫端以外的地方。
- 驗證全部通過才寫入；寫入與稽核在同一個 transaction，成功才一起提交。
- 錯誤字串逐字出自 spec/appendix-b-fields.md。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Resource, Rule, authorize
from app.modules.iam.account_lifecycle_and_pay_settings.access import authorize_account_action
from app.modules.iam.bank_number_masking_and_reveal import crypto, repo

MSG_BANK_FORMAT = "銀行帳號須為 14 位數字（3 位分行＋11 位帳號）"
MSG_BANK_BLOCKED = "銀行帳號目前無法讀取，無法修改"
MSG_METHOD = "請選擇發薪方式"
MSG_NEED_BANK_NUMBER = "請先設定銀行帳號再改為轉帳"

UNREADABLE = "無法讀取"  # IAM-R43：沒有金鑰（或解不開）時顯示的值
NOT_SET = "尚未設定"  # 規格沒有為「還沒有銀行帳號」寫字串；這是顯示用文字，沒有 scenario 斷言它
PAYMENT_METHODS = ("TRANSFER", "CASH")
_BANK_NUMBER = re.compile(r"[0-9]{14}")  # [0-9]：不是 \d（\d 也吃全形與其他文字的數字）；fullmatch：不容許結尾換行

# 持有人自己，或管理員（OWNER 擁有 ADMIN 的全部權限，permissions._effective_roles）
_ADMIN = Rule(roles={Role.ADMIN})
_HOLDER = Rule(roles={Role.USER}, owner_only=True)


class AccountNotFound(Exception):
    """沒有這個帳戶（規格沒有「找不到」的結果類別；router 回 404，D-106）。"""


@dataclass(frozen=True)
class Shown:
    state: str  # masked／revealed／unreadable／unset
    text: str  # 畫面上顯示的值


def _field(form: dict[str, list[str]], key: str) -> str | None:
    """同名欄位取最後一個；沒有送這個欄位回傳 None（與「送了空白」不同）。"""
    values = form.get(key)
    return values[-1] if values else None


def mask(number: str) -> str:
    """只留末四碼；其餘位數換成 `*`（不留任何其他數字）。"""
    return "*" * (len(number) - 4) + number[-4:]


def _load_for_read(conn: psycopg.Connection, actor: Actor, account_id: int, action: str) -> repo.Holder:
    """持有人或管理員。先判斷權限，再讀帳戶：沒有權限的人不能靠 404 與否探到帳戶是否存在。"""
    authorize(actor, action, _ADMIN, _HOLDER, resource=Resource(owner_id=account_id))
    holder = repo.get(conn, account_id)
    if holder is None:
        raise AccountNotFound(account_id)
    return holder


def _load_for_write(conn: psycopg.Connection, actor: Actor, account_id: int, action: str) -> repo.Holder:
    authorize_account_action(actor, action)
    holder = repo.get(conn, account_id, lock=True)
    if holder is None:
        raise AccountNotFound(account_id)
    authorize_account_action(actor, action, holder)
    return holder


def _readable(holder: repo.Holder) -> str | None:
    """解開密文；沒有金鑰、金鑰不對、密文被改過都回傳 None（呼叫端一律顯示「無法讀取」）。"""
    key = crypto.load_key()
    if key is None or holder.bank_number_cipher is None:
        return None
    try:
        return crypto.decrypt(key, holder.bank_number_cipher, crypto.aad_for(holder.id))
    except crypto.Unreadable:
        return None


def show_masked(conn: psycopg.Connection, actor: Actor, account_id: int) -> tuple[repo.Holder, Shown]:
    """IAM-R40：預設只顯示末四碼。不寫稽核，也不寫任何其他東西。"""
    holder = _load_for_read(conn, actor, account_id, "view a bank number")
    if holder.bank_number_cipher is None:
        return holder, Shown("unset", NOT_SET)
    number = _readable(holder)
    if number is None:
        return holder, Shown("unreadable", UNREADABLE)
    return holder, Shown("masked", mask(number))


def reveal(conn: psycopg.Connection, actor: Actor, account_id: int) -> tuple[repo.Holder, Shown]:
    """IAM-R41：顯示全碼，並寫 BANK_REVEAL。稽核與回應同生同死：稽核寫不進去就不顯示。"""
    holder = _load_for_read(conn, actor, account_id, "reveal a bank number")
    if holder.bank_number_cipher is None:
        return holder, Shown("unset", NOT_SET)
    number = _readable(holder)
    if number is None:
        return holder, Shown("unreadable", UNREADABLE)
    audit.write(actor, "BANK_REVEAL", f"顯示 {holder.name} 的銀行帳號全碼", conn=conn)  # 說明只點名是誰的，不含任何位數
    conn.commit()
    return holder, Shown("revealed", number)


def parse_bank_number(value: str | None) -> str:
    """去掉 `-` 後必須剛好 14 位數字；其他（含沒送、空白、前後空白）→ INVALID。"""
    if value is None or _BANK_NUMBER.fullmatch(value.replace("-", "")) is None:
        raise OutcomeError(Outcome.INVALID, MSG_BANK_FORMAT)
    return value.replace("-", "")


def set_bank_number(conn: psycopg.Connection, actor: Actor, account_id: int, form: dict[str, list[str]]) -> None:
    holder = _load_for_write(conn, actor, account_id, "set a bank number")
    number = parse_bank_number(_field(form, "bank_number"))
    key = crypto.load_key()
    if key is None:
        raise OutcomeError(Outcome.BLOCKED, MSG_BANK_BLOCKED)  # IAM-R43：沒有金鑰就不存（更不會存明文）
    repo.set_cipher(conn, account_id, crypto.encrypt(key, number, crypto.aad_for(account_id)))
    audit.write(actor, "ACCOUNT_UPDATE", f"修改帳戶 {holder.name}：銀行帳號已更新", conn=conn)  # 不含任何位數
    conn.commit()


def set_payment_method(conn: psycopg.Connection, actor: Actor, account_id: int, form: dict[str, list[str]]) -> bool:
    """回傳是否真的有改變（值相同時不寫、不稽核，仍算接受）。"""
    holder = _load_for_write(conn, actor, account_id, "set a payment method")
    method = _field(form, "payment_method")
    if method not in PAYMENT_METHODS:
        raise OutcomeError(Outcome.INVALID, MSG_METHOD)
    if method == "TRANSFER" and holder.bank_number_cipher is None:
        raise OutcomeError(Outcome.CONFLICT, MSG_NEED_BANK_NUMBER)
    if method == holder.payment_method:
        return False
    repo.set_payment_method(conn, account_id, method)
    audit.write(actor, "ACCOUNT_UPDATE", f"修改帳戶 {holder.name}：發薪方式 {holder.payment_method} → {method}", conn=conn)
    conn.commit()
    return True
