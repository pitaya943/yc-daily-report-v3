"""`an audit row "X" is written`（不帶 actor）的共用步驟（D-117 S2，T-304）。

原本由 T-202 定義在 tests/steps/RPT-F02/rpt_f02_steps.py：行為者取自 RPT-F02 專用的 `lifecycle` fixture，
所以 IAM-F05 的 IAM-R21（`an audit row "ACCOUNT_ROLE_CHANGE" is written`）用不了。步驟是全域註冊的（pitfall #26），
同文字只能有一個定義，所以搬到這裡。

語意：這個動作新增了一列該類型的稽核，行為者是「發出請求的 session 的主人」（`client` 的 session cookie 對到的帳戶）。
- 類型不對 → 失敗；行為者不是 session 的主人 → 失敗；沒有新增 → 失敗；沒有有效的 session → 失敗（不知道行為者是誰，不猜）。
- 認領用 `claim_audit_row`：被認領的那一列之後可由 `nothing else is written` 扣除，一列只能被認領一次。

使用方式（與 steps.py、outcome.py 相同）：

    from tests.steps.common.audit_row import *   # noqa: F401,F403
"""
from __future__ import annotations

from pytest_bdd import parsers, then

from app.core import session as session_core
from tests.steps.common.steps import claim_audit_row


def session_owner_name(client, db) -> str:
    """發出請求的 session 的主人。沒有 cookie 或 session 已失效時不猜，直接讓斷言失敗。"""
    token = client.cookies.get(session_core.SESSION_COOKIE)
    actor = session_core.actor_for_token(db, token) if token else None
    db.rollback()
    assert actor is not None, "要有已登入的 session 才知道稽核的行為者是誰"
    return actor.name


def check_audit_row_written(recorder, client, db, type_: str) -> None:
    """動作新增了一列 `type_` 的稽核，行為者是 session 的主人；並把那一列記為「已斷言」。"""
    claim_audit_row(recorder, db, type_, session_owner_name(client, db))


@then(parsers.re(r'an audit row "(?P<type_>[A-Z_]+)" is written$'))
def _audit_row_written(recorder, client, db, type_):
    check_audit_row_written(recorder, client, db, type_)
