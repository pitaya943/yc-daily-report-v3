"""T-200 完成條件 4～6：共用版型 `base.html` 與 `render_page`（D-080、D-078）。

用一個只存在於測試裡的小 FastAPI 應用程式呼叫 `render_page`，模板放在 tmp_path，
並且 `{% extends "base.html" %}`——和 feature 的 router 實際使用的方式一樣。
"""
from __future__ import annotations

import json
from html.parser import HTMLParser

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.core.clock import clock
from app.core.db import get_db
from app.core.pages import render_page
from app.core.session import SESSION_COOKIE, issue_session

PAGE = """{% extends "base.html" %}
{% block title %}測試頁 {{ who }}{% endblock %}
{% block content %}<p id="who">{{ who }}</p>{% endblock %}
"""


class _Tags(HTMLParser):
    """收集所有標籤與屬性（屬性值已還原 HTML 實體，所以能直接 json.loads）。"""

    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.text.append(data)


def parse(html: str) -> _Tags:
    parser = _Tags()
    parser.feed(html)
    return parser


def body_attrs(html: str) -> dict[str, str | None]:
    bodies = [attrs for tag, attrs in parse(html).tags if tag == "body"]
    assert len(bodies) == 1
    return bodies[0]


@pytest.fixture
def client(tmp_path) -> TestClient:
    (tmp_path / "hello.html").write_text(PAGE, encoding="utf-8")
    app = FastAPI()

    @app.get("/page")
    def page(request: Request, who: str = "世界", conn=Depends(get_db)):
        return render_page(request, conn, tmp_path, "hello.html", {"who": who})

    test_client = TestClient(app, raise_server_exceptions=True)
    test_client.template_dir = tmp_path  # 讓個別測試能再掛路由到同一個模板目錄
    return test_client


def make_session(db, name: str = "Wen"):
    with db.cursor() as cur:
        cur.execute("select id from yc_v3.accounts where name = %s", (name,))
        account_id = cur.fetchone()[0]
    issued = issue_session(db, account_id)
    db.commit()
    return issued


def last_used(db, issued) -> object:
    with db.cursor() as cur:
        cur.execute("select last_used_at from yc_v3.sessions where anti_forgery_token = %s", (issued.anti_forgery_token,))
        return cur.fetchone()[0]


def get_page(client, issued=None, **params):
    headers = {"Cookie": f"{SESSION_COOKIE}={issued.token}"} if issued else {}
    return client.get("/page", params=params, headers=headers)


# ── 完成條件 6：已登入時 hx-headers 解析成 JSON 後等於該 session 的 token ──


def test_signed_in_body_carries_the_session_token_in_hx_headers(client, db):
    issued = make_session(db)
    response = get_page(client, issued)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert json.loads(body_attrs(response.text)["hx-headers"]) == {"X-CSRF-Token": issued.anti_forgery_token}


def test_each_session_gets_its_own_token(client, db):
    first, second = make_session(db, "Wen"), make_session(db, "Admin1")
    assert first.anti_forgery_token != second.anti_forgery_token
    assert json.loads(body_attrs(get_page(client, first).text)["hx-headers"]) == {"X-CSRF-Token": first.anti_forgery_token}
    assert json.loads(body_attrs(get_page(client, second).text)["hx-headers"]) == {"X-CSRF-Token": second.anti_forgery_token}


def test_hx_headers_is_a_single_quoted_attribute(client, db):
    issued = make_session(db)
    assert "hx-headers='{" in get_page(client, issued).text  # D-080 / 完成條件 4：單引號屬性


def test_hostile_token_characters_cannot_break_out_of_the_attribute(client, db):
    # 正常的 token 是 URL-safe base64；這裡直接把資料庫裡的值換成會破壞屬性的字元，確認 tojson 把它們轉義
    issued = make_session(db)
    hostile = "a'b\"c<d>&e"
    with db.cursor() as cur:
        cur.execute("update yc_v3.sessions set anti_forgery_token = %s where anti_forgery_token = %s", (hostile, issued.anti_forgery_token))
    db.commit()
    html = get_page(client, issued).text
    attrs = body_attrs(html)
    assert json.loads(attrs["hx-headers"]) == {"X-CSRF-Token": hostile}
    assert set(attrs) <= {"hx-headers"}  # 沒有因為跳出屬性而多出別的屬性
    assert "<d>" not in html


# ── 完成條件 6：未登入時沒有 hx-headers ──


