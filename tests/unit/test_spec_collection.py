"""完成條件 4：spec/features 裡的每一個 scenario（Outline 依 Examples 展開）都必須被收集。

pytest-bdd 以名稱當 key，同一個 .feature 內重名的 scenario 會被後者覆蓋、且沒有任何警告
（CFG-F02 有兩個 `Validation`）。這個測試用「與 pytest-bdd 無關的文字計數」當期望值，
所以以後不論是重名、或 pytest-bdd 解析行為改變而少收集，都會在這裡失敗，而不是默默少掉。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEATURES = sorted((ROOT / "spec" / "features").glob("*.feature"))

SCENARIO = re.compile(r"^\s*Scenario( Outline| Template)?:")
EXAMPLES = re.compile(r"^\s*Examples:")


def expected_tests(path: Path) -> int:
    """直接數 Gherkin 文字：Scenario 數 + 每個 Examples 表的資料列數 - 1（Outline 本身不算）。"""
    total, in_examples, header_seen = 0, False, False
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#") or not s:
            continue
        if SCENARIO.match(line):
            total += 1
            in_examples = False
            continue
        if EXAMPLES.match(line):
            in_examples, header_seen = True, False
            continue
        if in_examples and s.startswith("|"):
            if not header_seen:
                header_seen = True
            else:
                total += 1
            continue
        if in_examples and not s.startswith("|"):
            in_examples = False
    return total


def outline_count(path: Path) -> int:
    return sum(1 for l in path.read_text(encoding="utf-8").splitlines() if re.match(r"^\s*Scenario (Outline|Template):", l))


def expected_total() -> int:
    # Outline 本身被 Examples 的每一列取代，所以要扣掉 Outline 的標題數
    return sum(expected_tests(p) - outline_count(p) for p in FEATURES)


def test_expected_count_is_sane():
    assert len(FEATURES) == 31
    assert expected_total() >= 489


def test_every_scenario_is_collected():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_spec.py", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    last = r.stdout.strip().splitlines()[-1]
    m = re.search(r"(\d+) tests? collected", last)
    assert m, r.stdout[-500:] + r.stderr[-500:]
    assert int(m.group(1)) == expected_total(), (
        f"collected {m.group(1)} but spec expands to {expected_total()}: some scenario was dropped"
    )


def test_same_named_scenarios_in_one_feature_are_all_collected():
    """CFG-R10 與 CFG-R11 各有一個 `Validation`；列入 CFG-R10 時必須跑到它的 6 個例子 + Zones are independent。"""
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("CFG-R10\n")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_spec.py", "--implemented", f.name, "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    m = re.search(r"(\d+) failed", r.stdout.strip().splitlines()[-1])
    # 步驟還沒實作，所以全部「失敗」；重點是數量：CFG-R10 的所有 scenario 都有被執行
    assert m and int(m.group(1)) == 7, r.stdout[-800:]
