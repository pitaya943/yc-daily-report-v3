"""完成條件 2：audit.write(actor, type, description) 可用；類型限於 spec/appendix-c-audit-types.md。"""
import psycopg
import pytest

from app.core import audit
from app.core.clock import clock
from app.core.db import connect
from app.core.permissions import SYSTEM, Actor, Role
from tests.steps.common.spec_tables import audit_types, removed_audit_types

WEN = Actor(id=None, name="Wen", role=Role.USER)


def _rows(db):
    with db.cursor() as cur:
        cur.execute("select actor_account_id, actor_name, type, description, occurred_at from yc_v3.audit_log order by id")
        return cur.fetchall()


def _wen(db) -> Actor:
    with db.cursor() as cur:
        cur.execute("select id, role from yc_v3.accounts where name = 'Wen'")
        i, role = cur.fetchone()
    return Actor(id=i, name="Wen", role=Role(role))


def test_allowed_types_are_exactly_appendix_c():
    assert set(audit.AUDIT_TYPES) == audit_types()
    assert len(audit_types()) == 37


def test_removed_types_are_rejected_and_nothing_is_written(db):
    for t in removed_audit_types():
        with pytest.raises(audit.UnknownAuditType):
            audit.write(_wen(db), t, "x")
    assert _rows(db) == []


def test_unknown_type_is_rejected(db):
    with pytest.raises(audit.UnknownAuditType):
        audit.write(_wen(db), "NOT_A_TYPE", "x")
    assert _rows(db) == []


def test_write_records_actor_type_description_and_taipei_time(db):
    wen = _wen(db)
    audit.write(wen, "REPORT_CREATE", "建立回報（共 3 人作業）")
    [(actor_id, name, type_, desc, at)] = _rows(db)
    assert (actor_id, name, type_, desc) == (wen.id, "Wen", "REPORT_CREATE", "建立回報（共 3 人作業）")
    assert at == clock.now()  # 時間來自 app.core.clock，不是系統時間（同一個時間點）
    # psycopg 依「資料庫 session 的時區」顯示 timestamptz（本機是 Asia/Taipei，CI 的 postgres:17 是 UTC），
    # 所以不能斷言回傳值的 utcoffset。改讓資料庫換算成台北的牆上時間，與資料庫的時區設定無關。
    wall = db.execute("select (occurred_at at time zone 'Asia/Taipei')::text from yc_v3.audit_log").fetchone()[0]
    assert wall == "2026-11-15 10:00:00"  # background 的時鐘：2026-11-15 10:00 Asia/Taipei


def test_system_actor_is_recorded_as_system(db):
    audit.write(SYSTEM, "ACCOUNT_LOCKOUT", "鎖定")
    [(actor_id, name, *_)] = _rows(db)
    assert (actor_id, name) == (None, "SYSTEM")


def test_without_a_connection_the_row_is_committed_on_its_own(db):
    audit.write(_wen(db), "ACCESS_DENIED", "x")
    with connect() as other:  # 另一條連線也看得到 → 已提交
        assert other.execute("select count(*) from yc_v3.audit_log").fetchone()[0] == 1


def test_with_a_connection_the_row_follows_the_callers_transaction(db):
    wen = _wen(db)
    audit.write(wen, "REPORT_CREATE", "x", conn=db)
    db.rollback()
    assert _rows(db) == []  # 業務動作回滾，稽核跟著回滾（兩者同生同死）
    audit.write(wen, "REPORT_CREATE", "x", conn=db)
    db.commit()
    assert len(_rows(db)) == 1


def test_the_database_itself_rejects_types_outside_appendix_c(db):
    for t in ("ACCOUNT_DELETE", "NOPE"):
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "insert into yc_v3.audit_log(occurred_at, actor_name, type, description) values (now(), 'SYSTEM', %s, 'x')", (t,)
            )
        db.rollback()


def test_the_database_accepts_every_type_of_appendix_c(db):
    for t in sorted(audit_types()):
        db.execute("insert into yc_v3.audit_log(occurred_at, actor_name, type, description) values (now(), 'SYSTEM', %s, 'x')", (t,))
    db.commit()
    assert db.execute("select count(*) from yc_v3.audit_log").fetchone()[0] == 37
