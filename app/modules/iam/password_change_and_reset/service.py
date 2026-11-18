"""密碼變更與重設的規則（IAM-F06）。

- IAM-R30：改自己的密碼要輸入目前密碼與相符的確認（OWNER 也一樣，Q-053）。
- IAM-R31：管理員重設別人的密碼，不需要目前密碼。
- IAM-R32：沒有自助找回密碼——這裡**刻意沒有**任何「忘記密碼」的函式或端點（員工請管理員；owner 在系統外重設，Q-046）。

- IAM-R33（D-123）：自己改密碼成功後，結束同一個帳戶的**其他** session，目前這個保留；被管理員重設後，該帳戶**全部**的 session 結束。
  只動那個帳戶的 session；與密碼寫入、稽核在同一個交易，同生同死。
- IAM-R34（D-124）：改密碼時輸入錯誤的目前密碼，與登入共用同一份失敗計數與鎖定（呼叫 `sign_in_lockout_and_rate_limit.service`
  既有的 `ensure_not_locked`、`record_failure`、`hold_not_locked`，這裡不另寫一份）。鎖定期間改密碼 `LOCKED`；不計入來源位址的頻率限制。

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
from app.core.session import _token_hash as session_token_hash  # 見 change_own_password：session.py 不在這張 ticket 的範圍內
from app.modules.iam.password_change_and_reset import repo
from app.modules.iam.sign_in_lockout_and_rate_limit import service as lockout

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


def change_own_password(conn: psycopg.Connection, actor: Actor, form: dict[str, list[str]], session_token: str) -> None:
    """改自己的密碼。`session_token` 是目前這個 session 的憑證：成功後保留它，結束同帳戶的其他 session（IAM-R33）。

    檢查順序（規格不規定，D-104）：鎖定 → 目前密碼 → 確認相符 → 長度。
    - 鎖定中一律 `LOCKED`，連正確的目前密碼也是；不寫任何東西（與登入相同）。
    - 目前密碼錯誤：記一次失敗（與登入共用，IAM-R34）；第 5 次同時鎖定並寫 ACCOUNT_LOCKOUT，回應 `LOCKED`，否則 `INVALID`。
      這是這個端點唯一會寫資料的拒絕。缺少或重複的 `current_password` 欄位是格式不合、不是一次密碼嘗試，
      與登入的 INVALID 相同（D-077）：回 `INVALID`、不計入、不寫資料。
    - 目前密碼正確**不**重置失敗次數（IAM-R05 只有登入成功、鎖定結束、15 分鐘沒有失敗才重置）。
    - 其餘被拒絕（確認不符、長度不合）沒有任何資料被寫入：錯誤在 transaction 提交之前丟出（連線關閉時回滾）。
    """
    current = _single(form, "current_password")
    new = _single(form, "new_password")
    confirm = _single(form, "password_confirm")

    lockout.ensure_not_locked(conn, actor.id)  # 只讀；LOCKED 時不做 scrypt、不寫東西
    stored = repo.lock_password_hash(conn, actor.id)
    if current is None:
        raise OutcomeError(Outcome.INVALID, MSG_CURRENT_WRONG)
    if not verify_password(current, stored):
        lockout.record_failure(conn, actor.id, actor.name)  # 提交失敗次數（與登入同一份）；第 5 次丟 LOCKED
        raise OutcomeError(Outcome.INVALID, MSG_CURRENT_WRONG)
    if new is not None and confirm != new:
        raise OutcomeError(Outcome.INVALID, MSG_CONFIRM_MISMATCH)
    validate_new_password(new)
    lockout.hold_not_locked(conn, actor.id)  # 驗證期間別的 worker 可能剛鎖定了這個帳戶：這次寫入不能算數

    repo.set_password_hash(conn, actor.id, hash_password(new))
    # 目前的憑證 → 雜湊用 session.py 的同一個定義（session.py 不在這張 ticket 的範圍內，所以取它的內部函式；
    # PR 說明提議在 session.py 加公開的 `end_other_sessions`，之後這裡就不必碰底線開頭的名稱）
    repo.end_other_sessions(conn, actor.id, session_token_hash(session_token))
    audit.write(actor, "PASSWORD_CHANGE", "變更自己的密碼", conn=conn)
    conn.commit()


# ───────────────────────── IAM-R31 ─────────────────────────


def reset_password(conn: psycopg.Connection, actor: Actor, target_id: int, form: dict[str, list[str]]) -> ResetDone:
    """管理員重設別人的密碼（不需要目前密碼；要有確認欄，D-127）。"""
    authorize_reset(actor)
    target = repo.find_account(conn, target_id)
    if target is None:
        raise AccountNotFound(target_id)
    authorize_reset(actor, target)  # T-304 在這裡加上依目標角色的判斷
    new = _single(form, "new_password")
    confirm = _single(form, "password_confirm")
    if new is not None and confirm != new:  # D-127：重設也有確認欄；缺少、為空、不一致都是同一句（順序與自己改密碼相同：確認 → 長度）
        raise OutcomeError(Outcome.INVALID, MSG_CONFIRM_MISMATCH)
    new = validate_new_password(new)

    repo.lock_password_hash(conn, target.id)
    repo.set_password_hash(conn, target.id, hash_password(new))
    repo.end_all_sessions(conn, target.id)  # IAM-R33：被重設的帳戶全部的 session 結束；管理員自己的 session 不受影響
    audit.write(actor, "PASSWORD_CHANGE", f"重設 {target.name} 的密碼", conn=conn)
    conn.commit()
    return ResetDone(account_name=target.name)
