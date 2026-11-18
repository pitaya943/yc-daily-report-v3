"""D-127：管理員重設密碼也有密碼確認欄（T-308 完成條件 14）；D-129／D-140：沒有資料斷言步驟的拒絕 scenario 的補充測試。

每個測試只放一個錯誤原因（pitfall #32）。拒絕都檢查三件事：結果類別、完整錯誤字串、資料沒有任何變動。
比規格更嚴格的斷言（PR 說明逐條列出，D-091）：重設的確認欄缺少、為空、不一致都是 `INVALID`「兩次輸入的密碼不一致」，
而且整個資料庫不變（密碼沒換、session 沒結束）；IAM-R30 的 Kuei scenario 只寫結果類別與字串，這裡補上「唯一的變動是多一次失敗」。
"""
from __future__ import annotations

from urllib.parse import urlencode

import iam_f06_steps as f06
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, session_rows, set_password, sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected

MISMATCH = "兩次輸入的密碼不一致"
LENGTH = "密碼長度須為 6 至 30 個字"


def signed_in(db, name: str) -> TestClient:
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert sign_in_with_correct_password(client, db, name).status_code == 303
    return client


def reset(db, admin, body: str) -> Recorder:
    recorder = Recorder(db)
    path = f06.RESET_PATH.format(id=f06.account_id(db, "Wen"))
    recorder.perform(
        lambda: admin.post(path, content=body, headers={"content-type": "application/x-www-form-urlencoded", f06.CSRF_HEADER: f06.csrf_token(admin, db)})
    )
    return recorder


@pytest.mark.parametrize(
    "body",
    [
        urlencode({"new_password": "newpass1", "password_confirm": "newpass2"}),
        urlencode({"new_password": "newpass1", "password_confirm": ""}),
        urlencode({"new_password": "newpass1"}),
    ],
    ids=["different", "empty", "missing"],
)
def test_a_reset_whose_confirmation_does_not_match_is_invalid_and_changes_nothing(db, body):
    admin = signed_in(db, "Admin1")
    set_password(db, "Wen")
    wen = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(wen, "Wen", TEST_PASSWORD).status_code == 303
    r = reset(db, admin, body)
    check_rejected(r, "INVALID", MISMATCH)
    check_nothing_written(r)  # 密碼沒換、Wen 的 session 沒結束、沒有稽核
    assert len(session_rows(db, "Wen")) == 1


def test_a_reset_with_a_bad_length_and_a_matching_confirmation_is_a_length_error(db):
    """確認欄相符時，長度不合仍是長度的錯誤字串（檢查順序與自己改密碼相同：確認 → 長度）。"""
    r = reset(db, signed_in(db, "Admin1"), urlencode({"new_password": "short", "password_confirm": "short"}))
    check_rejected(r, "INVALID", LENGTH)
    check_nothing_written(r)


def test_a_reset_with_a_matching_confirmation_succeeds(db):
    r = reset(db, signed_in(db, "Admin1"), urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}))
    assert r.response.status_code == 200
    fresh = TestClient(create_app(), raise_server_exceptions=False)
    assert post_sign_in(fresh, "Wen", "newpass1").status_code == 303


def test_the_owners_wrong_current_password_is_counted_and_nothing_else_changes(db):
    """IAM-R30 的 Kuei scenario 只寫結果類別與字串（D-129）：補上「唯一的變動是多一次失敗」。"""
    owner = signed_in(db, "Kuei")
    r = Recorder(db)
    fields = {"current_password": "wrong", "new_password": "newpass1", "password_confirm": "newpass1"}
    r.perform(lambda: f06.post_form(owner, db, f06.OWN_PASSWORD_PATH, fields))
    check_rejected(r, "INVALID", "目前密碼不正確")
    assert set(r.changes()) == {"sign_in_failures"} and len(r.changes()["sign_in_failures"]["added"]) == 1
    assert SESSION_COOKIE in owner.cookies
