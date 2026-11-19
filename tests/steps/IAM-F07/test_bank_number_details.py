"""IAM-F07 與 IAM-R14 的細節測試：規格 scenario 沒有逐一寫出、但完成條件要求的行為（比規格更嚴格的斷言見 PR 說明）。

直接走 HTTP（TestClient）。輔助函式來自同目錄的 iam_f07_steps（由 conftest 載入）。每個測試只放一個錯誤原因，
而且不斷言規格已經推翻或之後的 ticket 會改的行為（pitfall #32）：IAM-R42 的其他欄位（勞健保、薪資）是 T-406 的；
不測「ADMIN 動 ADMIN」（T-304）；不斷言「還沒有銀行帳號」的顯示文字（規格沒有寫）。
金鑰只由 `bank_key` fixture 在測試裡產生（隨機），不提交任何金鑰。
"""
from __future__ import annotations

import base64
import logging
import os

import iam_f07_steps as h
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.steps.common.outcome import check_forbidden_writes_only_access_denied
from tests.steps.common.steps import Recorder, check_nothing_written, check_rejected

NUMBER = "12345678901234"
MSG_FORMAT = "銀行帳號須為 14 位數字（3 位分行＋11 位帳號）"
MSG_BLOCKED = "銀行帳號目前無法讀取，無法修改"
MSG_METHOD = "請選擇發薪方式"
MSG_NEED_NUMBER = "請先設定銀行帳號再改為轉帳"
UNREADABLE = "無法讀取"


@pytest.fixture
def client():
    return TestClient(create_app(), raise_server_exceptions=False)


def sign_in(client, db, name):
    from tests.steps.common.session import sign_in_with_correct_password

    assert sign_in_with_correct_password(client, db, name).status_code == 303


def act(client, db, actor, path, fields=(), method="post"):
    """動作前後各拍一張全庫快照；回傳 recorder（含回應）。"""
    recorder = Recorder(db)
    if method == "get":
        recorder.perform(lambda: client.get(path))
    else:
        recorder.perform(lambda: h.post(client, db, actor, path, list(fields)))
    return recorder


def path_of(db, name="Wen", suffix=""):
    return h.bank_path(h.account_id(db, name), suffix)


def decrypted(db, name="Wen") -> str:
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    cipher, _ = h.stored(db, name)
    return crypto.decrypt(crypto.load_key(), cipher, crypto.aad_for(h.account_id(db, name)))


def audit_rows(db, type_):
    with db.cursor() as cur:
        cur.execute("select actor_name, description from yc_v3.audit_log where type = %s order by id", (type_,))
        rows = cur.fetchall()
    db.rollback()
    return rows


# ───────────────────────── IAM-R14：設定銀行帳號 ─────────────────────────


def test_the_format_error_changes_nothing(client, db, bank_key):
    """規格的 `The bank-number error message` 只斷言類別與字串；資料沒有變動由這裡補上（D-129）。"""
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Admin1")
    before = h.stored(db, "Wen")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", "1234567890123")])
    check_rejected(r, "INVALID", MSG_FORMAT)
    check_nothing_written(r)
    assert h.stored(db, "Wen") == before, "舊的密文必須原封不動"


@pytest.mark.parametrize("sent", ["12345678901234", "123-45678901234", "1-2-3-4-5-6-7-8-9-0-1-2-3-4"])
def test_an_accepted_number_is_stored_without_hyphens(client, db, bank_key, sent):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", sent)])
    assert r.response.status_code == 200, r.response.text[:200]
    assert decrypted(db) == NUMBER, "存的是去掉 - 之後的 14 位數字"


@pytest.mark.parametrize(
    "sent",
    ["", " 12345678901234", "12345678901234 ", "12345678901234\n", "１２３４５６７８９０１２３４", "1234567890123４", "123456789012-"],
    ids=["empty", "leading-space", "trailing-space", "trailing-newline", "fullwidth", "one-fullwidth", "hyphen-takes-a-place"],
)
def test_other_inputs_are_invalid_and_change_nothing(client, db, bank_key, sent):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", sent)])
    check_rejected(r, "INVALID", MSG_FORMAT)
    check_nothing_written(r)


def test_a_missing_field_is_invalid_not_a_default(client, db, bank_key):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("something_else", "1")])
    check_rejected(r, "INVALID", MSG_FORMAT)
    check_nothing_written(r)


