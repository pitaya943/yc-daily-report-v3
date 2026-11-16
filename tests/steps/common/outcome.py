"""`the outcome is ...` 的共用步驟（T-102 完成條件 10、D-052）。

原本由 T-103 定義在 tests/steps/IAM-F03/iam_f03_steps.py（只斷言 message 為 null）。IAM-F02 的 LOCKED 卻有規格字串，
而步驟是全域註冊的：兩處定義同文字的步驟，後載入的會靜靜覆蓋前一個。所以只在這裡定義一次，並一般化。

使用方式（與 steps.py、session.py 相同）：

    from tests.steps.common.outcome import *   # noqa: F401,F403

規則：
- 結果類別 → HTTP status 依 spec/README.md 的表（`check_rejected` 從 spec 解析，不另抄一份）。
- 該結果類別在規格裡有固定的錯誤字串時，逐字斷言；沒有的斷言 message 為 null（不替規格發明字串）。
  目前只有 LOCKED 有（spec/appendix-b-fields.md「登入密碼」：「密碼錯誤次數過多，請在 15 分鐘後再試」）。
  UNAUTHENTICATED 在登入時有字串，但閒置逾時沒有，同一個結果類別不能一概而論，所以登入用
  `the request is rejected as UNAUTHENTICATED with message "..."`，不走這個步驟。
- 拒絕時斷言資料沒有任何變動（AGENTS.md 不可違反 #5）：IAM-F03 原本的兩項斷言（null 與 nothing is written）不放寬。
- `signed in` 與 `accepted` 是成功的結果：前者檢查登入的回應與 cookie，後者是 200。
"""
from __future__ import annotations

from pytest_bdd import parsers, then

from app.core import session as session_core
from tests.steps.common.steps import check_nothing_written, check_rejected

# 有規格字串的結果類別 → 完整錯誤字串。逐字出自 spec/appendix-b-fields.md。
SPEC_MESSAGES: dict[str, str] = {
    "LOCKED": "密碼錯誤次數過多，請在 15 分鐘後再試",
}


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
    check_rejected(recorder, outcome, SPEC_MESSAGES.get(outcome))
    check_nothing_written(recorder)
