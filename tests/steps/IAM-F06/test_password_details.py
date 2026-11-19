"""IAM-F06 的 scenario 沒有逐字涵蓋、但 T-305 的完成條件要求的行為。

- 完成條件 3、4：每個拒絕案例斷言三件事（結果類別、完整錯誤字串、資料沒有任何變動）；伺服器重新驗證每個欄位，
  缺少的值不補預設值。每個測試只放**一個**錯誤原因（pitfall #32），也不斷言規格沒寫的行為。
- 完成條件 9（D-118）：路徑固定；重設端點的權限判斷只在 `service.authorize_reset`。

以下「比規格更嚴格的斷言」會在 PR 說明逐條列出（D-091）：被拒絕的請求整個資料庫都不變
（動作前後全庫快照）、稽核整列（含 actor_name）不得含密碼、密碼長度以字元數（不是位元組）計。
"""
from __future__ import annotations

import threading
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

import iam_f06_steps as f06
from app.main import create_app
from tests.steps.common.session import SESSION_COOKIE, TEST_PASSWORD, post_sign_in, set_password, sign_in_with_correct_password
from tests.steps.common.steps import check_nothing_written, check_rejected, new_audit_rows

LENGTH = "密碼長度須為 6 至 30 個字"
MISMATCH = "兩次輸入的密碼不一致"
CURRENT_WRONG = "目前密碼不正確"
VALID = {"current_password": TEST_PASSWORD, "new_password": "newpass1", "password_confirm": "newpass1"}


def signed_in(db, name: str) -> TestClient:
    client = TestClient(create_app(), raise_server_exceptions=False)
    assert sign_in_with_correct_password(client, db, name).status_code == 303
    return client


def post_raw(client, db, path: str, body: str):
    """原樣送出請求主體（可以重複欄位、缺少欄位）。"""
    return client.post(path, content=body, headers={"content-type": "application/x-www-form-urlencoded", "X-CSRF-Token": f4(client, db)})


def f4(client, db) -> str:
    return f06.csrf_token(client, db)


def password_hash(db, name: str) -> str | None:
    row = db.execute("select password_hash from yc_v3.accounts where name = %s", (name,)).fetchone()
    db.rollback()
    return row[0]


def can_sign_in(db, name: str, password: str) -> bool:
    fresh = TestClient(create_app(), raise_server_exceptions=False)
    return post_sign_in(fresh, name, password).status_code == 303


def own(recorder, client, db, body: str):
    recorder.perform(lambda: post_raw(client, db, f06.OWN_PASSWORD_PATH, body))
    return recorder.response


# ───────────────────────── IAM-R30：自己改密碼 ─────────────────────────


def test_a_successful_change_replaces_the_hash_and_only_the_new_password_signs_in(db, recorder):
    client = signed_in(db, "Wen")
    before = password_hash(db, "Wen")
    assert own(recorder, client, db, urlencode(VALID)).status_code == 200
    after = password_hash(db, "Wen")
    assert after != before and after.startswith("scrypt$"), "密碼雜湊應換成新的 scrypt 雜湊"
    assert "newpass1" not in after
    assert can_sign_in(db, "Wen", "newpass1") and not can_sign_in(db, "Wen", TEST_PASSWORD)


def test_a_successful_change_touches_only_the_actors_password_and_one_audit_row(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode(VALID))
    changes = recorder.changes()
    assert set(changes) == {"accounts", "audit_log"}, f"只該動到 accounts（密碼）與 audit_log：{list(changes)}"
    assert len(changes["accounts"]["added"]) == 1 and len(changes["accounts"]["removed"]) == 1
    assert len(changes["audit_log"]["added"]) == 1


def test_the_audit_row_names_the_actor_and_carries_no_password_or_hash(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode(VALID))
    added = new_audit_rows(recorder)
    assert len(added) == 1
    row = added[0]
    for secret in (TEST_PASSWORD, "newpass1", password_hash(db, "Wen")):
        assert secret not in row, f"稽核整列不可含 {secret[:6]}…"
    assert "PASSWORD_CHANGE" in row and "Wen" in row


