"""所有 feature 共用的步驟與 fixture（T-003 完成條件 4、5）。

其他 feature 的步驟檔這樣使用：

    from tests.steps.common.steps import *   # noqa: F401,F403   (fixture 與共用步驟)

    @when(...)
    def _act(recorder, client):
        recorder.perform(lambda: client.post("/some/path", json={...}))   # ← 動作一律走 recorder

設計：
- 「nothing is written」要比對動作**前後**的資料庫內容，不能只看回應（AGENTS.md 不可違反 #5）。
  所以動作要交給 `recorder.perform()`：它在動作前、後各拍一張 yc_v3 全部資料表的快照（每列轉成文字、排序）。
  快照含 audit_log，因此 FORBIDDEN 那個多出來的 ACCESS_DENIED 列也會被看見；
  該情況用 `nothing is written except an audit row ...`，不能用 `nothing is written`。
- 快照走獨立連線（`db` fixture），看的是已提交的資料，所以應用程式在別條連線寫入也抓得到。
- 錯誤字串逐字比對；HTTP status 對照 spec/README.md 的表（測試從 spec 解析，不是另抄一份）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pytest_bdd import parsers, then

from app.main import create_app
from tests.steps.common.spec_tables import outcome_http_table

Snapshot = dict[str, list[str]]


def take_snapshot(db) -> Snapshot:
    """yc_v3 每張表（schema_migrations 除外）的全部內容：{表名: 排序後的列文字}。"""
    with db.cursor() as cur:
        cur.execute(
            "select tablename from pg_tables where schemaname = 'yc_v3' and tablename <> 'schema_migrations' order by 1"
        )
        tables = [r[0] for r in cur.fetchall()]
        snap: Snapshot = {}
        for t in tables:
            # 表名來自 pg_tables，不是使用者輸入；用 quote_ident 的結果等價於下面的雙引號
            cur.execute(f'select x::text from yc_v3."{t}" x order by 1')
            snap[t] = [r[0] for r in cur.fetchall()]
    db.rollback()  # 不要讓快照的連線一直握著 transaction（會擋住下一個測試的 truncate）
    return snap


def diff(before: Snapshot, after: Snapshot) -> dict[str, dict[str, list[str]]]:
    """{表名: {"added": [...], "removed": [...]}}，只列有變動的表。"""
    out: dict[str, dict[str, list[str]]] = {}
    for t in sorted(set(before) | set(after)):
        b, a = list(before.get(t, [])), list(after.get(t, []))
        added, removed = list(a), []
        for row in b:
            if row in added:
                added.remove(row)
            else:
                removed.append(row)
        if added or removed:
            out[t] = {"added": added, "removed": removed}
    return out


@dataclass
class Recorder:
    """記下一次動作的回應與前後快照。"""

    db: object
    response: object = None
    before: Snapshot | None = None
    after: Snapshot | None = None
    _performed: bool = field(default=False, repr=False)

    def perform(self, action):
        self.before = take_snapshot(self.db)
        self.response = action()
        self.after = take_snapshot(self.db)
        self._performed = True
        return self.response

    def changes(self) -> dict[str, dict[str, list[str]]]:
        assert self._performed, "動作沒有透過 recorder.perform() 執行，無法比對前後的資料庫內容"
        return diff(self.before, self.after)


@pytest.fixture
def client() -> TestClient:
    # raise_server_exceptions=False：未預期的例外要變成 500 讓斷言看見，而不是在測試裡直接炸掉
    return TestClient(create_app(), raise_server_exceptions=False)


@pytest.fixture
def recorder(db) -> Recorder:
    return Recorder(db)


# ───────────────────────── 共用步驟 ─────────────────────────


def check_rejected(recorder: Recorder, outcome: str, message: str | None) -> None:
    table = outcome_http_table()
    assert outcome in table, f"{outcome} 不是 spec/README.md 的結果類別"
    r = recorder.response
    assert r is not None, "沒有回應可檢查"
    assert r.status_code == table[outcome], f"HTTP status 應為 {table[outcome]}，實際 {r.status_code}"
    body = r.json()
    assert body["outcome"] == outcome, f"結果類別應為 {outcome}，實際 {body.get('outcome')}"
    assert body["message"] == message, f"錯誤字串應為 {message!r}，實際 {body.get('message')!r}"


@then(parsers.re(r'the request is rejected as (?P<outcome>[A-Z_]+) with message "(?P<message>.+)"'))
def _rejected_with_message(recorder, outcome, message):
    check_rejected(recorder, outcome, message)


@then(parsers.re(r"the request is rejected as (?P<outcome>[A-Z_]+)"))
def _rejected(recorder, outcome):
    # spec 沒有為這個情況寫錯誤字串，所以斷言「沒有字串」；不替 spec 發明訊息。
    check_rejected(recorder, outcome, None)


def check_nothing_written(recorder: Recorder) -> None:
    changes = recorder.changes()
    assert not changes, f"資料庫在動作前後不一致：{changes}"


@then("nothing is written")
@then("nothing else is written")
def _nothing_written(recorder):
    check_nothing_written(recorder)


def new_audit_rows(recorder: Recorder) -> list[str]:
    return recorder.changes().get("audit_log", {}).get("added", [])


def audit_rows_matching(recorder: Recorder, db, type_: str, actor: str | None = None) -> list[tuple]:
    """動作新增的 audit_log 列中，符合類型（與行為者）的那些。"""
    added = set(new_audit_rows(recorder))
    with db.cursor() as cur:
        cur.execute("select x::text, type, actor_name from yc_v3.audit_log x")
        rows = [r for r in cur.fetchall() if r[0] in added]
    db.rollback()
    return [r for r in rows if r[1] == type_ and (actor is None or r[2] == actor)]


@then(parsers.re(r'an audit row "(?P<type_>[A-Z_]+)" is written with actor "(?P<actor>[^"]+)"'))
def _audit_row_with_actor(recorder, db, type_, actor):
    assert recorder.changes().get("audit_log", {}).get("removed", []) == [], "稽核紀錄不可被刪除或修改"
    assert audit_rows_matching(recorder, db, type_, actor), (
        f'沒有新增 actor 為 "{actor}" 的 "{type_}" 稽核列；新增的列：{new_audit_rows(recorder)}'
    )


@then("no audit row is written")
def _no_audit_row(recorder):
    assert recorder.changes().get("audit_log") is None, f"不該有稽核列：{recorder.changes().get('audit_log')}"


@then(parsers.re(r'nothing is written except an audit row "(?P<type_>[A-Z_]+)" with actor "(?P<actor>[^"]+)"'))
def _nothing_except_audit_row(recorder, db, type_, actor):
    changes = recorder.changes()
    others = {t: c for t, c in changes.items() if t != "audit_log"}
    assert not others, f"稽核以外的資料表有變動：{others}"
    audit = changes.get("audit_log", {"added": [], "removed": []})
    assert audit["removed"] == [], "稽核紀錄不可被刪除或修改"
    assert len(audit["added"]) == 1, f"應該只新增 1 列稽核，實際 {len(audit['added'])} 列：{audit['added']}"
    assert audit_rows_matching(recorder, db, type_, actor), f'新增的稽核列不是 "{type_}" / "{actor}"：{audit["added"]}'