def test_anonymous_body_has_no_hx_headers(client):
    response = get_page(client)
    assert response.status_code == 200
    assert "hx-headers" not in body_attrs(response.text)
    assert "X-CSRF-Token" not in response.text


def test_unknown_cookie_is_treated_as_anonymous(client):
    response = client.get("/page", headers={"Cookie": f"{SESSION_COOKIE}=not-a-real-session"})
    assert response.status_code == 200
    assert "hx-headers" not in body_attrs(response.text)


def test_idle_expired_session_gets_no_token(client, db):
    issued = make_session(db)
    clock.advance(clock_idle())
    response = get_page(client, issued)
    assert response.status_code == 200
    assert "hx-headers" not in body_attrs(response.text)
    assert issued.anti_forgery_token not in response.text


def clock_idle():
    from app.core.session import IDLE_TIMEOUT

    return IDLE_TIMEOUT  # 剛好滿 30 分鐘就逾時（IAM-R10）


# ── 完成條件 6：不延長 session 的閒置計時（D-078）──


def test_rendering_a_page_does_not_touch_last_used_at(client, db):
    issued = make_session(db)
    before = last_used(db, issued)
    clock.advance(clock_idle() / 2)  # 若被當成「使用」，時間一定會變
    response = get_page(client, issued)
    assert response.status_code == 200
    assert "hx-headers" in body_attrs(response.text)
    assert last_used(db, issued) == before


def test_rendering_a_page_writes_nothing_at_all(client, db):
    from tests.steps.common.steps import diff, take_snapshot

    issued = make_session(db)
    before = take_snapshot(db)
    get_page(client, issued)
    get_page(client)
    assert diff(before, take_snapshot(db)) == {}  # 整個資料庫不變


# ── 完成條件 6：頁面載入 /static/htmx.min.js；不連外部 CDN ──


def test_page_loads_the_pinned_htmx_from_the_same_origin(client, db):
    for response in (get_page(client, make_session(db)), get_page(client)):
        scripts = [attrs.get("src") for tag, attrs in parse(response.text).tags if tag == "script"]
        assert "/static/htmx.min.js" in scripts
        assert all(src.startswith("/") and not src.startswith("//") for src in scripts if src)  # 沒有外部網址


# ── 完成條件 4、5：block 與模板搜尋路徑 ──


def test_feature_template_extends_the_core_base_and_fills_both_blocks(client):
    parsed = parse(get_page(client, who="Wen").text)
    assert ("p", {"id": "who"}) in parsed.tags
    text = "".join(parsed.text)
    assert "測試頁 Wen" in text  # title block
    titles = [attrs for tag, attrs in parsed.tags if tag == "title"]
    assert len(titles) == 1


def test_context_values_are_html_escaped(client):
    html = get_page(client, who="<script>alert(1)</script>").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_feature_template_dir_wins_over_core_for_same_name(tmp_path, db):
    # feature 的 templates/ 排在 app/core/templates/ 前面；同名時 feature 的優先
    (tmp_path / "base.html").write_text("FEATURE-BASE {% block content %}{% endblock %}", encoding="utf-8")
    (tmp_path / "p.html").write_text('{% extends "base.html" %}{% block content %}x{% endblock %}', encoding="utf-8")
    app = FastAPI()

    @app.get("/p")
    def p(request: Request, conn=Depends(get_db)):
        return render_page(request, conn, tmp_path, "p.html", {})

    assert TestClient(app).get("/p").text.startswith("FEATURE-BASE")


def test_status_code_can_be_chosen(tmp_path):
    (tmp_path / "p.html").write_text('{% extends "base.html" %}{% block content %}x{% endblock %}', encoding="utf-8")
    app = FastAPI()

    @app.get("/p")
    def p(request: Request, conn=Depends(get_db)):
        return render_page(request, conn, tmp_path, "p.html", {}, status_code=404)

    assert TestClient(app).get("/p").status_code == 404


def test_context_cannot_override_the_token(client, db):
    # 呼叫端傳進來的 context 不能蓋掉 render_page 取得的 token
    issued = make_session(db)

    @client.app.get("/evil")
    def evil(request: Request, conn=Depends(get_db)):
        return render_page(request, conn, client.template_dir, "hello.html", {"who": "x", "csrf_token": "forged"})

    response = client.get("/evil", headers={"Cookie": f"{SESSION_COOKIE}={issued.token}"})
    assert json.loads(body_attrs(response.text)["hx-headers"]) == {"X-CSRF-Token": issued.anti_forgery_token}
    anonymous = client.get("/evil")
    assert "hx-headers" not in body_attrs(anonymous.text)