def test_the_owner_can_change_their_password_with_the_correct_current_password(db, recorder):
    client = signed_in(db, "Kuei")
    assert own(recorder, client, db, urlencode(VALID)).status_code == 200
    assert can_sign_in(db, "Kuei", "newpass1")


@pytest.mark.parametrize("new, ok", [("12345", False), ("123456", True), ("x" * 30, True), ("x" * 31, False), ("", False)])
def test_the_length_boundaries_are_6_to_30(db, recorder, new, ok):
    client = signed_in(db, "Wen")
    r = own(recorder, client, db, urlencode({**VALID, "new_password": new, "password_confirm": new}))
    if ok:
        assert r.status_code == 200
    else:
        check_rejected(recorder, "INVALID", LENGTH)
        check_nothing_written(recorder)


def test_length_counts_characters_not_bytes(db, recorder):
    # 6 個中文字 = 18 位元組；30 個中文字 = 90 位元組。規格寫「6 至 30 個字」
    client = signed_in(db, "Wen")
    assert own(recorder, client, db, urlencode({**VALID, "new_password": "密碼六個字了", "password_confirm": "密碼六個字了"})).status_code == 200
    assert can_sign_in(db, "Wen", "密碼六個字了")


def test_spaces_are_part_of_the_password_and_are_not_trimmed(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode({**VALID, "new_password": "      ", "password_confirm": "      "}))  # 6 個空白 = 6 個字
    assert recorder.response.status_code == 200
    assert can_sign_in(db, "Wen", "      ")


def test_a_wrong_current_password_leaves_the_old_password_working(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode({**VALID, "current_password": "wrong"}))
    check_rejected(recorder, "INVALID", CURRENT_WRONG)
    # D-124（T-308）：錯誤的目前密碼與登入共用失敗計數，所以恰好寫一列失敗次數；帳戶、session、稽核等其他資料不變。
    # 原本斷言整個資料庫不變，那是 D-124 推翻的行為（pitfall #32）；這裡改成更精確的「只有這一張表、只多這一列」。
    assert set(recorder.changes()) == {"sign_in_failures"}, recorder.changes()
    assert len(recorder.changes()["sign_in_failures"]["added"]) == 1 and recorder.changes()["sign_in_failures"]["removed"] == []
    assert can_sign_in(db, "Wen", TEST_PASSWORD)


@pytest.mark.parametrize(
    "body, message",
    [
        (urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}), CURRENT_WRONG),  # 缺少目前密碼
        (urlencode({"current_password": TEST_PASSWORD, "password_confirm": "newpass1"}), LENGTH),  # 缺少新密碼
        (urlencode({"current_password": TEST_PASSWORD, "new_password": "newpass1"}), MISMATCH),  # 缺少確認
        ("", CURRENT_WRONG),  # 什麼都沒有
    ],
    ids=["missing-current", "missing-new", "missing-confirm", "empty-body"],
)
def test_a_missing_field_is_rejected_and_never_defaulted(db, recorder, body, message):
    client = signed_in(db, "Wen")
    own(recorder, client, db, body)
    check_rejected(recorder, "INVALID", message)
    check_nothing_written(recorder)


@pytest.mark.parametrize(
    "extra, message",
    [
        ({"current_password": TEST_PASSWORD}, CURRENT_WRONG),
        ({"new_password": "newpass1"}, LENGTH),
        ({"password_confirm": "newpass1"}, MISMATCH),
    ],
    ids=["dup-current", "dup-new", "dup-confirm"],
)
def test_a_repeated_field_is_rejected_instead_of_picking_one(db, recorder, extra, message):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode(VALID) + "&" + urlencode(extra))
    check_rejected(recorder, "INVALID", message)
    check_nothing_written(recorder)