def test_setting_the_number_writes_one_account_update_audit_without_digits(client, db, bank_key):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    assert r.response.status_code == 200
    rows = audit_rows(db, "ACCOUNT_UPDATE")
    assert [a for a, _ in rows] == ["Admin1"] and "Wen" in rows[0][1]
    assert "1234" not in rows[0][1] and NUMBER not in rows[0][1], "稽核說明不含銀行帳號的任何位數"
    assert set(r.changes()) == {"accounts", "audit_log"}, f"只該動帳戶與稽核：{r.changes().keys()}"


# ───────────────────────── IAM-R14：發薪方式 ─────────────────────────


def test_switching_to_transfer_with_a_number_is_accepted_and_audited(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", f"/accounts/{h.account_id(db, 'Wen')}/payment-method", [("payment_method", "TRANSFER")])
    assert r.response.status_code == 200
    assert h.stored(db, "Wen")[1] == "TRANSFER"
    rows = audit_rows(db, "ACCOUNT_UPDATE")
    assert len(rows) == 1 and "CASH → TRANSFER" in rows[0][1]


def test_setting_the_same_method_again_writes_nothing(client, db, bank_key):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", f"/accounts/{h.account_id(db, 'Wen')}/payment-method", [("payment_method", "CASH")])
    assert r.response.status_code == 200
    check_nothing_written(r)


def test_switching_back_to_cash_keeps_the_number(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set payment_method = 'TRANSFER' where name = 'Wen'")
    db.commit()
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", f"/accounts/{h.account_id(db, 'Wen')}/payment-method", [("payment_method", "CASH")])
    assert r.response.status_code == 200
    assert h.stored(db, "Wen")[1] == "CASH" and decrypted(db) == NUMBER


@pytest.mark.parametrize("fields", [[], [("payment_method", "")], [("payment_method", "BITCOIN")], [("payment_method", "cash")]], ids=["missing", "empty", "unknown", "lowercase"])
def test_an_unknown_payment_method_is_invalid_and_changes_nothing(client, db, bank_key, fields):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", f"/accounts/{h.account_id(db, 'Wen')}/payment-method", fields)
    check_rejected(r, "INVALID", MSG_METHOD)
    check_nothing_written(r)


def test_the_database_refuses_transfer_without_a_number(db):
    """應用程式的驗證是第一道，migration 0008 的約束是最後一道。"""
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("update yc_v3.accounts set payment_method = 'TRANSFER' where name = 'Wen'")
    db.rollback()


def test_existing_accounts_are_paid_by_cash_with_no_number(db):
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.accounts where payment_method <> 'CASH' or bank_number_cipher is not null")
        assert cur.fetchone()[0] == 0
    db.rollback()


# ───────────────────────── IAM-R43：沒有金鑰（或金鑰不對） ─────────────────────────


BAD_KEYS = {
    "empty": "",
    "not-base64": "!!!not base64!!!",
    "31-bytes": base64.b64encode(b"k" * 31).decode(),
    "33-bytes": base64.b64encode(b"k" * 33).decode(),
}


@pytest.mark.parametrize("bad", BAD_KEYS.values(), ids=BAD_KEYS.keys())
def test_a_malformed_key_is_treated_as_missing_when_viewing(client, db, bank_key, monkeypatch, bad):
    h.store_bank_number(db, "Wen", NUMBER)
    monkeypatch.setenv(h.KEY_ENV, bad)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), method="get")
    assert h.value_shown(r.response) == ("unreadable", UNREADABLE)


@pytest.mark.parametrize("bad", BAD_KEYS.values(), ids=BAD_KEYS.keys())
def test_a_malformed_key_blocks_editing_and_writes_nothing(client, db, bank_key, monkeypatch, bad):
    monkeypatch.setenv(h.KEY_ENV, bad)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    check_rejected(r, "BLOCKED", MSG_BLOCKED)
    check_nothing_written(r)


def test_revealing_without_the_key_shows_unreadable_and_writes_no_audit(client, db, bank_key, monkeypatch):
    h.store_bank_number(db, "Wen", NUMBER)
    monkeypatch.delenv(h.KEY_ENV)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db, suffix="/reveal"))
    assert h.value_shown(r.response) == ("unreadable", UNREADABLE)
    check_nothing_written(r)


def test_a_different_key_cannot_read_the_old_number(client, db, bank_key, monkeypatch):
    h.store_bank_number(db, "Wen", NUMBER)
    monkeypatch.setenv(h.KEY_ENV, h.new_test_key())
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), method="get")
    assert h.value_shown(r.response) == ("unreadable", UNREADABLE)


