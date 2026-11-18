"""「誰能動誰」：IAM-R20、R22 的權限表，只寫在這一處（D-115）。

帳戶管理（account_lifecycle_and_pay_settings）與密碼重設（password_change_and_reset）都 import 這裡的函式，
不各自寫一份；新增、封存、復原、改區域、重設密碼的端點只要在「查到目標之後」呼叫 `authorize_on_target`。

規則（IAM-R20）：
- 對象是 USER：ADMIN 與 OWNER 都可以（OWNER 擁有 ADMIN 的全部權限，permissions._effective_roles）。
- 對象是 ADMIN 或 OWNER：只有 OWNER。ADMIN 對 ADMIN（含自己）與對 OWNER 一律 FORBIDDEN，並寫 `ACCESS_DENIED`。
- 不認得的角色：fail-closed，同「對象是 ADMIN 或 OWNER」。

OWNER 的密碼不在這張表內處理（D-122）：系統內沒有人能用管理員重設端點重設 OWNER 的密碼（`NOBODY`），
所以 password_change_and_reset 對 OWNER 對象另外判斷；其他動作對 OWNER 對象（改自己的區域）仍由 OWNER 自己進行。
"""
from __future__ import annotations

from app.core.actor import Actor, Role
from app.core.permissions import Rule, authorize

ADMIN_AND_UP = Rule(roles={Role.ADMIN})  # OWNER 也通過
OWNER_ONLY = Rule(roles={Role.OWNER})
NOBODY = Rule(roles=set())  # 沒有任何角色能通過：用在「沒有這個動作」的 FORBIDDEN 一側


def rule_for_target(target_role: str) -> Rule:
    """動這個角色的帳戶要符合的規則（IAM-R20）。"""
    return ADMIN_AND_UP if target_role == Role.USER.value else OWNER_ONLY


def authorize_on_target(actor: Actor | None, action: str, target_role: str) -> None:
    """通過就回傳；否則 FORBIDDEN 並寫 `ACCESS_DENIED`。`action` 是稽核說明用的人類可讀字串。"""
    authorize(actor, action, rule_for_target(target_role))