def test_an_empty_confirmation_does_not_match_a_valid_new_password(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode({**VALID, "password_confirm": ""}))
    check_rejected(recorder, "INVALID", MISMATCH)
    check_nothing_written(recorder)


def test_an_oversized_body_is_rejected_without_writing(db, recorder):
    client = signed_in(db, "Wen")
    own(recorder, client, db, urlencode({**VALID, "new_password": "x" * 5000, "password_confirm": "x" * 5000}))
    check_rejected(recorder, "INVALID", None)
    check_nothing_written(recorder)


def test_a_visitor_cannot_change_a_password(db, recorder):
    client = TestClient(create_app(), raise_server_exceptions=False)
    recorder.perform(lambda: client.post(f06.OWN_PASSWORD_PATH, content=urlencode(VALID), headers={"content-type": "application/x-www-form-urlencoded"}))
    check_rejected(recorder, "UNAUTHENTICATED", None)
    check_nothing_written(recorder)


def test_a_change_without_the_anti_forgery_token_is_forbidden_and_writes_only_access_denied(db, recorder):
    client = signed_in(db, "Wen")
    recorder.perform(lambda: client.post(f06.OWN_PASSWORD_PATH, content=urlencode(VALID), headers={"content-type": "application/x-www-form-urlencoded"}))
    check_rejected(recorder, "FORBIDDEN", None)
    assert [t for t in recorder.changes() if t != "audit_log"] == [], "ACCESS_DENIED 以外不可有變動"
    assert len(new_audit_rows(recorder)) == 1 and can_sign_in(db, "Wen", TEST_PASSWORD)


def test_two_simultaneous_changes_with_the_same_current_password_cannot_both_succeed(db):
    """鎖住帳戶列：驗證目前密碼與寫入新密碼之間不能被另一個變更插進來。"""
    client = signed_in(db, "Wen")
    token = f4(client, db)
    cookie = client.cookies.get(SESSION_COOKIE)
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def worker(new: str) -> None:
        c = TestClient(create_app(), raise_server_exceptions=False)
        c.cookies.set(SESSION_COOKIE, cookie)
        barrier.wait()
        statuses.append(c.post(f06.OWN_PASSWORD_PATH, content=urlencode({**VALID, "new_password": new, "password_confirm": new}), headers={"content-type": "application/x-www-form-urlencoded", "X-CSRF-Token": token}).status_code)

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("newpass1", "newpass2")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(statuses) == [200, 422], f"同時兩個變更用同一個舊密碼，只能有一個成功：{statuses}"


# ───────────────────────── IAM-R31：管理員重設 ─────────────────────────


def reset(recorder, client, db, target: str, body: str, *, target_id: int | None = None):
    path = f06.RESET_PATH.format(id=target_id if target_id is not None else f06.account_id(db, target))
    recorder.perform(lambda: post_raw(client, db, path, body))
    return recorder.response


def test_a_reset_needs_no_current_password_and_replaces_the_old_one(db, recorder):
    client = signed_in(db, "Admin1")
    set_password(db, "Wen")  # 先讓 Wen 有一個舊密碼，才看得出被換掉
    assert reset(recorder, client, db, "Wen", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"})).status_code == 200
    assert can_sign_in(db, "Wen", "newpass1") and not can_sign_in(db, "Wen", TEST_PASSWORD)


def test_a_reset_by_the_owner_works_too(db, recorder):
    client = signed_in(db, "Kuei")
    assert reset(recorder, client, db, "Wen", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"})).status_code == 200
    assert can_sign_in(db, "Wen", "newpass1")


def test_a_reset_changes_only_the_target_password_and_writes_one_audit_row(db, recorder):
    client = signed_in(db, "Admin1")
    admin_hash, wei_hash = password_hash(db, "Admin1"), password_hash(db, "Wei")
    reset(recorder, client, db, "Wen", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}))
    assert set(recorder.changes()) == {"accounts", "audit_log"}
    assert (password_hash(db, "Admin1"), password_hash(db, "Wei")) == (admin_hash, wei_hash), "其他帳戶的密碼不可動"
    rows = new_audit_rows(recorder)
    assert len(rows) == 1 and "PASSWORD_CHANGE" in rows[0] and "Admin1" in rows[0] and "Wen" in rows[0]
    assert "newpass1" not in rows[0]


