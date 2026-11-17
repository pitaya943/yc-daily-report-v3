"""密碼變更與重設的規則（IAM-F06）。

- IAM-R30：改自己的密碼要輸入目前密碼與相符的確認（OWNER 也一樣，Q-053）。
- IAM-R31：管理員重設別人的密碼，不需要目前密碼。
- IAM-R32：沒有自助找回密碼——這裡**刻意沒有**任何「忘記密碼」的函式或端點（員工請管理員；owner 在系統外重設，Q-046）。

欄位驗證（附錄 B）全部在伺服器重做；缺少的值不補預設值：缺少或重複的欄位等同於不合格的值。
密碼與雜湊只經過 `app/core/session.py`（`hash_password`／`verify_password`），密碼怎麼雜湊只有一個定義（D-056）。
稽核（PASSWORD_CHANGE）只寫「誰改了誰的密碼」，不寫任何密碼或雜湊。
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Rule, authorize
from app.core.session import hash_password, verify_password
from app.modules.iam.password_change_and_reset import repo

# spec/appendix-b-fields.md「密碼」「密碼確認」「目前密碼」的錯誤字串，逐字照抄
MSG_CURRENT_WRONG = "目前密碼不正確"
MSG_CONFIRM_MISMATCH = "兩次輸入的密碼不一致"
MSG_LENGTH = "密碼長度須為 6 至 30 個字"

MIN_LENGTH = 6
MAX_LENGTH = 30

# ───────────────────────── 誰能重設誰（權限只寫在這一處）─────────────────────────
#
# IAM-R31：管理員（ADMIN 與擁有 ADMIN 全部權限的 OWNER）重設 USER 的密碼；USER 不行 → FORBIDDEN（並寫 ACCESS_DENIED）。
# T-304（D-115、IAM-R22）會在 `authorize_reset` 加上「只有 OWNER 能重設 ADMIN」；規則請改這個函式，不要散到端點裡。
RESET_RULE = Rule(roles={Role.ADMIN})


def authorize_reset(actor: Actor, target: repo.AccountRow | None = None) -> None:
    """通過就回傳；否則 UNAUTHENTICATED／FORBIDDEN。

    `target` 預設 None：第一步只看行為者的角色（還沒查目標，所以 USER 不會藉由 404 與 403 的差別探測哪些帳戶存在）；
    T-304 要依目標的角色判斷時，在查到目標之後再呼叫一次（傳入 target）。
    """
    authorize(actor, "reset a password", RESET_RULE)


class AccountNotFound(Exception):
    """沒有這個帳戶（規格沒有「找不到」的結果類別；router 回 404，D-106）。"""


@dataclass(frozen=True)
class ResetDone:
    account_name: str


# ───────────────────────── 欄位 ─────────────────────────


def _single(form: dict[str, list[str]], name: str) -> str | None:
    """欄位的唯一值；沒有這個欄位、或同名欄位重複，一律回傳 None（不挑其中一個、不補預設值）。"""
    values = form.get(name)
    if values is None or len(values) != 1:
        return None
    return values[0]


def validate_new_password(new: str | None) -> str:
    """密碼：任意字元，6–30 字（附錄 B）。長度以字元數（Unicode code point）計，不 strip：空白也是密碼的一部分。"""
    if new is None or not (MIN_LENGTH <= len(new) <= MAX_LENGTH):
        raise OutcomeError(Outcome.INVALID, MSG_LENGTH)
    return new


# ───────────────────────── IAM-R30 ─────────────────────────


def change_own_password(conn: psycopg.Connection, actor: Actor, form: dict[str, list[str]]) -> None:
    """改自己的密碼。檢查順序（規格不規定，D-104）：目前密碼 → 確認相符 → 長度。

    被拒絕時沒有任何資料被寫入：所有檢查都在寫入之前，錯誤在 transaction 提交之前丟出（連線關閉時回滾）。
    """
    current = _single(form, "current_password")
    new = _single(form, "new_password")
    confirm = _single(form, "password_confirm")

    stored = repo.lock_password_hash(conn, actor.id)
    if current is None or not verify_password(current, stored):  # 缺少目前密碼 = 不正確；verify_password 對沒有雜湊的帳戶也付同樣成本
        raise OutcomeError(Outcome.INVALID, MSG_CURRENT_WRONG)
    if new is not None and confirm != new:
        raise OutcomeError(Outcome.INVALID, MSG_CONFIRM_MISMATCH)
    validate_new_password(new)

    repo.set_password_hash(conn, actor.id, hash_password(new))
    audit.write(actor, "PASSWORD_CHANGE", "變更自己的密碼", conn=conn)
    conn.commit()


# ───────────────────────── IAM-R31 ─────────────────────────


def reset_password(conn: psycopg.Connection, actor: Actor, target_id: int, form: dict[str, list[str]]) -> ResetDone:
    """管理員重設別人的密碼（不需要目前密碼；重設沒有確認欄，規格的動作是「重設為 X」）。"""
    authorize_reset(actor)
    target = repo.find_account(conn, target_id)
    if target is None:
        raise AccountNotFound(target_id)
    authorize_reset(actor, target)  # T-304 在這裡加上依目標角色的判斷
    new = validate_new_password(_single(form, "new_password"))

    repo.lock_password_hash(conn, target.id)
    repo.set_password_hash(conn, target.id, hash_password(new))
    audit.write(actor, "PASSWORD_CHANGE", f"重設 {target.name} 的密碼", conn=conn)
    conn.commit()
    return ResetDone(account_name=target.name)
