"""RPT-F03 歷史與匯出的步驟（由同目錄的 conftest.py 註冊成全域 plugin）。

設計：
- 請求走真的 HTTP（TestClient）；動作一律走 `recorder.perform`，所以「資料沒有變動」比對的是動作前後整個資料庫。
- Given 直接寫資料庫（ticket 完成條件 6）：回報、CONFIRMED／REJECTED、自訂工項都不經過產品的端點。
- 讀頁面用 HTMLParser 取出 `<tr data-report-id>` 的列；讀匯出檔用 openpyxl（D-087）。期望的欄位從
  spec/appendix-a-catalogues.md 解析，不抄進測試。
- 共用步驟（outcome、rejected、audit、signed in）在 tests/steps/common/，這裡不重新定義（pitfall #26）；
  新增步驟前已 grep 過同文字（見 PR 說明）。
- 步驟文字一律用 `parsers.re` 與 `[^"]+`：`parse` 的 `{x}` 會跨過引號，「…dated "A" with collaborator "B"」
  會被較短的步驟吃掉。
"""
from __future__ import annotations

import io
import re
from html.parser import HTMLParser
from urllib.parse import urlencode

import openpyxl
import pytest
from pytest_bdd import given, parsers, then, when

from app.core.clock import clock
from tests.steps.common.outcome import *  # noqa: F401,F403  (the outcome is ...)
from tests.steps.common.session import *  # noqa: F401,F403  ("<name>" is signed in)
from tests.steps.common.session import session_rows, sign_in_with_correct_password
from tests.steps.common.spec_tables import SPEC
from tests.steps.common.steps import *  # noqa: F401,F403  (client、recorder、拒絕、稽核的共用步驟)
from tests.steps.common.steps import check_nothing_written

USER_HISTORY = "/reports/history"
ADMIN_HISTORY = {"ordinary": "/review/history/ordinary", "big-meter": "/review/history/big-meter"}
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# 畫面與匯出的固定用語。規格只給了狀態的三個字串（RPT-R20）；欄位標題不在附錄 B，是 UI 用語（PR 說明列為未解問題）。
STATUS_WORDING = {"PENDING": "未確認", "CONFIRMED": "已確認", "REJECTED": "已駁回"}
COLUMN_LABELS = {"date": "日期", "account": "帳戶", "custom item": "自訂工項", "confirmation": "確認狀態"}
# Given 的「自訂工項」：名稱、數量（0.1 只）、單價
CUSTOM_ITEM = ("Custom pipe", 15, 100)


# ───────────────────────── 輔助 ─────────────────────────


def account_id(db, name: str) -> int:
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        row = cur.fetchone()
    db.rollback()
    assert row is not None, f"背景資料裡沒有帳戶 {name}"
    return row[0]


def catalogue_of(db, name: str) -> str:
    """AD-4：大表旗標開 → BIG_METER；否則依區域。獨立於產品程式再推導一次。"""
    with db.cursor() as cur:
        cur.execute("select zone, big_meter from yc_v3.accounts where name = %s", (name,))
        zone, big = cur.fetchone()
    db.rollback()
    return "BIG_METER" if big else zone


def insert_report(db, submitter: str, date: str, status: str = "PENDING", crew: tuple[str, ...] = (), custom: tuple | None = None,
                  items: dict[str, int] | None = None) -> int:
    """Given 用：直接寫一張回報（含共同作業者、自訂工項、工項數量），不經過產品的送出端點。"""
    now = clock.now()
    # 先查好 id：account_id／catalogue_of 會 rollback，不能夾在待提交的寫入中間
    submitter_id, catalogue = account_id(db, submitter), catalogue_of(db, submitter)
    crew_ids = [account_id(db, who) for who in crew]
    name, tenths, price = custom if custom else (None, None, None)
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at, "
            "custom_name, custom_tenths, custom_price) values (%s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (submitter_id, date, catalogue, status, now, now, name, tenths, price),
        )
        rid = cur.fetchone()[0]
        for position, member_id in enumerate(crew_ids, start=1):
            cur.execute("insert into yc_v3.report_crew(report_id, position, account_id) values (%s, %s, %s)", (rid, position, member_id))
        for code, qty in (items or {}).items():
            cur.execute("insert into yc_v3.report_items(report_id, item_code, tenths) values (%s, %s, %s)", (rid, code, qty))
    db.commit()
    return rid