def test_a_user_cannot_reset_a_password_and_only_access_denied_is_written(db, recorder):
    client = signed_in(db, "Wei")
    wen_hash = password_hash(db, "Wen")
    reset(recorder, client, db, "Wen", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}))
    check_rejected(recorder, "FORBIDDEN", None)
    assert [t for t in recorder.changes() if t != "audit_log"] == [], "ACCESS_DENIED 以外不可有變動（accounts 沒變）"
    assert len(new_audit_rows(recorder)) == 1 and "ACCESS_DENIED" in new_audit_rows(recorder)[0] and "Wei" in new_audit_rows(recorder)[0]
    assert password_hash(db, "Wen") == wen_hash


def test_a_user_gets_forbidden_even_for_an_account_that_does_not_exist(db, recorder):
    # 先判斷權限、再查目標：USER 不能靠 404 與 403 的差別探測帳戶是否存在
    client = signed_in(db, "Wei")
    reset(recorder, client, db, "", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}), target_id=999999)
    check_rejected(recorder, "FORBIDDEN", None)


def test_a_reset_of_a_missing_account_is_404_and_writes_nothing(db, recorder):
    client = signed_in(db, "Admin1")
    reset(recorder, client, db, "", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}), target_id=999999)
    assert recorder.response.status_code == 404
    check_nothing_written(recorder)


@pytest.mark.parametrize("new", ["12345", "x" * 31, ""])
def test_a_reset_with_a_bad_length_is_rejected(db, recorder, new):
    client = signed_in(db, "Admin1")
    reset(recorder, client, db, "Wen", urlencode({"new_password": new, "password_confirm": new}))
    check_rejected(recorder, "INVALID", LENGTH)
    check_nothing_written(recorder)


def test_a_reset_with_a_missing_password_is_rejected_and_never_defaulted(db, recorder):
    client = signed_in(db, "Admin1")
    reset(recorder, client, db, "Wen", "")
    check_rejected(recorder, "INVALID", LENGTH)
    check_nothing_written(recorder)


def test_a_reset_with_a_repeated_password_field_is_rejected(db, recorder):
    client = signed_in(db, "Admin1")
    reset(recorder, client, db, "Wen", "new_password=newpass1&new_password=newpass2&password_confirm=newpass1")
    check_rejected(recorder, "INVALID", LENGTH)
    check_nothing_written(recorder)


def test_a_visitor_cannot_reset_a_password(db, recorder):
    client = TestClient(create_app(), raise_server_exceptions=False)
    path = f06.RESET_PATH.format(id=f06.account_id(db, "Wen"))
    recorder.perform(lambda: client.post(path, content=urlencode({"new_password": "newpass1", "password_confirm": "newpass1"}), headers={"content-type": "application/x-www-form-urlencoded"}))
    check_rejected(recorder, "UNAUTHENTICATED", None)
    check_nothing_written(recorder)


def test_a_non_numeric_account_id_is_not_found(db, recorder):
    client = signed_in(db, "Admin1")
    recorder.perform(lambda: post_raw(client, db, "/accounts/abc/password", urlencode({"new_password": "newpass1", "password_confirm": "newpass1"})))
    assert recorder.response.status_code in (404, 422)
    check_nothing_written(recorder)


# ───────────────────────── 頁面與路由（D-118）─────────────────────────


@pytest.mark.parametrize("who", ["Wen", "Admin1", "Kuei"])
def test_every_signed_in_role_can_open_the_change_password_page(db, who):
    client = signed_in(db, who)
    r = client.get(f06.OWN_PASSWORD_PATH)
    assert r.status_code == 200
    for field in ("current_password", "new_password", "password_confirm"):
        assert f'name="{field}"' in r.text
    assert 'type="password"' in r.text and who in r.text
    assert "X-CSRF-Token" in r.text, "頁面內的 HTMX 請求要自動帶 anti-forgery token"


