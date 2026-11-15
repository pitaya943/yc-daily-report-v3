"""完成條件 3：權限檢查以角色、擁有權、狀態為輸入；被拒絕時自動寫 ACCESS_DENIED。"""
import pytest

from app.core.outcomes import Outcome, OutcomeError
from app.core.permissions import Actor, Resource, Role, Rule, authorize

OWN = Rule(roles={Role.USER}, owner_only=True, states={"PENDING", "REJECTED"})
ADMIN_ONLY = Rule(roles={Role.ADMIN})
OWNER_ONLY = Rule(roles={Role.OWNER})


def actor(db, name) -> Actor:
    with db.cursor() as cur:
        cur.execute("select id, role from yc_v3.accounts where name = %s", (name,))
        i, role = cur.fetchone()
    return Actor(id=i, name=name, role=Role(role))


def audit_rows(db):
    with db.cursor() as cur:
        cur.execute("select actor_name, type, description from yc_v3.audit_log order by id")
        return cur.fetchall()


def test_allowed_request_returns_and_writes_nothing(db):
    wen = actor(db, "Wen")
    authorize(wen, "submit own report", OWN, resource=Resource(owner_id=wen.id, state="PENDING"))
    assert audit_rows(db) == []


@pytest.mark.parametrize(
    "who,rule,resource_of,why",
    [
        ("Admin1", OWN, lambda a: Resource(owner_id=a.id, state="PENDING"), "role"),
        ("Wen", OWN, lambda a: Resource(owner_id=a.id + 1, state="PENDING"), "ownership"),
        ("Wen", OWN, lambda a: Resource(owner_id=a.id, state="CONFIRMED"), "state"),
        ("Wen", OWN, lambda a: Resource(owner_id=a.id), "state missing is not allowed"),
        ("Wen", ADMIN_ONLY, lambda a: None, "role"),
        ("Admin1", OWNER_ONLY, lambda a: None, "role"),
    ],
)
def test_denied_raises_forbidden_and_writes_exactly_one_access_denied(db, who, rule, resource_of, why):
    a = actor(db, who)
    with pytest.raises(OutcomeError) as e:
        authorize(a, "confirm a report", rule, resource=resource_of(a))
    assert e.value.outcome is Outcome.FORBIDDEN
    rows = audit_rows(db)
    assert len(rows) == 1, why
    name, type_, desc = rows[0]
    assert (name, type_) == (who, "ACCESS_DENIED")
    assert "confirm a report" in desc  # 說明文字要點出被嘗試的動作（AUD-R03）


def test_owner_has_every_admin_permission(db):
    authorize(actor(db, "Kuei"), "calculate payroll", ADMIN_ONLY)
    assert audit_rows(db) == []


def test_admin_does_not_get_owner_only_permission(db):
    with pytest.raises(OutcomeError):
        authorize(actor(db, "Admin1"), "open the audit log", OWNER_ONLY)


def test_any_matching_rule_is_enough(db):
    wen = actor(db, "Wen")
    # 管理員，或自己的待審回報
    authorize(wen, "edit report", ADMIN_ONLY, OWN, resource=Resource(owner_id=wen.id, state="PENDING"))
    with pytest.raises(OutcomeError):
        authorize(wen, "edit report", ADMIN_ONLY, OWN, resource=Resource(owner_id=wen.id, state="CONFIRMED"))


def test_no_actor_is_unauthenticated_and_not_audited(db):
    with pytest.raises(OutcomeError) as e:
        authorize(None, "anything", ADMIN_ONLY)
    assert e.value.outcome is Outcome.UNAUTHENTICATED
    assert audit_rows(db) == []


def test_denial_audit_survives_the_callers_rollback(db):
    wen = actor(db, "Wen")
    with pytest.raises(OutcomeError):
        authorize(wen, "confirm a report", ADMIN_ONLY)
    db.rollback()
    assert len(audit_rows(db)) == 1
