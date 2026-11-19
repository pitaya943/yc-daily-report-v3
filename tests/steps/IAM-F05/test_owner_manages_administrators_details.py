"""IAM-F05 的細節測試：規格 scenario 沒有逐一寫出、但完成條件要求的行為（比規格更嚴格的斷言見 PR 說明）。

直接走 HTTP（TestClient）。輔助函式來自同目錄的 iam_f05_steps（由 conftest 載入）。每個測試只放一個錯誤原因，
不斷言規格已經推翻或之後的 ticket 會改的行為（pitfall #32）。

AGENTS.md 不可違反第 5 條（D-129）：每個拒絕案例斷言結果類別、完整錯誤字串、資料沒有任何變動——
`FORBIDDEN` 只多 1 列 `ACCESS_DENIED`（行為者是被拒絕的人），其他類別資料庫完全不變。
"""
from __future__ import annotations

import iam_f05_steps as h
import pytest
from fastapi.testclient import TestClient

from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.db import connect
from app.main import create_app
from app.modules.iam.account_lifecycle_and_pay_settings import service as accounts_service
from tests.steps.common.outcome import check_forbidden_writes_only_access_denied
from tests.steps.common.session import sign_in_with_correct_password
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected

MSG_ARCHIVE_OWNER = "owner 帳戶不能封存"
MSG_ARCHIVE_SELF = "不能封存自己目前登入的帳戶"
MSG_ROLE = "請選擇角色"
MSG_BIG_METER = "請先關閉大表旗標，再切換為管理員"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def sign_in(client, db, name):
    assert sign_in_with_correct_password(client, db, name).status_code == 303


def act(client, db, actor, path, fields):
    """動作前後各拍一張全庫快照；回傳 recorder（含回應）。"""
    recorder = Recorder(db)
    recorder.perform(lambda: h.post(client, db, actor, path, fields))
    return recorder


def target(db, name):
    return f"/accounts/{h.account_id(db, name)}"


def rejected(r, client, db, outcome, message):
    """拒絕的三件事（AGENTS.md 不可違反第 5 條）：結果類別、完整錯誤字串、資料沒有任何變動（FORBIDDEN 只多 1 列 ACCESS_DENIED）。"""
    check_rejected(r, outcome, message)
    if outcome == "FORBIDDEN":
        check_forbidden_writes_only_access_denied(r, client, db)
    else:
        check_nothing_written(r)


def audit_rows(db, type_):
    with db.cursor() as cur:
        cur.execute("select actor_name, description from yc_v3.audit_log where type = %s order by id", (type_,))
        rows = cur.fetchall()
    db.rollback()
    return rows


def seed_lock(db, name):
    """直接寫入「剛被鎖定」的失敗次數列（與 IAM-F02 的步驟相同的資料形狀）。"""
    with db.cursor() as cur:
        cur.execute(
            "insert into yc_v3.sign_in_failures(account_id, fail_count, last_failed_at, locked_at) values (%s, 5, %s, %s)",
            (h.account_id(db, name), clock.now(), clock.now()),
        )
    db.commit()


# ───────────────────────── IAM-R22（規格只寫 rejected as；D-129 補資料斷言） ─────────────────────────


@pytest.mark.parametrize(
    "actor,message",
    [("Kuei", MSG_ARCHIVE_OWNER), ("Admin1", MSG_ARCHIVE_SELF)],
    ids=["owner-archives-owner", "admin-archives-self"],
)
def test_self_protection_rejects_with_the_spec_string_and_changes_nothing(client, db, actor, message):
    sign_in(client, db, actor)
    r = act(client, db, actor, target(db, actor) + "/archive", [])
    rejected(r, client, db, "CONFLICT", message)
    assert h.account_values(db, actor)["archived"] is False


