"""稽核寫入（spec/appendix-c-audit-types.md）。

    audit.write(actor, type, description)              # 自己開連線並提交
    audit.write(actor, type, description, conn=conn)   # 寫進呼叫端的 transaction，由呼叫端提交

兩種模式的取捨：
- 業務動作成功：稽核要和業務資料「同生同死」，所以傳 `conn`，同一個 transaction 一起提交或回滾，
  不會有「資料改了卻沒有稽核」或「沒改卻有稽核」。
- 被拒絕的動作（ACCESS_DENIED）：業務 transaction 會回滾，但稽核必須留下，所以不傳 `conn`，
  用獨立連線寫入並立刻提交。
時間來自 app/core/clock.py（Asia/Taipei），不讓資料庫自己取時間。
"""
from __future__ import annotations

import psycopg

from app.core.actor import Actor
from app.core.clock import clock
from app.core.db import connect

# spec/appendix-c-audit-types.md 的 37 種類型。tests/unit/core/test_audit.py 會從 spec 解析並逐一比對；
# migration 0002 的 check 約束是同一份清單（資料庫那一側的最後防線）。
# 已移除、不得出現：ACCOUNT_DELETE、ACCOUNT_DEACTIVATE、ACCOUNT_REACTIVATE。
AUDIT_TYPES: frozenset[str] = frozenset(
    {
        # 回報
        "REPORT_CREATE", "REPORT_UPDATE", "REPORT_DELETE", "REPORT_CONFIRM", "REPORT_REJECT", "REPORT_UNCONFIRM",
        # 帳戶
        "ACCOUNT_CREATE", "ACCOUNT_UPDATE", "ACCOUNT_ARCHIVE", "ACCOUNT_RESTORE", "ACCOUNT_ROLE_CHANGE",
        "ACCOUNT_LOCKOUT", "PASSWORD_CHANGE", "BANK_REVEAL",
        # 材料
        "MATERIAL_REQUEST", "MATERIAL_CANCEL", "MATERIAL_ADD", "MATERIAL_UPDATE", "MATERIAL_DELETE",
        "MATERIAL_APPROVE", "MATERIAL_REJECT", "MATERIAL_IMPORT", "MATERIAL_RESET", "MATERIAL_KEEP_A",
        "MATERIAL_SYNC_B",
        # 薪資與設定
        "SYSTEM_CONFIG", "RETENTION_SET", "RETENTION_RESET", "RETENTION_YEAR_END",
        # 流水帳
        "LEDGER_CREATE", "LEDGER_UPDATE", "LEDGER_DELETE", "LEDGER_SETTLE", "LEDGER_VOID",
        # 橫切
        "EXPORT", "FILE_DOWNLOAD", "ACCESS_DENIED",
    }
)


class UnknownAuditType(ValueError):
    """類型不在附錄 C。這是程式錯誤（不是使用者輸入），所以丟一般例外而不是結果類別。"""


_INSERT = (
    "insert into yc_v3.audit_log(occurred_at, actor_account_id, actor_name, type, description) "
    "values (%s, %s, %s, %s, %s)"
)


def write(actor: Actor, type: str, description: str, *, conn: psycopg.Connection | None = None) -> None:  # noqa: A002
    if type not in AUDIT_TYPES:
        raise UnknownAuditType(f"audit type {type!r} is not in spec/appendix-c-audit-types.md")
    if not description or not description.strip():
        raise ValueError("audit description must not be empty")
    params = (clock.now(), actor.id, actor.name, type, description)
    if conn is not None:
        conn.execute(_INSERT, params)
        return
    with connect() as own:  # 離開 with 時提交；例外時回滾
        own.execute(_INSERT, params)