def test_a_cipher_copied_to_another_account_cannot_be_read(client, db, bank_key):
    """密文綁定帳戶（AAD）：把 Wen 的密文複製到 Wei 的列，解不開，而不是顯示 Wen 的帳號。"""
    h.store_bank_number(db, "Wen", NUMBER)
    with db.cursor() as cur:
        cur.execute("update yc_v3.accounts set bank_number_cipher = (select bank_number_cipher from yc_v3.accounts where name = 'Wen') where name = 'Wei'")
    db.commit()
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db, "Wei"), method="get")
    assert h.value_shown(r.response) == ("unreadable", UNREADABLE)


def test_a_new_number_replaces_an_unreadable_one(client, db, bank_key, monkeypatch):
    """金鑰換掉之後，管理員重新設定就能恢復（沒有鎖死）。"""
    h.store_bank_number(db, "Wen", NUMBER)
    monkeypatch.setenv(h.KEY_ENV, h.new_test_key())
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), [("bank_number", "98765432109876")])
    assert r.response.status_code == 200
    assert decrypted(db) == "98765432109876"


# ───────────────────────── 儲存與加密（完成條件 8） ─────────────────────────


def test_the_stored_cipher_round_trips_and_is_not_the_plain_number(client, db, bank_key):
    sign_in(client, db, "Admin1")
    act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    cipher, _ = h.stored(db, "Wen")
    assert len(cipher) == 12 + len(NUMBER) + 16, "nonce（12）＋密文（與明文等長）＋標籤（16）"
    assert NUMBER.encode() not in cipher
    assert decrypted(db) == NUMBER


def test_setting_the_same_number_twice_stores_different_ciphers(client, db, bank_key):
    """每次加密都用新的隨機 nonce。"""
    sign_in(client, db, "Admin1")
    act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    first, _ = h.stored(db, "Wen")
    act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    second, _ = h.stored(db, "Wen")
    assert first != second and first[:12] != second[:12]


def test_crypto_uses_a_fresh_nonce_for_every_encryption(bank_key):
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    key = crypto.load_key()
    nonces = {crypto.encrypt(key, NUMBER, b"a")[:12] for _ in range(2000)}
    assert len(nonces) == 2000


def test_crypto_rejects_a_tampered_cipher_and_the_wrong_aad(bank_key):
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    key = crypto.load_key()
    blob = crypto.encrypt(key, NUMBER, b"a")
    assert crypto.decrypt(key, blob, b"a") == NUMBER
    flipped = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(crypto.Unreadable):
        crypto.decrypt(key, flipped, b"a")
    with pytest.raises(crypto.Unreadable):
        crypto.decrypt(key, blob, b"b")
    with pytest.raises(crypto.Unreadable):
        crypto.decrypt(key, blob[:12], b"a")


def test_the_key_must_be_exactly_32_bytes_of_base64(monkeypatch):
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    monkeypatch.delenv(h.KEY_ENV, raising=False)
    assert crypto.load_key() is None
    good = os.urandom(32)
    monkeypatch.setenv(h.KEY_ENV, base64.b64encode(good).decode())
    assert crypto.load_key() == good
    monkeypatch.setenv(h.KEY_ENV, base64.b64encode(good).decode() + "\n")
    assert crypto.load_key() == good, "環境變數尾端的換行不算格式錯誤"


def test_errors_never_carry_the_key_or_the_number(bank_key):
    from app.modules.iam.bank_number_masking_and_reveal import crypto

    key = crypto.load_key()
    blob = crypto.encrypt(key, NUMBER, b"a")
    with pytest.raises(crypto.Unreadable) as caught:
        crypto.decrypt(key, blob, b"b")
    text = repr(caught.value) + str(caught.value)
    assert bank_key not in text and NUMBER not in text


def test_nothing_is_logged_with_the_key_or_the_number(client, db, bank_key, caplog):
    caplog.set_level(logging.DEBUG)
    sign_in(client, db, "Admin1")
    act(client, db, "Admin1", path_of(db), [("bank_number", NUMBER)])
    act(client, db, "Admin1", path_of(db, suffix="/reveal"))
    act(client, db, "Admin1", path_of(db), [("bank_number", "1234567890123")])  # 被拒絕的一次
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert NUMBER not in logged and bank_key not in logged


# ───────────────────────── IAM-R40、R41：畫面與稽核 ─────────────────────────


def test_the_default_view_never_contains_the_full_number(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db), method="get")
    assert NUMBER not in r.response.text and "5678901234" not in r.response.text
    assert "no-store" in r.response.headers["cache-control"]
    check_nothing_written(r)  # 整個資料庫不變（T-200：渲染頁面不寫資料；session 的最後使用時間在固定時鐘下不變）


