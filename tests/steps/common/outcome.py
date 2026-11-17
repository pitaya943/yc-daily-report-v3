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
  例外只有 FORBIDDEN（D-095）：規格規定每個 FORBIDDEN 都寫 `ACCESS_DENIED`（spec/README.md 結果類別表、AUD-R03），
  所以它的資料斷言是「恰好新增 1 列 `ACCESS_DENIED`、行為者是被拒絕的人（發出請求的 session 的主人），其他資料表完全不變」；
  這一列同時被記為「已斷言」，之後的 `nothing else is written` 可以扣掉它。
- `signed in` 與 `accepted` 是成功的結果：前者檢查登入的回應與 cookie，後者是 200。
- `the outcome is <outcome> with message "<message>"`（D-117 S1，T-305 新增）：規格的例子表把結果與完整字串放在同一列
  （例如 IAM-R30）。`accepted` 時 message 必須是空字串、HTTP 200；其他類別逐字比對（`check_rejected`，不經附錄 B 白名單：
  這句的重點就是「這一句」），資料斷言與 `the outcome is X` 完全相同（FORBIDDEN 依 D-095）。例子表的空儲存格代表
  「規格沒有為這個拒絕寫字串」，也就是回應的 message 為 null。
  regex 用 fullmatch，而 `the outcome is (?P<outcome>[A-Z_]+)` 不含空白與引號，所以不會吃掉這一句（見 test_outcome_with_message.py）。
"""
from __future__ import annotations

import functools

from pytest_bdd import parsers, then

from app.core import session as session_core
from tests.steps.common.spec_tables import SPEC
from tests.steps.common.steps import check_nothing_written, check_rejected, claim_audit_row

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


def check_accepted(recorder) -> None:
    r = recorder.response
    assert r.status_code == 200, f"應被接受（200），實際 {r.status_code}：{r.text[:200]}"


@then("the outcome is accepted")
def _outcome_accepted(recorder):
    check_accepted(recorder)


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


def check_forbidden_writes_only_access_denied(recorder, client, db) -> None:
    """D-095：FORBIDDEN 恰好新增 1 列 ACCESS_DENIED、行為者是被拒絕的人，其他資料表完全不變。

    「被拒絕的人」是發出請求的 session 的主人（client 的 session cookie）：FORBIDDEN 是「已登入但不被允許」，
    沒有有效 session 的請求不可能是 FORBIDDEN（那是 UNAUTHENTICATED）。
    """
    token = client.cookies.get(session_core.SESSION_COOKIE)
    actor = session_core.actor_for_token(db, token) if token else None
    db.rollback()
    assert actor is not None, "FORBIDDEN 的請求必須由已登入者發出（沒有有效的 session）"
    changes = recorder.changes()
    others = {t: c for t, c in changes.items() if t != "audit_log"}
    assert not others, f"FORBIDDEN 除了 ACCESS_DENIED 之外，其他資料表不能有變動：{others}"
    audit = changes.get("audit_log", {"added": [], "removed": []})
    assert audit["removed"] == [], "稽核紀錄不可被刪除或修改"
    assert len(audit["added"]) == 1, f"FORBIDDEN 應恰好新增 1 列稽核（ACCESS_DENIED），實際 {len(audit['added'])} 列：{audit['added']}"
    claim_audit_row(recorder, db, "ACCESS_DENIED", actor.name)  # 類型與行為者都要對；同時記為已斷言


def check_rejection_writes(recorder, client, db, outcome: str) -> None:
    """拒絕時的資料斷言：FORBIDDEN 依 D-095，其他類別資料完全不變。`the outcome is X` 與 `... with message` 共用。"""
    if outcome == "FORBIDDEN":
        check_forbidden_writes_only_access_denied(recorder, client, db)  # D-095
    else:
        check_nothing_written(recorder)


@then(parsers.re(r"the outcome is (?P<outcome>[A-Z_]+)"))
def _outcome_rejected(recorder, client, db, outcome):
    try:
        actual = recorder.response.json().get("message")
    except Exception:  # 回應不是 JSON：交給 check_rejected 報出真正的問題
        actual = None
    check_rejected(recorder, outcome, expected_message(outcome, actual))
    check_rejection_writes(recorder, client, db, outcome)


@then(parsers.re(r'the outcome is (?P<outcome>accepted|[A-Z_]+) with message "(?P<message>.*)"'))
def _outcome_with_message(recorder, client, db, outcome, message):
    """D-117 S1：結果類別與完整錯誤字串一起斷言。"""
    if outcome == "accepted":
        assert message == "", f"accepted 不可帶錯誤字串，規格寫的是 {message!r}"
        check_accepted(recorder)
        return
    # 空字串 = 規格沒有為這個拒絕寫字串 → 回應的 message 必須是 null；其他一律逐字相等
    check_rejected(recorder, outcome, message or None)
    check_rejection_writes(recorder, client, db, outcome)
