"""完成條件 1：七個結果類別對應 spec/README.md 的 HTTP status，並回傳完整的錯誤字串。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.outcomes import Outcome, OutcomeError, register_outcome_handlers
from app.main import create_app
from tests.steps.common.spec_tables import outcome_http_table

# 完整字串逐字取自 spec/appendix-b-fields.md
FULL_MESSAGES = {
    "LOCKED": "密碼錯誤次數過多，請在 15 分鐘後再試",
    "BLOCKED": "單價尚未設定完整，無法計算薪資，請先補齊單價",
    "CONFLICT": "每日最多只能送出 3 筆回報",
    "INVALID": "回報日期須為今天或往前 30 天內，不可選擇未來日期",
    "UNAUTHENTICATED": "密碼錯誤，請重試",
}


def test_there_are_exactly_the_seven_classes_of_the_spec():
    assert {o.value for o in Outcome} == set(outcome_http_table())
    assert len(Outcome) == 7


def test_every_class_maps_to_the_http_status_of_the_spec_table():
    for name, status in outcome_http_table().items():
        assert Outcome(name).http_status == status, name


def _client_raising(outcome: Outcome, message: str | None) -> TestClient:
    app = FastAPI()
    register_outcome_handlers(app)

    @app.get("/boom")
    def boom():
        raise OutcomeError(outcome, message)

    return TestClient(app)


def test_handler_returns_status_class_and_the_full_message_verbatim():
    for name, message in FULL_MESSAGES.items():
        r = _client_raising(Outcome(name), message).get("/boom")
        assert r.status_code == outcome_http_table()[name]
        assert r.json() == {"outcome": name, "message": message}


def test_a_message_is_never_invented_when_the_spec_gives_none():
    r = _client_raising(Outcome.FORBIDDEN, None).get("/boom")
    assert r.status_code == 403
    assert r.json() == {"outcome": "FORBIDDEN", "message": None}


def test_create_app_registers_the_handler():
    app = create_app()

    @app.get("/__boom__")
    def boom():
        raise OutcomeError(Outcome.CONFLICT, FULL_MESSAGES["CONFLICT"])

    r = TestClient(app).get("/__boom__")
    assert (r.status_code, r.json()["outcome"]) == (409, "CONFLICT")
