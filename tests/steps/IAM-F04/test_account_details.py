"""IAM-F04 的細節測試：規格 scenario 沒有逐一寫出、但完成條件要求的行為（比規格更嚴格的斷言見 PR 說明）。

直接走 HTTP（TestClient）。輔助函式來自同目錄的 iam_f04_steps（由 conftest 載入）。每個測試只放一個錯誤原因，
而且不斷言規格已經推翻或之後的 ticket 會改的行為（pitfall #32）：不測「ADMIN 動 ADMIN」（T-304）、不測銀行帳號（T-306）。
"""
from __future__ import annotations

import iam_f04_steps as h
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.steps.common.outcome import check_forbidden_writes_only_access_denied
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected

INITIAL = {  # D-116
    "insured": False, "insurance_deduction": 0, "uninsured_rate_bp": None,
    "uninsured_exempt": False, "fixed_salary": 0, "pays_fixed_salary_every_period": False,
}
MSG_DEDUCTION = "勞健保扣除額須為 0 或正整數"
MSG_RATE = "未投保扣除比例須為 0 到 100 之間，最多兩位小數"
MSG_SALARY = "固定薪資須為 0 或正整數"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def sign_in(client, db, name):
    from tests.steps.common.session import sign_in_with_correct_password

    assert sign_in_with_correct_password(client, db, name).status_code == 303


def act(client, db, actor, path, fields, method="post"):
    """動作前後各拍一張全庫快照；回傳 recorder（含回應）。"""
    recorder = Recorder(db)
    if method == "get":
        recorder.perform(lambda: client.get(path))
    else:
        recorder.perform(lambda: h.post(client, db, actor, path, fields))
    return recorder


def target(db, name="Wen"):
    return f"/accounts/{h.account_id(db, name)}"


def audit_rows(db, type_):
    with db.cursor() as cur:
        cur.execute("select actor_name, description from yc_v3.audit_log where type = %s order by id", (type_,))
        rows = cur.fetchall()
    db.rollback()
    return rows


# ───────────────────────── D-114：USER 不能讀或改別人的薪資設定 ─────────────────────────


@pytest.mark.parametrize("path_of", [lambda db: "/accounts", lambda db: target(db, "Wei")], ids=["list", "someone-elses-page"])
def test_a_user_cannot_read_account_management(client, db, path_of):
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", path_of(db), [], method="get")
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_a_user_cannot_change_someone_elses_pay_settings(client, db):
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", target(db, "Wei"), [("fixed_salary", "9999")])
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)
    assert h.account_values(db, "Wei")["fixed_salary"] == 0


def test_a_user_cannot_create_an_account(client, db):
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", "/accounts", [("name", "X"), ("password", "secret1"), ("zone", "WEST"), ("role", "USER")])
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_a_user_asking_about_a_missing_account_gets_forbidden_not_404(client, db):
    """先判斷權限、再查目標：不能靠 404 與 403 的差別探測帳戶是否存在。"""
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", "/accounts/99999", [], method="get")
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_a_visitor_is_unauthenticated(client, db):
    r = act(client, db, "Wen", "/accounts", [], method="get")
    check_rejected(r, "UNAUTHENTICATED", None)
    check_nothing_written(r)


# ───────────────────────── D-116：初始值 ─────────────────────────


def test_existing_accounts_have_the_initial_pay_settings(db):
    for name in ("Kuei", "Admin1", "Wen", "Nan", "Big", "Old"):
        values = h.account_values(db, name)
        assert {k: values[k] for k in INITIAL} == INITIAL, name


