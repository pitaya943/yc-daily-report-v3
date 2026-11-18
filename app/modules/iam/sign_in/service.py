"""登入的規則（IAM-F01），以及掛在它上面的鎖定與頻率限制（IAM-F02，規則在 sign_in_lockout_and_rate_limit/service.py）。"""
from __future__ import annotations

import psycopg

from app.core.actor import Role
from app.core.outcomes import Outcome, OutcomeError
from app.core.session import IssuedSession, issue_session, landing_path_for, verify_password
from app.modules.iam.sign_in import repo
from app.modules.iam.sign_in_lockout_and_rate_limit import service as lockout

# spec/appendix-b-fields.md「登入帳戶」「登入密碼」的錯誤字串，逐字照抄
MSG_PICK_ACCOUNT = "請選擇帳戶"
MSG_WRONG_PASSWORD = "密碼錯誤，請重試"

GROUPS = ("admin", "west", "south")


def names_for_group(conn: psycopg.Connection, group: str) -> list[str]:
    """IAM-R01：群組內未封存帳戶的名稱。群組不在白名單內就是 INVALID（沒有這個動作）；spec 沒寫字串，所以沒有 message。"""
    if group not in GROUPS:
        raise OutcomeError(Outcome.INVALID)
    return repo.names_in_group(conn, group)


def sign_in(
    conn: psycopg.Connection, name: str | None, password: str | None, group: str | None = None, *, client_address: str
) -> tuple[IssuedSession, str]:
    """驗證並發出 session，回傳（session, 落地頁路徑）。成功時才發出 session；被拒絕時不發。

    順序有意義（每一步都是「更便宜的先擋」，而且被擋掉的請求不留下任何資料，見 lockout 的 service.py）：
    1. 來源位址超過頻率（只讀）→ RATE_LIMITED。
    2. 沒有帳戶名稱（缺少或空白）：INVALID「請選擇帳戶」。不替缺少的值補預設值。
    3. 有給群組時，帳戶要在該群組的名單內，否則 INVALID「請選擇帳戶」。
    4. 帳戶存在且未封存，而且鎖定中 → LOCKED（連正確的密碼也是；不做 scrypt、不寫任何東西）。
    5. 記下這次嘗試（鎖內再檢查頻率）。之後才做 scrypt。
    6. 密碼錯誤、查無帳戶、帳戶已封存、帳戶還沒設定密碼、沒給密碼：全部是同一個 UNAUTHENTICATED「密碼錯誤，請重試」
       （IAM-R03）。每一條路徑都付出一次完整的 scrypt 成本（見 verify_password），不能從回應時間分辨。
       只有「帳戶存在且未封存」才累計失敗次數；第 5 次改成 LOCKED 並寫 ACCOUNT_LOCKOUT。
    7. 比對通過後、發出 session 前，在帳戶列的鎖內重新確認雜湊沒變（D-141）；變了與密碼錯誤相同。
    """
    lockout.ensure_not_rate_limited(conn, client_address)
    if not name or not name.strip():
        raise OutcomeError(Outcome.INVALID, MSG_PICK_ACCOUNT)
    if group is not None and (group not in GROUPS or name not in repo.names_in_group(conn, group)):
        raise OutcomeError(Outcome.INVALID, MSG_PICK_ACCOUNT)

    account = repo.find_account(conn, name)
    usable = account is not None and not account.archived
    if usable:
        lockout.ensure_not_locked(conn, account.id)
    lockout.record_attempt(conn, client_address)

    stored = account.password_hash if usable else None
    password_ok = verify_password(password or "", stored)  # 不論帳戶狀態都要執行，時間才一致
    if not (password_ok and usable):
        if usable:
            lockout.record_failure(conn, account.id, name)  # 第 5 次在這裡改丟 LOCKED
        raise OutcomeError(Outcome.UNAUTHENTICATED, MSG_WRONG_PASSWORD)

    # D-141（IAM-R33 的競爭）：scrypt 在任何鎖之外執行，期間這個帳戶可能剛改了密碼或被重設（並結束了它的 session）。
    # 發出 session 之前，先鎖住帳戶列並重讀雜湊：與比對時的不同，代表比對用的是已被輪替掉的密碼，
    # 與密碼錯誤相同處理（UNAUTHENTICATED、記一次失敗、不發 session）。鎖的順序固定是「帳戶列 → 帳戶的 advisory lock」，
    # 與改密碼一致（password_change_and_reset/service.py），所以不會互相死結。
    if repo.lock_password_hash(conn, account.id) != stored:
        conn.rollback()  # 放掉帳戶列的鎖；record_failure 自己取帳戶的 advisory lock 並提交
        lockout.record_failure(conn, account.id, name)
        raise OutcomeError(Outcome.UNAUTHENTICATED, MSG_WRONG_PASSWORD)
    lockout.begin_success(conn, account.id)  # 確認沒被鎖定，並清掉失敗次數
    issued = issue_session(conn, account.id)
    conn.commit()
    return issued, landing_path_for(Role(account.role))
