"""帳戶管理的權限判斷：這個 feature 的每個端點都經過 `authorize_account_action`，只有這一處。

為什麼集中：T-304（管理員管理）要加上「只有 OWNER 能新增、封存、復原、修改 ADMIN 帳戶」（D-115），
它只需要在這個函式內多看一眼 `target`（目標帳戶的角色），不必改動任何端點或 service。
`target` 現在還沒有用到，但每個會動到「某個帳戶」的呼叫都已經把它傳進來，之後不用再找呼叫端。

現在的規則（IAM-F04）：ADMIN 與 OWNER 可以管理帳戶；USER 一律 FORBIDDEN，並寫 `ACCESS_DENIED`（permissions.authorize）。
USER 讀別人的勞健保扣除額與未投保比例同樣走這裡（D-114：GET /accounts/{id} 也要通過這一關）。
"""
from __future__ import annotations

from app.core.actor import Actor
from app.core.permissions import Rule, authorize
from app.core.actor import Role

# OWNER 擁有 ADMIN 的全部權限（permissions._effective_roles），所以只列 ADMIN
MANAGE_ACCOUNTS = Rule(roles={Role.ADMIN})


def authorize_account_action(actor: Actor | None, action: str, target=None) -> None:
    """通過就回傳；否則丟 OutcomeError（FORBIDDEN，已寫 ACCESS_DENIED）。`target` 是被動到的帳戶（可為 None，例如清單與建立）。"""
    authorize(actor, action, MANAGE_ACCOUNTS)