def test_the_owner_invariant_holds_even_for_an_owner_role_actor_who_is_not_the_owner_account(db):
    """防線的最後一道：OWNER 帳戶不能封存，不依賴「OWNER 只有一個人」。用一個角色為 OWNER、但 id 不同的行為者呼叫 service。"""
    admin1 = h.account_id(db, "Admin1")
    impostor = Actor(id=admin1, name="Admin1", role=Role.OWNER)
    recorder = Recorder(db)

    def action():
        with connect() as conn:
            with pytest.raises(Exception) as caught:
                accounts_service.archive_account(conn, impostor, h.account_id(db, "Kuei"))
        return caught.value

    error = recorder.perform(action)
    assert (error.outcome.value, error.message) == ("CONFLICT", MSG_ARCHIVE_OWNER)
    check_nothing_written(recorder)


# ───────────────────────── IAM-R20：ADMIN 不能動 OWNER、不能動自己（FORBIDDEN 只多 1 列 ACCESS_DENIED） ─────────────────────────

_ADMIN_ACTIONS = {
    "archive": ("/archive", []),
    "restore": ("/restore", []),
    "zone": ("", [("zone", "SOUTH")]),
    "role": ("/role", [("role", "USER")]),
    "reset-password": ("/password", [("new_password", h.NEW_PASSWORD), ("password_confirm", h.NEW_PASSWORD)]),
}


@pytest.mark.parametrize("kind", list(_ADMIN_ACTIONS))
def test_an_admin_cannot_touch_the_owner(client, db, kind):
    sign_in(client, db, "Admin1")
    tail, fields = _ADMIN_ACTIONS[kind]
    r = act(client, db, "Admin1", target(db, "Kuei") + tail, fields)
    rejected(r, client, db, "FORBIDDEN", None)


@pytest.mark.parametrize("kind", ["zone", "role", "reset-password"])
def test_an_admin_cannot_change_its_own_account(client, db, kind):
    """Q-055：管理員除了密碼以外的自身欄位只有 OWNER 能改；密碼用自己的端點（IAM-R30），不是管理員重設端點。"""
    sign_in(client, db, "Admin1")
    tail, fields = _ADMIN_ACTIONS[kind]
    r = act(client, db, "Admin1", target(db, "Admin1") + tail, fields)
    rejected(r, client, db, "FORBIDDEN", None)


def test_an_admin_cannot_create_an_admin_and_nothing_but_the_denial_is_written(client, db):
    sign_in(client, db, "Admin1")
    fields = [("name", "NewAdmin"), ("password", "secret1"), ("password_confirm", "secret1"), ("zone", "WEST"), ("role", "ADMIN")]
    r = act(client, db, "Admin1", "/accounts", fields)
    rejected(r, client, db, "FORBIDDEN", None)
    assert "accounts" not in r.changes()


def test_a_forbidden_creation_does_not_reveal_field_errors(client, db):
    """權限先於欄位驗證：ADMIN 建立 ADMIN，即使名稱是空的，也是 FORBIDDEN，不是「請輸入顯示名稱」。"""
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", "/accounts", [("name", ""), ("role", "ADMIN")])
    rejected(r, client, db, "FORBIDDEN", None)


# ───────────────────────── D-122：沒有人能用管理員重設端點重設 OWNER 的密碼 ─────────────────────────


def test_the_owner_cannot_use_the_admin_reset_endpoint_on_itself(client, db):
    sign_in(client, db, "Kuei")
    before = h.account_values(db, "Kuei")["password_hash"]
    r = act(client, db, "Kuei", target(db, "Kuei") + "/password", _ADMIN_ACTIONS["reset-password"][1])
    rejected(r, client, db, "INVALID", None)
    assert h.account_values(db, "Kuei")["password_hash"] == before


