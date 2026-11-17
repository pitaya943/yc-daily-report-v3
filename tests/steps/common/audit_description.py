"""`the audit description contains "<text>"` 的共用步驟（D-094）。

原本由 T-201 定義在 tests/steps/RPT-F01/rpt_f01_steps.py：只看 `REPORT_CREATE`，而且要求「全庫恰 1 列 REPORT_CREATE」。
步驟是全域註冊的，RPT-F02 的 RPT-R11（新增的稽核是 `REPORT_UPDATE`）與 M3 的 IAM-F06 也用同一句，所以搬到這裡並一般化。

使用方式（與 steps.py、outcome.py 相同）：

    from tests.steps.common.audit_description import *   # noqa: F401,F403

新定義：這個動作恰新增 1 列稽核，而且那一列的說明包含指定文字，不限類型。
拿掉的只有 T-201 加嚴的「全庫恰 1 列 REPORT_CREATE」：對 RPT-R07 而言，scenario 從乾淨的資料庫開始、送出後唯一新增的
稽核就是 REPORT_CREATE，所以「恰新增 1 列、說明含『共 3 人作業』」檢查的是同一件事。
"""
from __future__ import annotations

from pytest_bdd import parsers, then

from tests.steps.common.steps import new_audit_rows


@then(parsers.parse('the audit description contains "{text}"'))
def _audit_description_contains(recorder, db, text):
    added = new_audit_rows(recorder)
    assert len(added) == 1, f"這個動作應該恰新增 1 列稽核，實際 {len(added)} 列：{added}"
    with db.cursor() as cur:
        cur.execute("select x::text, type, description from yc_v3.audit_log x")
        rows = [r for r in cur.fetchall() if r[0] == added[0]]
    db.rollback()
    assert len(rows) == 1, f"新增的稽核列在資料庫裡找不到：{added}"
    _, type_, description = rows[0]
    assert text in description, f"稽核（{type_}）的說明應含「{text}」，實際「{description}」"
