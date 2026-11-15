from pytest_bdd import given, parsers, scenarios, then, when

from app.core.clock import clock
from tests.support.background import parse_background

scenarios("../../tests/integration/world.feature")


def _names(db):
    with db.cursor() as cur:
        cur.execute("select name from yc_v3.accounts order by id")
        return [r[0] for r in cur.fetchall()]


@given("the database holds exactly the background accounts")
@then("the database holds exactly the background accounts")
def _background_only(db):
    assert _names(db) == [a["name"] for a in parse_background().accounts]


@when(parsers.parse('a test account "{name}" is added'))
def _add(db, name):
    with db.cursor() as cur:
        cur.execute("insert into yc_v3.accounts(name, role, zone) values (%s, 'USER', 'WEST')", (name,))
    db.commit()


@then(parsers.parse("the database holds {n:d} accounts"))
def _count(db, n):
    assert len(_names(db)) == n


@then(parsers.parse('the clock reads "{iso}"'))
def _clock(iso):
    assert clock.now().isoformat() == iso
