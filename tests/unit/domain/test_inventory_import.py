"""T-114 庫存比對（MAT-R20、MAT-R21、AD-6）的單元測試。

單位約定：數量一律以 tenth（0.1 只）的整數表示；這裡的範例直接用 spec 的整數。
A = 系統現況，B = 上傳檔，x = B.received - A.received。
不變式：received == cumulative + remaining。
"""
import pytest

from app.core.outcomes import Outcome
from app.domain.inventory_import import (
    B_INCONSISTENT_MESSAGE,
    Stock,
    decide_import,
    resolve_quarantine,
)

# 與 MAT-F03 MAT-R20「Import decision per row」的 Examples 逐列對應。
# (a_rec, a_cum, a_rem, b_rec, b_cum, b_rem, decision, fault, rec, cum, rem)
R20_ROWS = [
    pytest.param(15, 10, 5, 20, 10, 10, "applied", "-", 20, 10, 10, id="normal-inbound-of-5"),
    pytest.param(15, 10, 5, 15, 10, 5, "applied", "-", 15, 10, 5, id="x-equals-0"),
    pytest.param(15, 10, 5, 12, 10, 2, "quarantined", "?", 15, 10, 5, id="x-negative"),
    pytest.param(15, 10, 4, 20, 10, 10, "quarantined", "A", 15, 10, 4, id="A-breaks-invariant"),
    pytest.param(15, 10, 5, 20, 12, 7, "quarantined", "B", 15, 10, 5, id="B-differs-from-expected"),
]


@pytest.mark.parametrize(
    "a_rec,a_cum,a_rem,b_rec,b_cum,b_rem,decision,fault,rec,cum,rem", R20_ROWS
)
def test_mat_r20_import_decision(
    a_rec, a_cum, a_rem, b_rec, b_cum, b_rem, decision, fault, rec, cum, rem
):
    a = Stock(a_rec, a_cum, a_rem)
    b = Stock(b_rec, b_cum, b_rem)
    result = decide_import(a, b)
    assert result.decision == decision
    assert result.fault == fault
    # 隔離時 A 必須原封不動；套用時是 A 加上 x。
    assert result.stock == Stock(rec, cum, rem)


def test_decide_import_does_not_mutate_inputs():
    a = Stock(15, 10, 5)
    decide_import(a, Stock(20, 10, 10))
    assert a == Stock(15, 10, 5)


# MAT-R21 Trust A or trust B：A (15, 10, 5)、B (20, 12, 8)、x = 5。
A = Stock(15, 10, 5)
B = Stock(20, 12, 8)


def test_mat_r21_trust_a():
    result = resolve_quarantine("trust A", A, B)
    assert result.stock == Stock(20, 10, 10)
    assert result.audit == "MATERIAL_KEEP_A"
    assert result.quarantined is False


def test_mat_r21_trust_b():
    result = resolve_quarantine("trust B", A, B)
    assert result.stock == Stock(20, 12, 8)
    assert result.audit == "MATERIAL_SYNC_B"
    assert result.quarantined is False


def test_ad6_trust_b_refused_when_b_breaks_invariant():
    """AD-6：結果類別、完整錯誤字串、資料沒有任何變動，三件事都斷言。"""
    bad_b = Stock(20, 12, 7)
    result = resolve_quarantine("trust B", A, bad_b)
    assert result.outcome is Outcome.CONFLICT
    assert result.message == "B 系統數值不一致，無法採用"
    assert result.message == B_INCONSISTENT_MESSAGE
    assert result.quarantined is True  # 該列留在暫存區
    assert result.stock == A  # 資料沒有任何變動
    assert result.audit is None  # 沒有稽核列


def test_trust_a_is_not_blocked_by_inconsistent_b():
    """AD-6 只限制「信任 B」；信任 A 時 B 不合不變式不影響結果。"""
    result = resolve_quarantine("trust A", A, Stock(20, 12, 7))
    assert result.stock == Stock(20, 10, 10)


def test_unknown_choice_is_a_programming_error():
    with pytest.raises(ValueError):
        resolve_quarantine("trust C", A, B)
