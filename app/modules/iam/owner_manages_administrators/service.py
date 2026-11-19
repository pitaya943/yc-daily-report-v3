"""切換角色（IAM-R21，D-118：`POST /accounts/{id}/role`）。

- 只有 OWNER 能切換角色（附錄 B「角色」）：USER 與 ADMIN 一律 FORBIDDEN 並寫 `ACCESS_DENIED`，
  不論對象是誰、連自己也不行（IAM-R22：ADMIN 不能改自己的角色）。權限先於欄位驗證與查帳戶：沒有權限的人不能靠 404 或欄位錯誤探到資訊。
- 欄位：`role` 只能是 `ADMIN` 或 `USER`；缺少、重複、空白、`OWNER` 或其他值都是 INVALID「請選擇角色」（附錄 B：OWNER 不能選）。
- 對象不存在 → AccountNotFound（router 回 404，D-106）。對象是 OWNER → INVALID（沒有這個動作，規格沒有字串）：唯一的 OWNER 不能被改角色。
- 切換為 ADMIN 前大表旗標須關閉（IAM-R21，Q-057）：旗標為開 → CONFLICT「請先關閉大表旗標，再切換為管理員」，資料不變。
- 角色沒有改變（USER → USER）：接受，不寫、不稽核（與 IAM-R15 的「沒有變動」相同做法）。
- 成功：角色更新與 `ACCOUNT_ROLE_CHANGE` 在同一個 transaction 提交。被切換者的 session 不結束：角色每次請求都從資料庫讀取，立即生效。
"""
from __future__ import annotations

import psycopg

from app.core import audit
from app.core.actor import Actor, Role
from app.core.outcomes import Outcome, OutcomeError
from app.modules.iam.account_lifecycle_and_pay_settings import repo as accounts
from app.modules.iam.owner_manages_administrators import repo
from app.modules.iam.owner_manages_administrators.access import OWNER_ONLY
from app.core.permissions import authorize

MSG_ROLE = "請選擇角色"
MSG_BIG_METER_FIRST = "請先關閉大表旗標，再切換為管理員"

SELECTABLE_ROLES = (Role.ADMIN.value, Role.USER.value)  # 附錄 B：產品內只能選 ADMIN 或 USER


class AccountNotFound(Exception):
    """沒有這個帳戶（規格沒有「找不到」的結果類別；router 回 404，D-106）。"""


def switch_role(conn: psycopg.Connection, actor: Actor, account_id: int, form: dict[str, list[str]]) -> bool:
    """回傳是否真的有改變。"""
    authorize(actor, "change a role", OWNER_ONLY)
    values = form.get("role")
    role = values[0] if values is not None and len(values) == 1 else None  # 缺少或重複的欄位都不合格，不挑其中一個
    if role not in SELECTABLE_ROLES:
        raise OutcomeError(Outcome.INVALID, MSG_ROLE)
    target = accounts.get(conn, account_id, lock=True)
    if target is None:
        raise AccountNotFound(account_id)
    if target.role == Role.OWNER.value:
        raise OutcomeError(Outcome.INVALID)  # 沒有這個動作：唯一的 OWNER 不能被改角色
    if target.role == role:
        return False
    if role == Role.ADMIN.value and target.big_meter:
        raise OutcomeError(Outcome.CONFLICT, MSG_BIG_METER_FIRST)
    repo.set_role(conn, account_id, role)
    audit.write(actor, "ACCOUNT_ROLE_CHANGE", f"變更 {target.name} 的角色：{target.role} → {role}", conn=conn)
    conn.commit()
    return True