def test_an_admin_resetting_the_owner_password_leaves_the_hash_unchanged(client, db):
    sign_in(client, db, "Admin1")
    before = h.account_values(db, "Kuei")["password_hash"]
    r = act(client, db, "Admin1", target(db, "Kuei") + "/password", _ADMIN_ACTIONS["reset-password"][1])
    rejected(r, client, db, "FORBIDDEN", None)
    assert h.account_values(db, "Kuei")["password_hash"] == before


# ───────────────────────── IAM-R21：切換角色 ─────────────────────────


@pytest.mark.parametrize("actor", ["Admin1", "Wen"], ids=["admin", "user"])
def test_only_the_owner_can_switch_roles(client, db, actor):
    sign_in(client, db, actor)
    r = act(client, db, actor, target(db, "Wei") + "/role", [("role", "ADMIN")])
    rejected(r, client, db, "FORBIDDEN", None)
    assert h.account_role(db, "Wei") == "USER"


@pytest.mark.parametrize(
    "fields",
    [[], [("role", "")], [("role", "OWNER")], [("role", "SUPER")], [("role", "ADMIN"), ("role", "ADMIN")], [("role", "admin")]],
    ids=["missing", "empty", "owner-cannot-be-selected", "unknown", "duplicated", "wrong-case"],
)
def test_the_role_field_is_validated_by_the_server(client, db, fields):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Wen") + "/role", fields)
    rejected(r, client, db, "INVALID", MSG_ROLE)
    assert h.account_role(db, "Wen") == "USER"


def test_the_owner_role_cannot_be_changed(client, db):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Kuei") + "/role", [("role", "ADMIN")])
    rejected(r, client, db, "INVALID", None)
    assert h.account_role(db, "Kuei") == "OWNER"


def test_switching_an_unknown_account_is_not_found(client, db):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", "/accounts/999999/role", [("role", "ADMIN")])
    assert r.response.status_code == 404
    check_nothing_written(r)


def test_a_big_meter_account_stays_a_user_when_the_switch_is_refused(client, db):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Big") + "/role", [("role", "ADMIN")])
    rejected(r, client, db, "CONFLICT", MSG_BIG_METER)
    assert (h.account_role(db, "Big"), h.account_values(db, "Big")["big_meter"]) == ("USER", True)


def test_switching_to_the_same_role_is_accepted_without_writing(client, db):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Wen") + "/role", [("role", "USER")])
    assert r.response.status_code == 200
    check_nothing_written(r)


def test_the_owner_can_demote_an_admin_and_the_change_is_audited(client, db):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Admin2") + "/role", [("role", "USER")])
    assert r.response.status_code == 200
    assert h.account_role(db, "Admin2") == "USER"
    assert audit_rows(db, "ACCOUNT_ROLE_CHANGE") == [("Kuei", "變更 Admin2 的角色：ADMIN → USER")]
    assert set(r.changes()) == {"accounts", "audit_log"}


def test_the_new_role_takes_effect_on_the_next_request_of_the_existing_session(client, db):
    """角色每次請求都從資料庫讀：被升為 ADMIN 的人不必重新登入；之後被降為 USER 也立即失去管理權限。"""
    sign_in(client, db, "Wen")
    assert client.get("/accounts").status_code == 403
    owner = TestClient(create_app(), raise_server_exceptions=False)
    sign_in(owner, db, "Kuei")
    assert h.post(owner, db, "Kuei", target(db, "Wen") + "/role", [("role", "ADMIN")]).status_code == 200
    assert client.get("/accounts").status_code == 200
    assert h.post(owner, db, "Kuei", target(db, "Wen") + "/role", [("role", "USER")]).status_code == 200
    assert client.get("/accounts").status_code == 403


# ───────────────────────── 不誤擋：OWNER 能動 ADMIN；ADMIN 仍能動 USER、能讀 ADMIN 的頁面 ─────────────────────────


@pytest.mark.parametrize("kind", ["archive", "zone", "reset-password"])
def test_the_owner_can_manage_an_admin(client, db, kind):
    sign_in(client, db, "Kuei")
    tail, fields = _ADMIN_ACTIONS[kind]
    r = act(client, db, "Kuei", target(db, "Admin2") + tail, fields)
    assert r.response.status_code == 200, r.response.text[:200]


