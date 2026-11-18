"""登入與密碼輪替的競爭（T-308 完成條件 17，D-141，issue #49）。

問題：登入在帳戶鎖「之外」比對密碼（scrypt 約零點幾秒），之後才發出 session。如果比對通過之後、發出 session 之前，
同一個帳戶剛好改了密碼或被重設（IAM-R33 會結束該帳戶的 session），這次登入還是會留下一個有效的 session——
知道舊密碼的人可以在輪替之後繼續登入。修法：發出 session 前，在帳戶列的鎖內重新確認密碼雜湊沒有變。

測試方式（確定性，不靠運氣的平行）：在登入的 `verify_password` 回傳「通過」之後、登入繼續之前，用另一條連線真的完成一次
改密碼（或管理員重設）。這正好重現「比對之後、發出 session 之前」。每個測試只放一個錯誤原因（pitfall #32）。
比規格更嚴格的斷言（D-091）：輪替之後該帳戶沒有任何有效 session、登入為 `UNAUTHENTICATED`「密碼錯誤，請重試」並記一次失敗。
"""
from __future__ import annotations

import iam_f02_steps as f02
import iam_f06_steps as f06
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.iam.sign_in import service as sign_in_service
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, session_rows, set_password, sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_rejected

WRONG_PASSWORD_MSG = "密碼錯誤，請重試"


def signed_in(db, name: str) -> TestClient:
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert sign_in_with_correct_password(client, db, name).status_code == 303
    return client


def rotate_between_compare_and_session(monkeypatch, rotate) -> None:
    """登入的密碼比對通過之後，立刻執行 `rotate()`（另一條連線的真實請求），再讓登入繼續。只觸發一次。"""
    real = sign_in_service.verify_password
    fired: list[bool] = []

    def verify_then_rotate(password, stored):
        ok = real(password, stored)
        if ok and not fired:
            fired.append(True)
            rotate()
        return ok

    monkeypatch.setattr(sign_in_service, "verify_password", verify_then_rotate)


def test_a_password_change_between_the_compare_and_the_session_leaves_no_new_session(db, monkeypatch):
    device = signed_in(db, "Wen")  # 改密碼的裝置，目前的 session 會保留（IAM-R33）
    attacker = TestClient(create_app(), raise_server_exceptions=False)  # 還知道舊密碼的另一個人
    rotate_between_compare_and_session(
        monkeypatch, lambda: f06.post_form(device, db, f06.OWN_PASSWORD_PATH, {"current_password": TEST_PASSWORD, "new_password": "newpass1", "password_confirm": "newpass1"})
    )
    r = Recorder(db)
    r.perform(lambda: post_sign_in(attacker, "Wen", TEST_PASSWORD))
    check_rejected(r, "UNAUTHENTICATED", WRONG_PASSWORD_MSG)
    assert SESSION_COOKIE not in attacker.cookies
    assert len(session_rows(db, "Wen")) == 1, "只剩改密碼的那台裝置的 session；舊密碼的登入不得留下新的"
    assert f02.failure_row(db, "Wen")[0] == 1, "被拒絕的登入與密碼錯誤相同：記一次失敗"


def test_a_reset_between_the_compare_and_the_session_leaves_no_session_at_all(db, monkeypatch):
    admin = signed_in(db, "Admin1")
    attacker = TestClient(create_app(), raise_server_exceptions=False)
    set_password(db, "Wen")
    wen_id = f06.account_id(db, "Wen")
    rotate_between_compare_and_session(
        monkeypatch, lambda: f06.post_form(admin, db, f06.RESET_PATH.format(id=wen_id), {"new_password": "newpass1", "password_confirm": "newpass1"})
    )
    r = Recorder(db)
    r.perform(lambda: post_sign_in(attacker, "Wen", TEST_PASSWORD))
    check_rejected(r, "UNAUTHENTICATED", WRONG_PASSWORD_MSG)
    assert session_rows(db, "Wen") == [], "管理員重設之後，該帳戶不得有任何有效 session"


def test_without_a_rotation_the_same_flow_still_signs_in(db, monkeypatch):
    """對照組：同一個攔截點，但什麼都沒輪替 → 照常登入成功（沒有誤傷正常登入）。"""
    set_password(db, "Wen")
    attacker = TestClient(create_app(), raise_server_exceptions=False)
    rotate_between_compare_and_session(monkeypatch, lambda: None)
    assert post_sign_in(attacker, "Wen", TEST_PASSWORD).status_code == 303
    assert len(session_rows(db, "Wen")) == 1


def test_simultaneous_sign_ins_and_password_changes_never_deadlock(db):
    """真正平行的壓力檢查：登入成功、登入失敗、改密碼同時進行，鎖的順序（帳戶列 → advisory lock）不得讓資料庫判定死結（500）。
    不斷言誰贏（那取決於排程），只斷言每個請求都得到規格內的結果類別，沒有未預期的 500。"""
    import threading

    set_password(db, "Wen")
    device = signed_in(db, "Wen")
    statuses: list[int] = []
    lock = threading.Lock()

    def run(send) -> None:
        status = send()
        with lock:
            statuses.append(status)

    for round_ in range(4):
        # 每一輪的改密碼都用「目前的密碼」：偶數輪 correct → newpass1、奇數輪 newpass1 → correct，結果不論成功與否都算規格內
        current, new = ("correct", "newpass1") if round_ % 2 == 0 else ("newpass1", "correct")
        threads = [
            threading.Thread(target=run, args=(lambda: post_sign_in(TestClient(create_app(), raise_server_exceptions=False), "Wen", current).status_code,)),
            threading.Thread(target=run, args=(lambda: post_sign_in(TestClient(create_app(), raise_server_exceptions=False), "Wen", "wrong").status_code,)),
            threading.Thread(
                target=run,
                args=(lambda: f06.post_form(device, db, f06.OWN_PASSWORD_PATH, {"current_password": current, "new_password": new, "password_confirm": new}).status_code,),
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    assert statuses and all(s in (200, 303, 401, 422, 423) for s in statuses), f"出現規格外的狀態（死結會是 500）：{sorted(statuses)}"