def test_a_visitor_cannot_open_the_change_password_page(db):
    r = TestClient(create_app(), raise_server_exceptions=False).get(f06.OWN_PASSWORD_PATH)
    assert r.status_code == 401


def test_the_password_routes_are_exactly_the_three_in_d118():
    routes = {(m, p) for m, p in f06.app_routes() if "password" in p}
    assert routes == {("GET", "/account/password"), ("POST", "/account/password"), ("POST", "/accounts/{account_id}/password")}


def test_the_reset_permission_lives_in_one_function():
    """T-304 要在這裡加規則：端點不自己判斷角色。"""
    import inspect

    from app.modules.iam.password_change_and_reset import router, service

    assert hasattr(service, "authorize_reset") and "authorize_reset" in inspect.getsource(service.reset_password)
    assert "authorize" not in inspect.getsource(router).replace("service.", "").split("def reset_password")[1].split("return render_page")[0]


# ───────────────────────── 密碼不能進網址（Bugbot 意見、Chief 要求）─────────────────────────


def test_the_password_form_posts_to_the_change_endpoint_even_without_javascript(db):
    """沒有 `method="post"` 時，瀏覽器的預設是 GET：三個密碼欄位會進網址、歷史紀錄與存取紀錄。"""
    import re

    html = signed_in(db, "Wen").get(f06.OWN_PASSWORD_PATH).text
    form = re.search(r"<form\b[^>]*>", html).group(0)
    assert re.search(r'\bmethod="post"', form), f"密碼表單必須明確用 POST：{form}"
    assert f'action="{f06.OWN_PASSWORD_PATH}"' in form, f"密碼表單必須有明確的 action：{form}"
    assert not re.search(r'\bmethod="get"', form, re.I)


def test_every_form_that_contains_a_password_field_posts(db):
    """所有「包含密碼欄位的表單」都明確用 POST（登入頁另一個沒有密碼的 GET 表單——群組選單——不受影響）。
    新增含密碼欄位的頁面時這項檢查會一併涵蓋。"""
    import re
    from pathlib import Path

    checked = []
    for template in sorted(Path("app").rglob("*.html")):
        for match in re.finditer(r"(<form\b[^>]*>)(.*?)</form>", template.read_text(encoding="utf-8"), re.S | re.I):
            tag, body = match.groups()
            if 'type="password"' not in body:
                continue
            checked.append(str(template))
            assert re.search(r'\bmethod="post"', tag), f"{template}：含密碼欄位的表單必須明確用 POST：{tag}"
    # 防止空轉：至少要檢查到登入頁與密碼變更頁兩個表單
    assert len(checked) >= 2 and any("sign_in" in c for c in checked) and any("password_change_and_reset" in c for c in checked), checked


def test_a_get_with_passwords_in_the_query_changes_nothing(db, recorder):
    client = signed_in(db, "Wen")
    before = password_hash(db, "Wen")
    query = urlencode(VALID)
    recorder.perform(lambda: client.get(f"{f06.OWN_PASSWORD_PATH}?{query}"))
    assert recorder.response.status_code == 200  # 只是顯示頁面
    check_nothing_written(recorder)
    assert password_hash(db, "Wen") == before and can_sign_in(db, "Wen", TEST_PASSWORD)


def test_a_get_on_the_reset_path_is_not_allowed_and_changes_nothing(db, recorder):
    client = signed_in(db, "Admin1")
    path = f06.RESET_PATH.format(id=f06.account_id(db, "Wen")) + "?" + urlencode({"new_password": "newpass1", "password_confirm": "newpass1"})
    recorder.perform(lambda: client.get(path))
    assert recorder.response.status_code == 405
    check_nothing_written(recorder)
    assert can_sign_in(db, "Wen", "newpass1") is False
