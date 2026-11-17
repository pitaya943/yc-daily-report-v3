"""T-200 完成條件 1～3：固定版本的 htmx.min.js（D-062、D-088）。

- 檔案的 sha256 必須等於 `app/core/pages.py` 記下的 `HTMX_SHA256`：檔案被換掉或改動時這裡會失敗。
- `GET /static/htmx.min.js` 不需要登入，內容與 repo 中的檔案相同。
- 只供應這一個檔案，不開放整個目錄（路徑穿越）。

這些測試不需要資料庫的資料，但沿用本目錄的 conftest（會清空並重建 yc_v3 的固定資料）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.pages import HTMX_SHA256, HTMX_VERSION
from app.main import create_app

HTMX_FILE = Path(__file__).resolve().parents[3] / "app" / "core" / "static" / "htmx.min.js"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_pinned_version_is_2_0_11():
    assert HTMX_VERSION == "2.0.11"  # D-088


def test_file_in_repo_matches_the_recorded_sha256():
    assert HTMX_FILE.is_file()
    assert sha256_of(HTMX_FILE.read_bytes()) == HTMX_SHA256


def test_recorded_sha256_is_a_full_lowercase_hex_digest():
    assert len(HTMX_SHA256) == 64
    assert HTMX_SHA256 == HTMX_SHA256.lower()
    int(HTMX_SHA256, 16)  # 不是十六進位會丟 ValueError


def test_served_without_signing_in_and_identical_to_the_file(client):
    response = client.get("/static/htmx.min.js")  # 沒有 cookie
    assert response.status_code == 200
    assert response.headers["content-type"].split(";")[0].strip() in {"text/javascript", "application/javascript"}
    assert sha256_of(response.content) == HTMX_SHA256
    assert response.content == HTMX_FILE.read_bytes()


@pytest.mark.parametrize(
    "path",
    [
        "/static/",
        "/static",
        "/static/session.py",
        "/static/htmx.js",
        "/static/htmx.min.js/",
        "/static/htmx.min.js/extra",
        "/static/../session.py",
        "/static/%2e%2e/session.py",
        "/static/..%2fsession.py",
        "/static/%2e%2e%2f%2e%2e%2fmain.py",
        "/static//etc/passwd",
        "/static/htmx.min.js%00.txt",
    ],
)
def test_only_the_one_file_is_served(client, path):
    response = client.get(path, follow_redirects=False)
    if response.status_code == 307:  # 多一條斜線只是轉去同一個檔案，不會供應別的東西
        assert response.headers["location"].endswith("/static/htmx.min.js")
        return
    assert response.status_code in {404, 405}
    assert b"create_app" not in response.content  # 不是原始碼
    assert sha256_of(response.content) != HTMX_SHA256


def test_a_sibling_file_in_the_static_directory_is_not_served(client):
    # 目錄裡日後可能有別的檔案（例如樣式表）；只有 htmx.min.js 有路由，其他一律 404
    probe = HTMX_FILE.parent / "t200-probe.txt"
    probe.write_text("probe", encoding="utf-8")
    try:
        assert client.get("/static/t200-probe.txt").status_code == 404
    finally:
        probe.unlink()
