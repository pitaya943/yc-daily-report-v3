from tests.support.background import parse_background


def test_background_matches_spec():
    bg = parse_background()
    assert bg.clock.isoformat() == "2026-11-15T10:00:00+08:00"
    names = [a["name"] for a in bg.accounts]
    assert names == ["Kuei", "Admin1", "Admin2", "Wen", "Wei", "Wan", "Nan", "Big", "Old"]
    old = bg.accounts[-1]
    assert old["archived"] is True and old["role"] == "USER"
    assert [a["zone"] for a in bg.accounts if a["name"] == "Nan"] == ["SOUTH"]
    assert [a["big_meter"] for a in bg.accounts if a["name"] == "Big"] == [True]