def test_a_new_account_gets_the_initial_pay_settings_without_sending_them(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", "/accounts", [("name", "Lin"), ("password", "secret1"), ("zone", "SOUTH"), ("role", "USER")])
    assert r.response.status_code == 200
    values = h.account_values(db, "Lin")
    assert {k: values[k] for k in INITIAL} == INITIAL


# ───────────────────────── IAM-R15：儲存的值 ─────────────────────────


@pytest.mark.parametrize(
    "fields, expected",
    [
        ([("insurance", "enrolled"), ("deduction", "834")], {"insured": True, "insurance_deduction": 834, "uninsured_exempt": False}),
        ([("insurance", "not_enrolled_rate"), ("rate", "5")], {"insured": False, "insurance_deduction": 0, "uninsured_rate_bp": 500, "uninsured_exempt": False}),
        ([("insurance", "not_enrolled_rate"), ("rate", "3.25")], {"uninsured_rate_bp": 325}),
        ([("insurance", "not_enrolled_rate"), ("rate", "0")], {"uninsured_rate_bp": 0}),
        ([("insurance", "not_enrolled_rate"), ("rate", "100")], {"uninsured_rate_bp": 10000}),
        ([("insurance", "not_enrolled_rate"), ("rate", "100.00")], {"uninsured_rate_bp": 10000}),
        ([("insurance", "not_enrolled_rate"), ("rate", "")], {"uninsured_rate_bp": None}),
        ([("insurance", "not_enrolled_exempt")], {"insured": False, "insurance_deduction": 0, "uninsured_exempt": True}),
    ],
    ids=["enrolled", "rate-5", "rate-3.25", "rate-0", "rate-100", "rate-100.00", "rate-blank", "exempt"],
)
def test_accepted_insurance_settings_are_stored(client, db, fields, expected):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), fields)
    assert r.response.status_code == 200, r.response.text
    values = h.account_values(db, "Wen")
    assert {k: values[k] for k in expected} == expected


def test_leaving_enrolled_resets_the_deduction_to_zero(client, db):
    sign_in(client, db, "Admin1")
    act(client, db, "Admin1", target(db), [("insurance", "enrolled"), ("deduction", "834")])
    act(client, db, "Admin1", target(db), [("insurance", "not_enrolled_rate"), ("rate", "5")])
    values = h.account_values(db, "Wen")
    assert (values["insured"], values["insurance_deduction"]) == (False, 0)  # 資料庫約束：未投保一定是 0


@pytest.mark.parametrize("rate", ["abc", "-1", "5.", ".5", " 5", "1e2", "100.1.1", "101", "100.01", "3.333"])
def test_invalid_rates_are_rejected_with_the_exact_message(client, db, rate):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("insurance", "not_enrolled_rate"), ("rate", rate)])
    check_rejected(r, "INVALID", MSG_RATE)
    check_nothing_written(r)


@pytest.mark.parametrize("deduction", ["abc", "1.5", "", " 5", "99999999999"])
def test_invalid_deductions_are_rejected_with_the_exact_message(client, db, deduction):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("insurance", "enrolled"), ("deduction", deduction)])
    check_rejected(r, "INVALID", MSG_DEDUCTION)
    check_nothing_written(r)


def test_enrolled_without_a_deduction_field_is_invalid_not_defaulted(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("insurance", "enrolled")])
    check_rejected(r, "INVALID", MSG_DEDUCTION)
    check_nothing_written(r)


def test_rate_choice_without_a_rate_field_is_invalid_not_defaulted(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("insurance", "not_enrolled_rate")])
    check_rejected(r, "INVALID", MSG_RATE)
    check_nothing_written(r)


@pytest.mark.parametrize("value", ["", "5000.5", "-1", "abc", " 5", "99999999999"])
def test_invalid_fixed_salaries_are_rejected_with_the_exact_message(client, db, value):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("fixed_salary", value)])
    check_rejected(r, "INVALID", MSG_SALARY)
    check_nothing_written(r)


def test_an_unknown_insurance_choice_is_invalid(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("insurance", "maybe")])
    check_rejected(r, "INVALID", None)
    check_nothing_written(r)


def test_a_request_with_no_known_field_is_invalid(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("nickname", "x")])
    check_rejected(r, "INVALID", None)
    check_nothing_written(r)


