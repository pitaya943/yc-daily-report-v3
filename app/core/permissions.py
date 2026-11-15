"""權限檢查：以角色、擁有權、狀態為輸入（spec/features/AUD-F01）。

    OWN_PENDING = Rule(roles={Role.USER}, owner_only=True, states={"PENDING"})
    authorize(actor, "edit a report", ADMIN_RULE, OWN_PENDING, resource=Resource(owner_id=..., state=...))

語意：
- 一條 `Rule` 內的條件是 AND：角色在 `roles`、（`owner_only` 時）擁有者就是行為者、
  （有 `states` 時）資源狀態在 `states` 內。傳入多條 Rule 時，任一條成立即可（OR）。
  這讓「管理員，或自己的待審回報」寫成兩條規則，而不是一個塞滿旗標的函式。
- fail-closed：要求狀態卻沒給狀態、要求擁有權卻沒給擁有者，一律不通過。
- OWNER 擁有 ADMIN 的全部權限（spec/glossary.md），反過來不成立。
- 沒有行為者（沒登入）→ `UNAUTHENTICATED`，不寫稽核（AUD-R01）。
- 被拒絕 → 先寫 `ACCESS_DENIED`（獨立連線、立刻提交，見 audit.py），再丟 `FORBIDDEN`（AUD-R03、AUD-R10）。
  稽核說明點出被嘗試的動作，所以 `action` 是必填的人類可讀字串。
  `FORBIDDEN` 沒有 spec 規定的錯誤字串，故 message 為 None（見 outcomes.py）。
- 只負責「權限」。「資料合法但狀態不允許」是 `CONFLICT`，由業務程式判斷，不在這裡。
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core import audit
from app.core.actor import SYSTEM, Actor, Role  # noqa: F401  (re-export)
from app.core.outcomes import Outcome, OutcomeError


@dataclass(frozen=True)
class Resource:
    owner_id: int | None = None
    state: str | None = None


@dataclass(frozen=True)
class Rule:
    roles: frozenset[Role]
    owner_only: bool = False
    states: frozenset[str] | None = None

    def __init__(self, roles, owner_only: bool = False, states=None) -> None:
        object.__setattr__(self, "roles", frozenset(roles))
        object.__setattr__(self, "owner_only", owner_only)
        object.__setattr__(self, "states", None if states is None else frozenset(states))


def _effective_roles(actor: Actor) -> frozenset[Role]:
    return frozenset({Role.OWNER, Role.ADMIN}) if actor.role is Role.OWNER else frozenset({actor.role})


def _satisfies(actor: Actor, rule: Rule, resource: Resource | None) -> bool:
    if not (_effective_roles(actor) & rule.roles):
        return False
    if rule.owner_only and (resource is None or resource.owner_id is None or resource.owner_id != actor.id):
        return False
    if rule.states is not None and (resource is None or resource.state not in rule.states):
        return False
    return True


def authorize(actor: Actor | None, action: str, *rules: Rule, resource: Resource | None = None) -> None:
    """通過就回傳；否則丟 OutcomeError（UNAUTHENTICATED 或 FORBIDDEN）。"""
    if actor is None:
        raise OutcomeError(Outcome.UNAUTHENTICATED)
    if any(_satisfies(actor, r, resource) for r in rules):
        return
    audit.write(actor, "ACCESS_DENIED", f"嘗試執行但被拒絕：{action}")
    raise OutcomeError(Outcome.FORBIDDEN)
