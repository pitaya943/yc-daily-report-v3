"""日報的資料存取（migration 0005：reports、report_items、report_crew）。

只有 SQL，沒有規則：驗證與權限在 service.py。所有函式都用呼叫端給的連線，**不自己提交**，
由呼叫端決定 transaction 的範圍（業務資料與稽核同生同死，見 app/core/audit.py）。
時間由呼叫端傳入（來自 app/core/clock.py），這裡不讀時鐘。

給 T-202（編輯、刪除）與 T-203（歷史、匯出）import：

    get_report, list_reports, replace_report_content, set_report_status, delete_report,
    count_own_reports, lock_submitter, get_account, eligible_collaborators, eligible_collaborator_ids
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import psycopg


@dataclass(frozen=True)
class Account:
    id: int
    name: str
    role: str
    zone: str
    big_meter: bool
    archived: bool


@dataclass(frozen=True)
class Report:
    id: int
    submitter_id: int
    submitter_name: str
    report_date: date
    catalogue: str
    status: str
    items: dict[str, int]  # 工項代碼 → 0.1 只（tenths）；只有送出時有帶的工項
    crew: list[tuple[int, str]]  # 共同作業者（不含提交者），依提交者選擇的順序：(帳戶 id, 名稱)
    custom_name: str | None = None  # 自訂工項（REV-R20，D-086）：T-201 不寫入；三者同為 None 或同有值
    custom_tenths: int | None = None
    custom_price: int | None = None
    created_at: datetime | None = field(default=None, compare=False)
    updated_at: datetime | None = field(default=None, compare=False)


# ───────────────────────── 帳戶 ─────────────────────────


def get_account(conn: psycopg.Connection, account_id: int) -> Account | None:
    row = conn.execute(
        "select id, name, role, zone, big_meter, archived from yc_v3.accounts where id = %s", (account_id,)
    ).fetchone()
    return None if row is None else Account(*row)


def eligible_collaborators(conn: psycopg.Connection, submitter: Account) -> list[tuple[int, str]]:
    """RPT-R05：同區、同類型（大表旗標相同）、未封存的 USER，不含提交者本人。依名稱排序，給表單的選單用。"""
    rows = conn.execute(
        "select id, name from yc_v3.accounts "
        "where role = 'USER' and not archived and zone = %s and big_meter = %s and id <> %s order by name",
        (submitter.zone, submitter.big_meter, submitter.id),
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def eligible_collaborator_ids(conn: psycopg.Connection, submitter: Account, candidate_ids: list[int]) -> set[int]:
    """candidate_ids 之中符合 RPT-R05 資格的那些（不存在的 id、封存者、不同區或類型、非 USER、提交者自己都不在內）。"""
    if not candidate_ids:
        return set()
    rows = conn.execute(
        "select id from yc_v3.accounts "
        "where id = any(%s) and role = 'USER' and not archived and zone = %s and big_meter = %s and id <> %s",
        (candidate_ids, submitter.zone, submitter.big_meter, submitter.id),
    ).fetchall()
    return {r[0] for r in rows}


# ───────────────────────── 每日上限（RPT-R04）─────────────────────────


def lock_submitter(conn: psycopg.Connection, submitter_id: int) -> None:
    """鎖住提交者的 accounts 列，直到這個 transaction 結束。

    每日上限是「先數、再寫」，兩個同時進來的請求若都先數到 2 就會各自寫入，變成 4 筆。
    先取得這把鎖，同一個人的並行送出就排隊：第二個請求要等第一個提交之後才數，會數到 3。
    `for no key update` 不會擋住別的交易對這一列的外鍵檢查（sessions、reports 參照 accounts），
    也不會擋住不同人的送出。取捨：鎖的是「人」，所以同一個人不同日期的送出也會排隊，這在每人每日數筆的量級可以忽略。
    """
    conn.execute("select 1 from yc_v3.accounts where id = %s for no key update", (submitter_id,))


def count_own_reports(conn: psycopg.Connection, submitter_id: int, report_date: date) -> int:
    """這個人在這一天自己送出、且仍存在的回報數（不分狀態；共同作業者不算）。"""
    return conn.execute(
        "select count(*) from yc_v3.reports where submitter_id = %s and report_date = %s", (submitter_id, report_date)
    ).fetchone()[0]


# ───────────────────────── 寫入 ─────────────────────────


def insert_report(
    conn: psycopg.Connection,
    *,
    submitter_id: int,
    report_date: date,
    catalogue: str,
    status: str,
    now: datetime,
    items: dict[str, int],
    crew_ids: list[int],
) -> int:
    """新增一張回報（含工項數量與共同作業者），回傳 id。`crew_ids` 的順序就是存下的順序（position 從 1 起）。"""
    report_id = conn.execute(
        "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at) "
        "values (%s, %s, %s, %s, %s, %s) returning id",
        (submitter_id, report_date, catalogue, status, now, now),
    ).fetchone()[0]
    _insert_items(conn, report_id, items)
    _insert_crew(conn, report_id, crew_ids)
    return report_id


def _insert_items(conn: psycopg.Connection, report_id: int, items: dict[str, int]) -> None:
    for code, tenths in items.items():
        conn.execute(
            "insert into yc_v3.report_items(report_id, item_code, tenths) values (%s, %s, %s)", (report_id, code, tenths)
        )


def _insert_crew(conn: psycopg.Connection, report_id: int, crew_ids: list[int]) -> None:
    for position, account_id in enumerate(crew_ids, start=1):
        conn.execute(
            "insert into yc_v3.report_crew(report_id, position, account_id) values (%s, %s, %s)",
            (report_id, position, account_id),
        )


def replace_report_content(
    conn: psycopg.Connection, report_id: int, *, items: dict[str, int], crew_ids: list[int], status: str, now: datetime
) -> None:
    """編輯（T-202）：以新的工項數量與作業小組取代舊的，並更新狀態與 updated_at。回報日期與工項組不變（AD-8、AD-4）。"""
    conn.execute("delete from yc_v3.report_items where report_id = %s", (report_id,))
    conn.execute("delete from yc_v3.report_crew where report_id = %s", (report_id,))
    _insert_items(conn, report_id, items)
    _insert_crew(conn, report_id, crew_ids)
    conn.execute("update yc_v3.reports set status = %s, updated_at = %s where id = %s", (status, now, report_id))


def set_report_status(conn: psycopg.Connection, report_id: int, status: str, now: datetime) -> None:
    conn.execute("update yc_v3.reports set status = %s, updated_at = %s where id = %s", (status, now, report_id))


def delete_report(conn: psycopg.Connection, report_id: int) -> bool:
    """刪除一張回報（工項與作業小組隨之刪除）。回傳是否真的刪了一列。刪除後這一天的額度就釋放了（RPT-R04）。"""
    return conn.execute("delete from yc_v3.reports where id = %s", (report_id,)).rowcount == 1


# ───────────────────────── 讀取 ─────────────────────────

_REPORT_COLUMNS = (
    "r.id, r.submitter_id, a.name, r.report_date, r.catalogue, r.status, "
    "r.custom_name, r.custom_tenths, r.custom_price, r.created_at, r.updated_at"
)


def _hydrate(conn: psycopg.Connection, rows: list[tuple]) -> list[Report]:
    if not rows:
        return []
    ids = [r[0] for r in rows]
    items: dict[int, dict[str, int]] = {i: {} for i in ids}
    for report_id, code, tenths in conn.execute(
        "select report_id, item_code, tenths from yc_v3.report_items where report_id = any(%s) order by report_id, item_code", (ids,)
    ):
        items[report_id][code] = tenths
    crew: dict[int, list[tuple[int, str]]] = {i: [] for i in ids}
    for report_id, account_id, name in conn.execute(
        "select c.report_id, c.account_id, a.name from yc_v3.report_crew c join yc_v3.accounts a on a.id = c.account_id "
        "where c.report_id = any(%s) order by c.report_id, c.position",
        (ids,),
    ):
        crew[report_id].append((account_id, name))
    return [
        Report(
            id=r[0], submitter_id=r[1], submitter_name=r[2], report_date=r[3], catalogue=r[4], status=r[5],
            items=items[r[0]], crew=crew[r[0]], custom_name=r[6], custom_tenths=r[7], custom_price=r[8],
            created_at=r[9], updated_at=r[10],
        )
        for r in rows
    ]


def get_report(conn: psycopg.Connection, report_id: int) -> Report | None:
    rows = conn.execute(
        f"select {_REPORT_COLUMNS} from yc_v3.reports r join yc_v3.accounts a on a.id = r.submitter_id where r.id = %s", (report_id,)
    ).fetchall()
    found = _hydrate(conn, rows)
    return found[0] if found else None


def list_reports(
    conn: psycopg.Connection,
    *,
    submitter_id: int | None = None,
    collaborator_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
) -> list[Report]:
    """依條件列出回報，日期新到舊、同日 id 大到小。`submitter_id` 與 `collaborator_id` 同時給時兩者取聯集
    （「我的歷史」包含我自己送出的與我是共同作業者的）；都不給就不限人。"""
    where, params = [], []
    if submitter_id is not None and collaborator_id is not None:
        where.append("(r.submitter_id = %s or exists (select 1 from yc_v3.report_crew c where c.report_id = r.id and c.account_id = %s))")
        params += [submitter_id, collaborator_id]
    elif submitter_id is not None:
        where.append("r.submitter_id = %s")
        params.append(submitter_id)
    elif collaborator_id is not None:
        where.append("exists (select 1 from yc_v3.report_crew c where c.report_id = r.id and c.account_id = %s)")
        params.append(collaborator_id)
    if date_from is not None:
        where.append("r.report_date >= %s")
        params.append(date_from)
    if date_to is not None:
        where.append("r.report_date <= %s")
        params.append(date_to)
    if status is not None:
        where.append("r.status = %s")
        params.append(status)
    clause = ("where " + " and ".join(where)) if where else ""
    rows = conn.execute(
        f"select {_REPORT_COLUMNS} from yc_v3.reports r join yc_v3.accounts a on a.id = r.submitter_id {clause} "
        "order by r.report_date desc, r.id desc",
        params,
    ).fetchall()
    return _hydrate(conn, rows)
