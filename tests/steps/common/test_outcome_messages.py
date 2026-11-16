"""共用步驟 `the outcome is <OUTCOME>` 的錯誤字串規則（D-093）。

規則：
- LOCKED：只接受自己那一句（「密碼錯誤次數過多，請在 15 分鐘後再試」）。
- 其他拒絕類別：message 必須是 spec/appendix-b-fields.md「錯誤訊息」欄逐字存在的字串，或為 null。

這是從「LOCKED 以外一律只接受 null」放寬成「也接受附錄 B 的字串」；null 仍然可以。
所以這裡的重點是反向測試：不在附錄 B 的字串（多一個字、少一個字、換一句）必須失敗，
否則步驟會變成「任何字串都通過」，等於把 AGENTS.md 不可違反 #5 的「完整錯誤字串」拿掉。

這裡直接呼叫步驟背後的函式，因為「該失敗的時候會失敗」無法用一個必須通過的 Gherkin scenario 表達
（與 test_nothing_else_written.py 相同）。
"""
from __future__ import annotations

import pytest

from app.core.outcomes import Outcome
from tests.steps.common import outcome as step
from tests.steps.common.spec_tables import outcome_http_table
from tests.steps.common.steps import Recorder


class _Response:
    def __init__(self, status_code: int, body: dict | None):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def _reject(db, outcome: str, message: str | None, *, status: int | None = None) -> Recorder:
    """假裝動作回了這個拒絕（沒有寫任何資料），回傳 recorder。"""
    r = Recorder(db)
    r.perform(lambda: _Response(status if status is not None else outcome_http_table()[outcome], {"outcome": outcome, "message": message}))
    return r


# ───────── 附錄 B 字串清單是從 spec 解析出來的 ─────────


def test_appendix_b_messages_are_parsed_from_the_spec():
    messages = step.appendix_b_messages()
    # 單句、多句（<br>）、含內層「」的字串都要解析正確
    assert "回報日期須為今天或往前 30 天內，不可選擇未來日期" in messages
    assert "工項數量須為 0 到 999.9，最小單位 0.1" in messages
    assert "每日最多只能送出 3 筆回報" in messages
    assert "密碼錯誤次數過多，請在 15 分鐘後再試" in messages
    assert "請上傳 xlsx 或 csv 檔，且標題列須含「材料編號」與「實領量」" in messages
    # 只剝最外層的「」：沒有字串以「開頭（內層的「」，如上面那句結尾的」，要保留）；「—」與欄位標題不是字串
    assert not any(m.startswith("「") for m in messages)
    assert "—" not in messages and "錯誤訊息" not in messages
    assert len(messages) > 50


# ───────── 會通過的 ─────────


@pytest.mark.parametrize(
    "outcome, message",
    [
        ("INVALID", "回報日期須為今天或往前 30 天內，不可選擇未來日期"),
        ("INVALID", "工項數量須為 0 到 999.9，最小單位 0.1"),
        ("INVALID", None),  # 規格沒有為該情況寫字串（例如 RPT-R01 的工項組以外）
        ("CONFLICT", "每日最多只能送出 3 筆回報"),
        ("CONFLICT", None),
        ("FORBIDDEN", None),
        ("UNAUTHENTICATED", None),
        ("LOCKED", "密碼錯誤次數過多，請在 15 分鐘後再試"),
    ],
)
def test_accepts_an_appendix_b_message_or_null(db, outcome, message):
    step._outcome_rejected(_reject(db, outcome, message), outcome)


# ───────── 會失敗的（反向測試）─────────


@pytest.mark.parametrize(
    "message",
    [
        "回報日期須為今天或往前 30 天內，不可選擇未來日期。",  # 多一個字
        "回報日期須為今天或往前 30 天內，不可選擇未來日期 ",  # 多一個空白
        "回報日期須為今天或往前 30 天內，不可選擇未來日期嗎",  # 多一個字
        "回報日期須為今天或往前 30 天內，不可選擇未來日",  # 少一個字
        "每日最多只能送出 3 筆回報。",
        "日期錯誤",  # 規格裡沒有的句子
        "",  # 空字串不是 null，也不在附錄 B
        "錯誤訊息",
        "—",
    ],
)
@pytest.mark.parametrize("outcome", ["INVALID", "CONFLICT", "FORBIDDEN"])
def test_rejects_a_message_that_is_not_in_appendix_b(db, outcome, message):
    with pytest.raises(AssertionError):
        step._outcome_rejected(_reject(db, outcome, message), outcome)


@pytest.mark.parametrize(
    "message",
    [
        None,
        "密碼錯誤，請重試",  # 附錄 B 的另一句（登入密碼的 UNAUTHENTICATED）
        "每日最多只能送出 3 筆回報",
        "密碼錯誤次數過多，請在 15 分鐘後再試。",
        "",
    ],
)
def test_locked_accepts_only_its_own_sentence(db, message):
    with pytest.raises(AssertionError):
        step._outcome_rejected(_reject(db, "LOCKED", message), "LOCKED")


def test_wrong_http_status_or_outcome_still_fails(db):
    # 字串對，但結果類別對不上 HTTP status／回應裡的類別：仍然失敗
    with pytest.raises(AssertionError):
        step._outcome_rejected(_reject(db, "INVALID", "每日最多只能送出 3 筆回報", status=409), "INVALID")
    with pytest.raises(AssertionError):
        step._outcome_rejected(_reject(db, "CONFLICT", "每日最多只能送出 3 筆回報"), "INVALID")


def test_a_non_json_response_fails_instead_of_passing(db):
    r = Recorder(db)
    r.perform(lambda: _Response(422, None))
    with pytest.raises(Exception):
        step._outcome_rejected(r, "INVALID")


def test_data_changes_still_fail_the_step(db):
    # check_nothing_written 照舊：字串合法，但動作寫了資料，一樣失敗
    r = Recorder(db)

    def action():
        db.execute("insert into yc_v3.accounts(name, role, zone) values ('Extra','USER','WEST')")
        db.commit()
        return _Response(422, {"outcome": "INVALID", "message": "回報日期須為今天或往前 30 天內，不可選擇未來日期"})

    r.perform(action)
    with pytest.raises(AssertionError):
        step._outcome_rejected(r, "INVALID")


def test_every_outcome_class_is_known():
    assert {o.value for o in Outcome} == set(outcome_http_table())