def test_a_reveal_is_not_cached(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", path_of(db, suffix="/reveal"))
    assert h.value_shown(r.response) == ("revealed", NUMBER)
    assert "no-store" in r.response.headers["cache-control"]


def test_a_reveal_writes_exactly_one_audit_row_and_nothing_else(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", path_of(db, suffix="/reveal"))
    assert set(r.changes()) == {"audit_log"} and len(r.changes()["audit_log"]["added"]) == 1
    rows = audit_rows(db, "BANK_REVEAL")
    assert len(rows) == 1 and rows[0][0] == "Admin1"
    assert NUMBER not in rows[0][1] and "1234" not in rows[0][1], "稽核說明點名是誰的，但不含任何位數"


def test_every_reveal_is_audited(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Wen")
    act(client, db, "Wen", path_of(db, suffix="/reveal"))
    act(client, db, "Wen", path_of(db, suffix="/reveal"))
    assert len(audit_rows(db, "BANK_REVEAL")) == 2


# ───────────────────────── IAM-R42（D-114）：USER 不能讀或改別人的銀行帳號 ─────────────────────────


@pytest.mark.parametrize(
    "suffix, method, fields",
    [("", "get", []), ("/reveal", "post", [])],
    ids=["view", "reveal"],
)
def test_a_user_cannot_read_someone_elses_bank_number(client, db, bank_key, suffix, method, fields):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Wei")
    r = act(client, db, "Wei", path_of(db, suffix=suffix), fields, method=method)
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)  # 恰好多 1 列 ACCESS_DENIED
    assert NUMBER not in r.response.text and "1234" not in r.response.text


def test_a_user_cannot_set_someone_elses_bank_number(client, db, bank_key):
    sign_in(client, db, "Wei")
    r = act(client, db, "Wei", path_of(db), [("bank_number", NUMBER)])
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)
    assert h.stored(db, "Wen")[0] is None


def test_a_user_cannot_set_someone_elses_payment_method(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Wei")
    r = act(client, db, "Wei", f"/accounts/{h.account_id(db, 'Wen')}/payment-method", [("payment_method", "TRANSFER")])
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)
    assert h.stored(db, "Wen")[1] == "CASH"


def test_a_user_cannot_set_their_own_bank_number(client, db, bank_key):
    """設定屬於帳戶管理（管理員）；持有人只能看與顯示自己的。"""
    sign_in(client, db, "Wen")
    r = act(client, db, "Wen", path_of(db), [("bank_number", NUMBER)])
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


def test_a_user_cannot_probe_for_missing_accounts(client, db, bank_key):
    """USER 問一個不存在的帳戶，得到的和問別人的一樣是 FORBIDDEN，不是 404。"""
    sign_in(client, db, "Wei")
    r = act(client, db, "Wei", h.bank_path(999999), method="get")
    check_rejected(r, "FORBIDDEN", None)
    check_forbidden_writes_only_access_denied(r, client, db)


@pytest.mark.parametrize("suffix, method", [("", "get"), ("/reveal", "post")], ids=["view", "reveal"])
def test_signed_out_requests_are_unauthenticated_and_write_nothing(client, db, bank_key, suffix, method):
    h.store_bank_number(db, "Wen", NUMBER)
    recorder = Recorder(db)
    target = path_of(db, suffix=suffix)
    recorder.perform(lambda: client.get(target) if method == "get" else client.post(target))
    check_rejected(recorder, "UNAUTHENTICATED", None)
    check_nothing_written(recorder)


@pytest.mark.parametrize("suffix", ["", "/reveal"], ids=["view", "reveal"])
def test_an_unknown_account_is_404_for_an_administrator(client, db, bank_key, suffix):
    sign_in(client, db, "Admin1")
    r = act(client, db, "Admin1", h.bank_path(999999, suffix), method="get" if suffix == "" else "post")
    assert r.response.status_code == 404
    check_nothing_written(r)


def test_the_page_offers_edit_forms_only_to_administrators(client, db, bank_key):
    h.store_bank_number(db, "Wen", NUMBER)
    sign_in(client, db, "Wen")
    own = client.get(path_of(db)).text
    assert 'name="bank_number"' not in own and 'name="payment_method"' not in own
    other = TestClient(create_app(), raise_server_exceptions=False)
    sign_in(other, db, "Admin1")
    admin = other.get(path_of(db)).text
    assert 'name="bank_number"' in admin and 'name="payment_method"' in admin
