"""完成條件 3：時鐘可由測試設定與推進；產品程式不直接讀系統時間。"""
import ast
import re
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.clock import Clock

TAIPEI = ZoneInfo("Asia/Taipei")


def test_set_and_read():
    c = Clock()
    c.set(datetime(2026, 11, 15, 10, 0, tzinfo=TAIPEI))
    assert c.now() == datetime(2026, 11, 15, 10, 0, tzinfo=TAIPEI)
    assert c.now().tzinfo is not None


def test_frozen_clock_does_not_move():
    c = Clock()
    c.set(datetime(2026, 11, 15, 10, 0, tzinfo=TAIPEI))
    assert c.now() == c.now()


def test_advance():
    c = Clock()
    c.set(datetime(2026, 11, 15, 10, 0, tzinfo=TAIPEI))
    c.advance(timedelta(minutes=15))
    assert c.now() == datetime(2026, 11, 15, 10, 15, tzinfo=TAIPEI)


def test_naive_datetime_is_rejected():
    c = Clock()
    try:
        c.set(datetime(2026, 11, 15, 10, 0))
    except ValueError:
        return
    raise AssertionError("naive datetime must be rejected")


def test_unset_clock_follows_real_time_in_taipei():
    c = Clock()
    assert c.now().utcoffset() == timedelta(hours=8)


SQL_TIME = re.compile(r"(?<![\w.])now\s*\(\s*\)|current_timestamp|current_date|clock_timestamp", re.I)

FORBIDDEN_CALLS = {
    ("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
    ("date", "today"), ("time", "time"), ("time", "time_ns"),
    ("time", "monotonic"), ("time", "localtime"), ("time", "gmtime"),
}


def test_product_code_never_reads_system_time():
    """掃描 app/**，除了 app/core/clock.py 以外不得呼叫系統時間。"""
    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "clock.py" and path.parent.name == "core":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                owner = node.func.value
                owner_name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", None)
                if (owner_name, node.func.attr) in FORBIDDEN_CALLS:
                    offenders.append(f"{path.relative_to(root.parent)}:{node.lineno}")
        text = path.read_text(encoding="utf-8")
        # SQL 的 now()/current_timestamp 也是系統時間
        # （`clock.now()` 的 `now()` 前面有 `.`，不算）
        if SQL_TIME.search(text):
            offenders.append(f"{path.relative_to(root.parent)}: SQL time function")
    assert offenders == []
