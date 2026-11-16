"""T-111 小組分配（REV-R10）的單元測試。

單位約定：數量一律以 tenth（0.1 只）的整數表示，2.3 只 = 23。
split(tenths, crew_size) 回傳依 crew 順序排列的整數份額。
"""
import pytest

from app.domain.split import split


def to_tenths(text: str) -> int:
    """把 "7.0" 這類字串轉成整數 tenth；不經過浮點數。"""
    whole, _, frac = text.partition(".")
    return int(whole) * 10 + int(frac or "0")


# 與 REV-F02 REV-R10 的 Examples 表逐列對應（qty, n, shares）。
EXAMPLES = [
    ("7.0", 1, "7.0"),
    ("6.0", 2, "3.0, 3.0"),
    ("7.0", 3, "2.4, 2.3, 2.3"),
    ("7.0", 3, "2.4, 2.3, 2.3"),  # crew A, C, B：份額只依位置，與人名無關
    ("1.0", 3, "0.4, 0.3, 0.3"),
    ("0.1", 3, "0.1, 0.0, 0.0"),
    ("0.5", 3, "0.2, 0.2, 0.1"),
    ("999.9", 7, "142.9, 142.9, 142.9, 142.8, 142.8, 142.8, 142.8"),
    ("0", 3, "0.0, 0.0, 0.0"),
]


@pytest.mark.parametrize("qty,n,shares", EXAMPLES)
def test_split_examples(qty, n, shares):
    expected = [to_tenths(s.strip()) for s in shares.split(",")]
    assert len(expected) == n
    assert split(to_tenths(qty), n) == expected


def test_split_invariants_all_inputs():
    # 數量 0–999.9（步進 0.1）× 人數 1–7，共 10000 × 7 組。
    for tenths in range(0, 9999 + 1):
        for n in range(1, 8):
            shares = split(tenths, n)
            assert len(shares) == n
            assert all(isinstance(s, int) and s >= 0 for s in shares)
            assert sum(shares) == tenths
            assert max(shares) - min(shares) <= 1
            assert all(shares[i] >= shares[i + 1] for i in range(n - 1))
