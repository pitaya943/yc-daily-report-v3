"""帳戶管理的權限判斷：這個 feature 的每個端點都經過 `authorize_account_action`，只有這一處。

為什麼集中：T-304（管理員管理）加上「只有 OWNER 能新增、封存、復原、修改 ADMIN 帳戶」（D-115）：只在這個函式內多看一眼 `target`
（目標帳戶的角色），不改動任何端點。「誰能動誰」的表在 owner_manages_administrators/access.py，只有那一份。

現在的規則（IAM-F04）：ADMIN 與 OWNER 可以管理帳戶；USER 一律 FORBIDDEN，並寫 `ACCESS_DENIED`（permissions.authorize）。
USER 讀別人的勞健保扣除額與未投保比例同樣走這裡（D-114：GET /accounts/{id} 也要通過這一關）。
"""
from __future__ import annotations

from app.core.actor import Actor, Role
from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Rule, authorize
from app.modules.iam.owner_manages_administrators.access import OWNER_ONLY, authorize_on_target

MSG_ARCHIVE_OWNER = "owner 帳戶不能封存"  # IAM-R22（附錄 B）
MSG_ARCHIVE_SELF = "不能封存自己目前登入的帳戶"  # IAM-R22（附錄 B）

# OWNER 擁有 ADMIN 的全部權限（permissions._effective_roles），所以只列 ADMIN
MANAGE_ACCOUNTS = Rule(roles={Role.ADMIN})


def authorize_account_action(actor: Actor | None, action: str, target=None, *, modifies: bool = True) -> None:
    """通過就回傳；否則丟 OutcomeError（FORBIDDEN，已寫 ACCESS_DENIED）。

    `target` 是被動到的帳戶（可為 None，例如清單與建立）。給了 `target` 且這個動作會修改帳戶（`modifies`），
    再依目標的角色判斷（IAM-R20，D-115）：對象是 ADMIN 或 OWNER，只有 OWNER 能動；ADMIN 只能動 USER。
    只讀（打開帳戶頁）不在 IAM-R20 的範圍內，`modifies=False` 時只看「至少是 ADMIN」。
    """
    authorize(actor, action, MANAGE_ACCOUNTS)
    if target is not None and modifies:
        authorize_on_target(actor, action, target.role)


def authorize_create(actor: Actor, role_field: str | None) -> None:
    """IAM-R20：ADMIN 不能建立 ADMIN（FORBIDDEN）。先於欄位驗證：沒有權限的人探不到欄位規則。其他角色值由 service 驗證。"""
    if role_field == Role.ADMIN.value:
        authorize(actor, "create an ADMIN account", OWNER_ONLY)


def refuse_archiving_yourself(actor: Actor, target) -> None:
    """IAM-R22：不能封存自己（CONFLICT）。先於 IAM-R20 的角色判斷：ADMIN 封存自己是 CONFLICT，不是 FORBIDDEN（規格的 scenario）。"""
    if target.id == actor.id:
        raise OutcomeError(Outcome.CONFLICT, MSG_ARCHIVE_OWNER if target.role == Role.OWNER.value else MSG_ARCHIVE_SELF)


def refuse_archiving_owner(target) -> None:
    """IAM-R22：OWNER 帳戶不能封存（CONFLICT）。通過 IAM-R20 的只有 OWNER 本人，已被 `refuse_archiving_yourself` 擋下；這是不變式的最後一道。"""
    if target.role == Role.OWNER.value:
        raise OutcomeError(Outcome.CONFLICT, MSG_ARCHIVE_OWNER)


def may_list_administrators(actor: Actor) -> bool:
    """Q-056：ADMIN 的帳戶管理只列 USER；OWNER 另外看得到 ADMIN（D-126：OWNER 能解除 ADMIN 的鎖定）。"""
    return actor.role is Role.OWNER