def test_the_owner_can_restore_an_archived_admin(client, db):
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set archived = true where name = 'Admin2'")
    db.commit()
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", target(db, "Admin2") + "/restore", [])
    assert r.response.status_code == 200
    assert h.account_values(db, "Admin2")["archived"] is False


def test_an_admin_can_still_manage_a_user(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db, "Wen") + "/archive", [])
    assert r.response.status_code == 200
    assert h.account_values(db, "Wen")["archived"] is True


def test_an_admin_can_still_open_an_admin_account_page_because_reading_is_not_in_iam_r20(client, db):
    sign_in(client, db, "Admin1")
    assert client.get(target(db, "Admin2")).status_code == 200


# ───────────────────────── D-126：帳戶管理頁的「解除鎖定」按鈕 ─────────────────────────


def rows_with_button(html):
    """頁面上有「解除鎖定」按鈕的列：{顯示名稱: 按鈕的 hx-post}。"""
    import re

    found = {}
    for m in re.finditer(r'<tr data-account-name="([^"]+)"(.*?)</tr>', html, flags=re.S):
        post = re.search(r'hx-post="([^"]+/unlock)"', m.group(2))
        if post and "解除鎖定" in m.group(2):
            found[m.group(1)] = post.group(1)
    return found


def test_an_admin_sees_the_unlock_button_for_a_locked_user_only(client, db):
    seed_lock(db, "Wen")
    seed_lock(db, "Admin2")
    sign_in(client, db, "Admin1")
    html = client.get("/accounts").text
    assert rows_with_button(html) == {"Wen": f"/accounts/{h.account_id(db, 'Wen')}/unlock"}


def test_the_owner_sees_the_unlock_button_for_a_locked_user_and_a_locked_admin(client, db):
    seed_lock(db, "Wen")
    seed_lock(db, "Admin2")
    sign_in(client, db, "Kuei")
    html = client.get("/accounts").text
    assert rows_with_button(html) == {
        "Wen": f"/accounts/{h.account_id(db, 'Wen')}/unlock",
        "Admin2": f"/accounts/{h.account_id(db, 'Admin2')}/unlock",
    }


def test_no_button_is_shown_when_nobody_is_locked(client, db):
    sign_in(client, db, "Kuei")
    assert rows_with_button(client.get("/accounts").text) == {}


def test_a_lock_that_has_ended_shows_no_button(client, db):
    """鎖定滿 15 分鐘就結束（IAM-R04）：同一個判斷，所以按鈕也消失。"""
    seed_lock(db, "Wen")
    clock.set(clock.now().replace(hour=10, minute=15))
    sign_in(client, db, "Kuei")
    assert rows_with_button(client.get("/accounts").text) == {}


def test_the_owner_account_is_never_listed(client, db):
    sign_in(client, db, "Kuei")
    seed_lock(db, "Kuei")  # 登入之後才鎖定：鎖定中的帳戶不能登入
    html = client.get("/accounts").text
    assert 'data-account-name="Kuei"' not in html


def test_an_admin_does_not_see_administrator_rows(client, db):
    """Q-056：ADMIN 的帳戶管理只列 USER。"""
    sign_in(client, db, "Admin1")
    html = client.get("/accounts").text
    assert 'data-role="ADMIN"' not in html and 'data-role="OWNER"' not in html


def test_the_button_calls_the_unlock_endpoint_and_the_lock_is_gone(client, db):
    seed_lock(db, "Admin2")
    sign_in(client, db, "Kuei")
    path = rows_with_button(client.get("/accounts").text)["Admin2"]
    assert h.post(client, db, "Kuei", path, []).status_code == 200
    assert rows_with_button(client.get("/accounts").text) == {}