def ensure_signed_in(client, db, name: str) -> None:
    """這些 scenario 沒有 `"<name>" is signed in`：動作之前先登入，登入寫的 session 才不算動作造成的資料變動。"""
    if not session_rows(db, name):
        response = sign_in_with_correct_password(client, db, name)
        assert response.status_code == 303, f"登入應成功（303），實際 {response.status_code}"


def get(client, path: str, query: dict[str, str] | None = None):
    url = path + (("?" + urlencode(query)) if query else "")
    return client.get(url, follow_redirects=False)


@pytest.fixture
def labels() -> dict[str, int]:
    """scenario 裡的 R1、R2… → 回報 id。"""
    return {}


@pytest.fixture
def last() -> dict:
    """scenario 內最近一次動作的資訊（頁面、篩選、期望的匯出列）。"""
    return {}


class _RowParser(HTMLParser):
    """取出清單的每一列：`<tr data-report-id=…>` 與裡面 class 為 account／label／status／custom 的儲存格文字。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []
        self._row: dict | None = None
        self._cell: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "data-report-id" in a:
            self._row = {"id": int(a["data-report-id"]), "account": "", "label": "", "status": "", "custom": ""}
        elif tag == "td" and self._row is not None:
            self._cell = next((c for c in (a.get("class") or "").split() if c in self._row), None)

    def handle_endtag(self, tag):
        if tag == "td":
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._row is not None and self._cell:
            self._row[self._cell] += data.strip()


def page_rows(response) -> list[dict]:
    assert response.status_code == 200, f"頁面應為 200，實際 {response.status_code}：{response.text[:200]}"
    parser = _RowParser()
    parser.feed(response.text)
    return parser.rows


def labels_of(labels: dict[str, int], rows: list[dict]) -> list[str]:
    by_id = {rid: label for label, rid in labels.items()}
    return [by_id.get(r["id"], f"?{r['id']}") for r in rows]


# ───────────────────────── 附錄 A 與匯出檔的解析 ─────────────────────────

_SECTIONS = {"A.1": "WEST", "A.2": "SOUTH", "A.3": "BIG_METER"}


def spec_display_names(name: str) -> list[str]:
    """spec/appendix-a-catalogues.md 的 A.1～A.3：某工項組依表中順序的顯示名稱。"""
    out: list[str] = []
    current = None
    for line in (SPEC / "appendix-a-catalogues.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^## (A\.\d)\b", line)
        if m:
            current = _SECTIONS.get(m.group(1))
            continue
        row = re.match(r"^\| `([a-z0-9_]+)` \| (.+?) \| (\d+) \| (是|—) \|$", line)
        if row and current == name:
            out.append(row.group(2))
    return out


def union_names(*names: str) -> list[str]:
    """「WEST 與 SOUTH 工項的聯集」：依顯示名稱合併，WEST 的順序在前，SOUTH 才有的接在後面。"""
    out: list[str] = []
    for n in names:
        for display in spec_display_names(n):
            if display not in out:
                out.append(display)
    return out


def read_xlsx(response) -> tuple[list, list[list]]:
    assert response.status_code == 200, f"匯出應為 200，實際 {response.status_code}：{response.text[:200]}"
    assert response.headers["content-type"].split(";")[0] == XLSX_TYPE, f"Content-Type 應為 .xlsx，實際 {response.headers['content-type']}"
    assert re.search(r'filename="[^"]+\.xlsx"', response.headers.get("content-disposition", "")), "應以 .xlsx 檔名下載"
    assert response.content[:2] == b"PK", "不是 zip 容器（.xlsx）"
    ws = openpyxl.load_workbook(io.BytesIO(response.content)).active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    assert rows, "匯出檔沒有標題列"
    return rows[0], rows[1:]


# ───────────────────────── Given ─────────────────────────

_DATE = r'"(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})"'


@given(parsers.re(r'"(?P<name>[^"]+)" submitted (?P<label>R\d+) dated ' + _DATE + r'(?: with (?:collaborator "(?P<collab>[^"]+)"|no collaborator))?$'))
def _submitted(db, labels, name, label, date, collab):
    labels[label] = insert_report(db, name, date, crew=(collab,) if collab else ())


@given(parsers.re(r'"(?P<name>[^"]+)" has one PENDING, one CONFIRMED, and one REJECTED report$'))
def _one_of_each(db, labels, name):
    # 日期由新到舊 = PENDING、CONFIRMED、REJECTED，清單（新到舊）的順序就是 scenario 的「未確認、已確認、已駁回」
    for label, date, status in (("R1", "2026-11-12", "PENDING"), ("R2", "2026-11-11", "CONFIRMED"), ("R3", "2026-11-10", "REJECTED")):
        labels[label] = insert_report(db, name, date, status)


@given(parsers.re(r'reports by "(?P<a>[^"]+)", "(?P<b>[^"]+)", and "(?P<c>[^"]+)"$'))
def _reports_by_three(db, labels, a, b, c):
    for i, who in enumerate((a, b, c), start=1):
        labels[f"R{i}"] = insert_report(db, who, "2026-11-12")


_ROW = re.compile(r'(R\d+) by "([^"]+)" dated "([^"]+)"(?: with (a custom item)| with collaborator "([^"]+)")?')


@given(parsers.re(r"(?P<rows>R\d+ by .+)$"))
def _rows_with_options(db, labels, rows):
    parsed = list(_ROW.finditer(rows))
    assert len(parsed) == rows.count(" by "), f"步驟的文字解析不完整：{rows}"
    for m in parsed:
        label, name, date, custom, collab = m.groups()
        labels[label] = insert_report(db, name, date, crew=(collab,) if collab else (), custom=CUSTOM_ITEM if custom else None)


@given(parsers.re(r'"(?P<name>[^"]+)" has since moved to zone (?P<zone>WEST|SOUTH)$'))
def _has_since_moved(db, name, zone):
    """RPT-R24：回報送出之後帳戶才換區域。直接改帳戶的區域（回報上記下的工項組 `reports.catalogue` 不動）。"""
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set zone = %s where name = %s", (zone, name))
        assert cur.rowcount == 1, f"背景資料裡沒有帳戶 {name}"
    db.commit()


@given(parsers.re(r'"(?P<name>[^"]+)" can see (?P<n>\d+) reports under the current filter$'))
def _can_see(db, labels, last, name, n):
    assert int(n) == 2, "這個 Given 只為 scenario 的 2 張回報準備資料"
    # 篩選：2026-11-05 到 2026-11-15。濾得掉的：日期之外的自己的回報（R3）；看不到的：別人的（R4）
    labels["R1"] = insert_report(db, name, "2026-11-10")
    labels["R2"] = insert_report(db, "Wei", "2026-11-12", crew=(name,))
    labels["R3"] = insert_report(db, name, "2026-11-02")
    labels["R4"] = insert_report(db, "Wei", "2026-11-13")
    last["query"] = {"date_from": "2026-11-05", "date_to": "2026-11-15"}
    last["expected"] = [("2026-11-12", "Wei"), ("2026-11-10", name)]


# ───────────────────────── When ─────────────────────────


def _open(recorder, client, db, last, name: str, path: str, query: dict | None = None):
    ensure_signed_in(client, db, name)
    last.update(name=name, path=path, query=query or last.get("query") or {})
    recorder.perform(lambda: get(client, path, last["query"]))


@when(parsers.re(r'"(?P<name>[^"]+)" opens history$'))
def _opens_history(recorder, client, db, last, name):
    _open(recorder, client, db, last, name, USER_HISTORY)


@when(parsers.re(r'"(?P<name>[^"]+)" opens (?P<page>ordinary|big-meter) history$'))
def _opens_admin_history(recorder, client, db, last, name, page):
    _open(recorder, client, db, last, name, ADMIN_HISTORY[page])


def _filter_query(text: str) -> dict[str, str]:
    if m := re.fullmatch(r"dates (\S+) to (\S+)", text):
        return {"date_from": m.group(1), "date_to": m.group(2)}
    if m := re.fullmatch(r"account (\S+)", text):
        return {"account": m.group(1)}
    if m := re.fullmatch(r"zone (\S+)", text):
        return {"zone": m.group(1)}
    if text == "has custom item":
        return {"has_custom": "1"}
    raise AssertionError(f"不認得的篩選：{text}")


@when(parsers.re(r'"(?P<name>[^"]+)" filters ordinary history by (?P<flt>.+)$'))
def _filters_ordinary(recorder, client, db, last, name, flt):
    _open(recorder, client, db, last, name, ADMIN_HISTORY["ordinary"], _filter_query(flt))


@when(parsers.re(r'"(?P<name>[^"]+)" filters history by (?P<field>date|zone|account) "(?P<value>[^"]*)"$'))
def _filters_history_invalid(recorder, client, db, last, name, field, value):
    query = {"date_from" if field == "date" else field: value}
    _open(recorder, client, db, last, name, ADMIN_HISTORY["ordinary"], query)
    # 比規格嚴：被拒絕的篩選什麼都不寫（結果類別與字串由共用的 Then 斷言；AGENTS.md 不可違反 #5 要求資料不變）
    check_nothing_written(recorder)


@when(parsers.re(r'"(?P<name>[^"]+)" exports history to Excel$'))
def _exports_user(recorder, client, db, last, name):
    _open(recorder, client, db, last, name, USER_HISTORY + "/export")


@when(parsers.re(r'"(?P<name>[^"]+)" exports (?P<page>ordinary|big-meter) history$'))
def _exports_admin(recorder, client, db, last, name, page):
    _open(recorder, client, db, last, name, ADMIN_HISTORY[page] + "/export", {})


# ───────────────────────── Then ─────────────────────────


@then(parsers.re(r'the list is "?(?P<rows>R\d+(?:, R\d+)*)"?(?P<ordered> in that order)?$'))
def _list_is(recorder, labels, rows, ordered):
    # 順序一律斷言（日期新到舊、同日 id 大到小）：scenario 的列表只寫了順序的一種寫法，不能因為沒寫「in that order」就不檢查
    assert labels_of(labels, page_rows(recorder.response)) == rows.split(", ")


@then(parsers.re(r'(?P<label>R\d+) is labelled "(?P<text>[^"]+)"$'))
def _labelled(recorder, labels, label, text):
    row = next((r for r in page_rows(recorder.response) if r["id"] == labels[label]), None)
    assert row is not None, f"清單裡沒有 {label}"
    assert row["label"] == text, f"{label} 的標籤應為 {text!r}，實際 {row['label']!r}"


@then(parsers.re(r"the statuses read (?P<statuses>.+)$"))
def _statuses_read(recorder, statuses):
    expected = re.findall(r'"([^"]+)"', statuses)
    assert [r["status"] for r in page_rows(recorder.response)] == expected
    assert set(expected) <= set(STATUS_WORDING.values())


@then(parsers.re(r"the list contains the reports? of (?P<names>.+) only$"))
def _contains_only(db, recorder, labels, names):
    expected = set(re.findall(r'"([^"]+)"', names))
    rows = page_rows(recorder.response)
    # Given 替每個帳戶各建 1 張：清單必須恰是那幾個帳戶的那幾張，多一張或少一張都不行
    assert len(rows) == len(expected), f"應恰有 {len(expected)} 張回報，實際 {len(rows)} 張"
    assert {r["id"] for r in rows} <= set(labels.values()), "清單出現了不是這個 scenario 建立的回報"
    assert {r["account"] for r in rows} == expected, f"清單的帳戶應為 {expected}，實際 {[r['account'] for r in rows]}"


@then(parsers.re(r"the file is \.xlsx with (?P<n>\d+) data rows$"))
def _xlsx_with_rows(recorder, last, n):
    _, data = read_xlsx(recorder.response)
    assert len(data) == int(n), f"資料列應為 {n}，實際 {len(data)}：{data}"
    assert [(r[0], r[1]) for r in data] == last["expected"], "匯出的列（日期、帳戶）必須恰是篩選後看得到的那些，且順序與頁面相同"
    # 比規格嚴：匯出只多一列 EXPORT 稽核，其他什麼都不寫（稽核的 actor 由共用的 Then 斷言）
    changes = recorder.changes()
    assert set(changes) == {"audit_log"} and len(changes["audit_log"]["added"]) == 1 and not changes["audit_log"]["removed"], changes


@then(parsers.re(r"the columns are (?P<columns>.+)$"))
def _columns_are(recorder, columns):
    header, _ = read_xlsx(recorder.response)
    expected: list[str] = []
    for token in columns.split(", "):
        if token in COLUMN_LABELS:
            expected.append(COLUMN_LABELS[token])
        elif m := re.fullmatch(r"the union of (\w+) and (\w+) items", token):
            expected += union_names(m.group(1), m.group(2))
        elif m := re.fullmatch(r"the (\w+) items", token):
            expected += spec_display_names(m.group(1))
        else:
            raise AssertionError(f"不認得的欄位：{token}")
    assert header == expected, f"欄位不一致：\n實際 {header}\n預期 {expected}"
