"""`the outcome is ...` 的共用步驟（T-102 完成條件 10、D-052）。

原本由 T-103 定義在 tests/steps/IAM-F03/iam_f03_steps.py（只斷言 message 為 null）。IAM-F02 的 LOCKED 卻有規格字串，
而步驟是全域註冊的：兩處定義同文字的步驟，後載入的會靜靜覆蓋前一個。所以只在這裡定義一次，並一般化。

使用方式（與 steps.py、session.py 相同）：

    from tests.steps.common.outcome import *   # noqa: F401,F403

規則：
- 結果類別 → HTTP status 依 spec/README.md 的表（`check_rejected` 從 spec 解析，不另抄一份）。
- LOCKED 只有一句固定的錯誤字串（spec/appendix-b-fields.md「登入密碼」：「密碼錯誤次數過多，請在 15 分鐘後再試」），
  逐字斷言，其他字串或 null 都不接受。
- 其他拒絕類別（D-093）：message 必須是附錄 B「錯誤訊息」欄裡逐字存在的字串，或為 null（規格沒有為該情況寫字串，
  例如 FORBIDDEN、閒置逾時的 UNAUTHENTICATED；不替規格發明字串）。字串清單在執行時從附錄 B 解析，不另抄一份。
  這個步驟只確認「是規格裡的某一句」，不確認是「這個欄位的那一句」：逐字對到正確的句子，由各 feature 的
  `the request is rejected as <OUTCOME> with message "..."` scenario 負責（例如 RPT-R02 的「The date error message」）。
  UNAUTHENTICATED 在登入時有字串，但閒置逾時沒有，所以登入用 `the request is rejected as UNAUTHENTICATED with message "..."`。
- 拒絕時斷言資料沒有任何變動（AGENTS.md 不可違反 #5）：IAM-F03 原本的兩項斷言（null 與 nothing is written）不放寬。
- `signed in` 與 `accepted` 是成功的結果：前者檢查登入的回應與 cookie，後者是 200。
"""
from __future__ import annotations

import functools

from pytest_bdd import parsers, then

from app.core import session as session_core
from tests.steps.common.spec_tables import SPEC
from tests.steps.common.steps import check_nothing_written, check_rejected

# 有規格字串的結果類別 → 完整錯誤字串。逐字出自 spec/appendix-b-fields.md。
SPEC_MESSAGES: dict[str, str] = {
    "LOCKED": "密碼錯誤次數過多，請在 15 分鐘後再試",
}


@functools.lru_cache(maxsize=None)
def appendix_b_messages() -> frozenset[str]:
    """spec/appendix-b-fields.md「錯誤訊息」欄裡的每一句完整字串。

    資料列的第 4 欄，多句以 `<br>` 分隔，每句外面包一層「」；只剝掉最外層（有的字串自己含「材料編號」這種內層引號）。
    沒有字串的列寫「—」，略過。
    """
    out: set[str] = set()
    for line in (SPEC / "appendix-b-fields.md").read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        for piece in cells[3].split("<br>"):
            piece = piece.strip()
            if piece.startswith("「") and piece.endswith("」") and len(piece) > 2:
                out.add(piece[1:-1])
    return frozenset(out)


def expected_message(outcome: str, actual: str | None) -> str | None:
    """這個拒絕可接受的 message：LOCKED 是它自己的那一句；其他類別是附錄 B 的字串或 null（D-093）。
    回傳 `check_rejected` 該比對的值；不可接受時回傳一個必然不等於 actual 的值，讓斷言訊息指出兩者。"""
    if outcome in SPEC_MESSAGES:
        return SPEC_MESSAGES[outcome]
    if actual is None or actual in appendix_b_messages():
        return actual
    return None  # actual 不是 null 也不在附錄 B → check_rejected 會以「應為 None」失敗


@then("the outcome is accepted")
def _outcome_accepted(recorder):
    r = recorder.response
    assert r.status_code == 200, f"應被接受（200），實際 {r.status_code}：{r.text[:200]}"


@then("the outcome is signed in")
def _outcome_signed_in(recorder, client, db):
    # 登入成功：轉址、發出 session cookie，而且 cookie 在資料庫裡對得到一個有效的 session
    r = recorder.response
    assert r.status_code == 303, f"登入成功應轉址（303），實際 {r.status_code}：{r.text[:200]}"
    token = client.cookies.get(session_core.SESSION_COOKIE)
    assert token, "登入成功後應收到 session cookie"
    actor = session_core.actor_for_token(db, token)
    db.rollback()
    assert actor is not None, "session cookie 在資料庫裡找不到對應的 session"


@then(parsers.re(r"the outcome is (?P<outcome>[A-Z_]+)"))
def _outcome_rejected(recorder, outcome):
    try:
        actual = recorder.response.json().get("message")
    except Exception:  # 回應不是 JSON：交給 check_rejected 報出真正的問題
        actual = None
    check_rejected(recorder, outcome, expected_message(outcome, actual))
    check_nothing_written(recorder)
