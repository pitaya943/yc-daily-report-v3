"""完成條件 6：一個冒煙測試，從 HTTP 請求走到資料庫並通過。
完成條件 1：router 由 app/main.py 自動掃描註冊（這裡的 /health 來自 app/modules/system/health/router.py）。
"""
from fastapi.testclient import TestClient

from app.main import create_app


def test_http_request_reaches_the_database(world):
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # 這個數字只可能來自資料庫：spec/background.md 的 9 個帳戶
    assert body["accounts"] == 9
    # 時間來自 app.core.clock（background 設定的 2026-11-15 10:00 Asia/Taipei）
    assert body["now"] == "2026-11-15T10:00:00+08:00"


def test_every_scenario_starts_from_a_clean_database(world, db):
    # 上一個測試不留痕跡：只有 background 的 9 個帳戶，沒有其他表的殘留
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.accounts")
        assert cur.fetchone()[0] == 9
        cur.execute("insert into yc_v3.accounts(name, role, zone) values ('Temp','USER','WEST')")
    db.commit()


def test_previous_test_writes_are_gone(world, db):
    with db.cursor() as cur:
        cur.execute("select count(*) from yc_v3.accounts where name = 'Temp'")
        assert cur.fetchone()[0] == 0


def test_router_autodiscovery_registers_module_routers():
    assert "/health" in create_app().openapi()["paths"]


def test_autodiscovery_picks_up_a_new_feature_without_editing_main(tmp_path, monkeypatch):
    """放進 app/modules/<模組>/<feature>/router.py 就會被註冊；沒有 router.py 的 feature 不影響。"""
    import app.modules as modules_pkg

    for pkg in ("alpha", "alpha/beta", "alpha/empty"):
        (tmp_path / pkg).mkdir(parents=True, exist_ok=True)
        (tmp_path / pkg / "__init__.py").write_text("")
    (tmp_path / "alpha/beta/router.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.get('/__discovered__')\ndef f():\n    return {}\n"
    )
    monkeypatch.setattr(modules_pkg, "__path__", [*modules_pkg.__path__, str(tmp_path)])
    paths = create_app().openapi()["paths"]
    assert "/__discovered__" in paths and "/health" in paths
