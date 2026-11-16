"""登入的規則（IAM-F01）。"""
from __future__ import annotations

import psycopg

from app.core.actor import Role
from app.core.outcomes import Outcome, OutcomeError
from app.core.session import IssuedSession, issue_session, landing_path_for, verify_password
from app.modules.iam.sign_in import repo

# spec/appendix-b-fields.md「登入帳戶」「登入密碼」的錯誤字串，逐字照抄
MSG_PICK_ACCOUNT = "請選擇帳戶"
MSG_WRONG_PASSWORD = "密碼錯誤，請重試"

GROUPS = ("admin", "west", "south")


def names_for_group(conn: psycopg.Connection, group: str) -> list[str]:
    """IAM-R01：群組內未封存帳戶的名稱。群組不在白名單內就是 INVALID（沒有這個動作）；spec 沒寫字串，所以沒有 message。"""
    if group not in GROUPS:
        raise OutcomeError(Outcome.INVALID)
    return repo.names_in_group(conn, group)


def sign_in(conn: psycopg.Connection, name: str | None, password: str | None, group: str | None = None) -> tuple[IssuedSession, str]:
    """驗證並發出 session，回傳（session, 落地頁路徑）。成功時才寫資料庫並提交；任何拒絕都不寫任何東西。

    - 沒有帳戶名稱（缺少或空白）：INVALID「請選擇帳戶」。不替缺少的值補預設值。
    - 有給群組時，帳戶要在該群組的名單內，否則 INVALID「請選擇帳戶」。
    - 密碼錯誤、查無帳戶、帳戶已封存、帳戶還沒設定密碼、沒給密碼：全部是同一個 UNAUTHENTICATED「密碼錯誤，請重試」
      （IAM-R03）。每一條路徑都付出一次完整的 scrypt 成本（見 verify_password），不能從回應時間分辨。
    """
    if not name or not name.strip():
        raise OutcomeError(Outcome.INVALID, MSG_PICK_ACCOUNT)
    if group is not None and (group not in GROUPS or name not in repo.names_in_group(conn, group)):
        raise OutcomeError(Outcome.INVALID, MSG_PICK_ACCOUNT)

    account = repo.find_account(conn, name)
    usable = account is not None and not account.archived
    stored = account.password_hash if usable else None
    password_ok = verify_password(password or "", stored)  # 不論帳戶狀態都要執行，時間才一致
    if not (password_ok and usable):
        raise OutcomeError(Outcome.UNAUTHENTICATED, MSG_WRONG_PASSWORD)

    issued = issue_session(conn, account.id)
    conn.commit()
    return issued, landing_path_for(Role(account.role))