def test_two_invalid_fields_change_nothing_even_if_the_first_is_valid(client, db):
    """驗證全部通過才寫入：前一個欄位合法、後一個不合法，前一個也不能被寫入。"""
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("zone", "SOUTH"), ("fixed_salary", "-1")])
    check_rejected(r, "INVALID", MSG_SALARY)
    check_nothing_written(r)


def test_setting_the_same_value_is_accepted_and_writes_nothing(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("fixed_salary", "0")])
    assert r.response.status_code == 200
    check_nothing_written(r)


def test_the_update_audit_has_the_old_and_the_new_value_and_the_actor(client, db):
    sign_in(client, db, "Admin1")
    act(client, db, "Admin1", target(db), [("fixed_salary", "5000")])
    (actor, description), = audit_rows(db, "ACCOUNT_UPDATE")
    assert actor == "Admin1" and "Wen" in description and "0" in description and "5000" in description, description


# ───────────────────────── IAM-R13：建立 ─────────────────────────


def create(client, db, **overrides):
    fields = {"name": "Lin", "password": "secret1", "zone": "SOUTH", "role": "USER", **overrides}
    if h.cookie_owner(client, db) is None:
        sign_in(client, db, "Admin1")
    return act(client, db, "Admin1", "/accounts", [(k, v) for k, v in fields.items() if v is not None])


def test_the_password_is_stored_as_a_hash_and_never_audited(client, db):
    create(client, db, password="secret-pass")
    values = h.account_values(db, "Lin")
    assert values["password_hash"].startswith("scrypt$") and "secret-pass" not in values["password_hash"]
    for _, description in audit_rows(db, "ACCOUNT_CREATE"):
        assert "secret-pass" not in description and values["password_hash"] not in description


def test_a_whitespace_only_name_is_invalid(client, db):
    r = create(client, db, name="   ")
    check_rejected(r, "INVALID", "請輸入顯示名稱")
    check_nothing_written(r)


def test_a_missing_password_is_invalid_not_defaulted(client, db):
    r = create(client, db, password=None)
    check_rejected(r, "INVALID", "密碼長度須為 6 至 30 個字")
    check_nothing_written(r)


def test_a_missing_zone_is_invalid_not_defaulted(client, db):
    r = create(client, db, zone=None)
    check_rejected(r, "INVALID", "請選擇施工區域")
    check_nothing_written(r)


def test_a_missing_role_is_invalid_not_defaulted(client, db):
    r = create(client, db, role=None)
    check_rejected(r, "INVALID", "請選擇角色")
    check_nothing_written(r)


def test_an_unrecognised_big_meter_value_is_invalid(client, db):
    r = create(client, db, big_meter="maybe")
    check_rejected(r, "INVALID", "請確認是否為大表帳戶")
    check_nothing_written(r)


def test_the_big_meter_flag_can_be_set_at_creation(client, db):
    assert create(client, db, big_meter="on").response.status_code == 200
    assert h.account_values(db, "Lin")["big_meter"] is True


def test_a_password_counts_characters_not_bytes(client, db):
    assert create(client, db, password="密" * 6).response.status_code == 200  # 6 個字、18 個位元組


# ───────────────────────── IAM-R16：區域與大表旗標 ─────────────────────────


def test_a_zone_change_does_not_rewrite_an_existing_reports_catalogue(client, db):
    """AD-4：改區域只影響之後送出的回報。"""
    h_given = h._has_reports
    h_given(db, "Wen", 1)
    sign_in(client, db, "Admin1")
    assert act(client, db, "Admin1", target(db), [("zone", "SOUTH")]).response.status_code == 200
    with db.cursor() as cur:
        cur.execute("select catalogue from yc_v3.reports")
        assert cur.fetchall() == [("WEST",)]
    db.rollback()
    assert h.account_values(db, "Wen")["zone"] == "SOUTH"


def test_the_big_meter_flag_can_be_turned_on_for_a_user(client, db):
    sign_in(client, db, "Admin1")
    assert act(client, db, "Admin1", target(db), [("big_meter", "on")]).response.status_code == 200
    assert h.account_values(db, "Wen")["big_meter"] is True


def test_an_unknown_zone_is_invalid(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db), [("zone", "EAST")])
    check_rejected(r, "INVALID", "請選擇施工區域")
    check_nothing_written(r)


# ───────────────────────── IAM-R17、R18：封存與復原 ─────────────────────────


def test_archiving_removes_every_session_of_the_account(client, db):
    sign_in(client, db, "Wen")
    other = TestClient(create_app(), raise_server_exceptions=False)
    sign_in(other, db, "Admin1")
    r = act(other, db, "Admin1", target(db) + "/archive", [])
    assert r.response.status_code == 200
    assert client.get("/session").status_code == 401
    assert r.changes()["sessions"]["removed"], "Wen 的 session 列應被刪除"


def test_a_restored_account_does_not_get_its_old_session_back(client, db):
    """封存前的 cookie 在復原後也不能用：archive 刪掉了 session 列（AD-13）。"""
    sign_in(client, db, "Wen")
    admin = TestClient(create_app(), raise_server_exceptions=False)
    sign_in(admin, db, "Admin1")
    act(admin, db, "Admin1", target(db) + "/archive", [])
    act(admin, db, "Admin1", target(db) + "/restore", [])
    assert client.get("/session").status_code == 401


def test_archiving_an_archived_account_is_a_conflict(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db, "Old") + "/archive", [])
    check_rejected(r, "CONFLICT", None)
    check_nothing_written(r)


def test_restoring_an_active_account_is_a_conflict(client, db):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", target(db) + "/restore", [])
    check_rejected(r, "CONFLICT", None)
    check_nothing_written(r)


@pytest.mark.parametrize("suffix", ["", "/archive", "/restore"])
def test_a_missing_account_is_404_for_an_admin(client, db, suffix):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", "/accounts/99999" + suffix, [("fixed_salary", "1")])
    assert r.response.status_code == 404
    check_nothing_written(r)


@pytest.mark.parametrize("suffix", ["delete", "deactivate"])
def test_the_removed_actions_are_invalid_even_for_a_missing_account(client, db, suffix):
    sign_in(client, db, "Kuei")
    r = act(client, db, "Kuei", f"/accounts/99999/{suffix}", [])
    check_rejected(r, "INVALID", None)
    check_nothing_written(r)


def test_the_removed_actions_need_a_signed_in_actor(client, db):
    recorder = Recorder(db)
    recorder.perform(lambda: client.post(target(db) + "/delete"))
    r = recorder
    check_rejected(r, "UNAUTHENTICATED", None)
    check_nothing_written(r)


# ───────────────────────── D-118：路徑固定 ─────────────────────────


def test_the_routes_are_exactly_the_ones_in_d118():
    from app.modules.iam.account_lifecycle_and_pay_settings.router import router

    routes = {(m, r.path) for r in router.routes for m in r.methods}
    assert routes == {
        ("GET", "/accounts"), ("POST", "/accounts"),
        ("GET", "/accounts/{account_id:int}"), ("POST", "/accounts/{account_id:int}"),
        ("POST", "/accounts/{account_id:int}/archive"), ("POST", "/accounts/{account_id:int}/restore"),
        ("POST", "/accounts/{account_id:int}/delete"), ("POST", "/accounts/{account_id:int}/deactivate"),
    }


def test_every_endpoint_goes_through_the_single_authorization_function():
    """T-304 要在 access.py 一處加「只有 OWNER 能動 ADMIN」：這個 feature 的程式不得在別處自己判斷角色。"""
    import pathlib

    base = pathlib.Path(__file__).resolve().parents[3] / "app/modules/iam/account_lifecycle_and_pay_settings"
    for name in ("router.py", "service.py", "repo.py"):
        text = (base / name).read_text(encoding="utf-8")
        assert "Role." not in text and "authorize(" not in text, f"{name} 不得自己判斷角色：權限只在 access.py"
