"""密碼雜湊與 session（IAM-F01；閒置逾時、登出、anti-forgery 由 T-103 補在這個檔案）。

這個檔案是「誰登入了」的單一出口：其他模組不自己讀 cookie、不自己查 sessions 表，
一律用 `get_current_actor` 這個 FastAPI dependency 取得行為者。

## 密碼雜湊（D-056）

標準庫 `hashlib.scrypt`，N=2^17、r=8、p=1；每個帳戶獨立的隨機 salt；以 `hmac.compare_digest` 比對。
儲存的字串帶演算法與參數前綴，格式：

    scrypt$n=131072,r=8,p=1$<salt，base64>$<雜湊，base64>

驗證時使用「字串裡記下的」參數，不是目前的常數：日後調高成本或換演算法時，舊的雜湊仍能驗證，
再於下一次登入成功時換成新格式（漸進遷移）。取捨：scrypt 需要約 128 MiB 記憶體（128 * N * r），
一次雜湊約零點幾秒——這正是它擋暴力破解的方式；代價是登入請求要付這個成本。
不選 bcrypt／argon2 是因為它們需要新增依賴（D-056：不新增依賴）。

## Session

- 憑證是 32 位元組的隨機值（`secrets.token_urlsafe`），只放在 HttpOnly cookie；資料庫只存它的 SHA-256。
  資料庫外洩時，攻擊者拿到的雜湊不能直接當憑證用（憑證本身已有 256 位元的熵，所以不需要慢雜湊）。
- cookie 不設 Max-Age／Expires：關掉瀏覽器就消失，沒有「記住我」（Q-011）。
- 時間一律來自 `app/core/clock.py`。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

import psycopg
from fastapi import Depends, Request, Response

from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError

SESSION_COOKIE = "yc_session"

# ───────────────────────── 密碼雜湊（D-056）─────────────────────────

SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32
_PREFIX = "scrypt"
# 防止資料庫裡被竄改的參數讓一次驗證吃掉無限的記憶體／時間（驗證用的是字串裡的參數）
_MAX_N = 2**20


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # OpenSSL 的記憶體上限預設 32 MiB，N=2^17、r=8 需要約 128 MiB；給 2 倍的餘裕
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=2 * 128 * n * r, dklen=_KEY_BYTES)


def hash_password(password: str) -> str:
    """回傳帶演算法與參數前綴的雜湊字串；每次呼叫使用新的隨機 salt。"""
    salt = os.urandom(_SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"{_PREFIX}$n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """比對密碼與儲存的雜湊。格式不認得、參數不合理、沒有雜湊一律回傳 False，不丟例外。

    沒有雜湊（帳戶還沒設定密碼）時仍然做一次完整的 scrypt，讓「沒有這個帳戶／沒設密碼」
    與「密碼錯誤」花的時間相同（IAM-R03：兩者不可被分辨，時間也是一個管道）。
    """
    parsed = _parse(stored) if stored else None
    if parsed is None:
        _scrypt(password, b"\0" * _SALT_BYTES, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        return False
    (n, r, p), salt, expected = parsed
    actual = _scrypt(password, salt, n, r, p)
    return hmac.compare_digest(actual, expected)


def _parse(stored: str) -> tuple[tuple[int, int, int], bytes, bytes] | None:
    try:
        alg, params, salt_b64, digest_b64 = stored.split("$")
        if alg != _PREFIX:
            return None
        kv = dict(item.split("=") for item in params.split(","))
        n, r, p = int(kv["n"]), int(kv["r"]), int(kv["p"])
        if not (2 <= n <= _MAX_N and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 16):
            return None
        return (n, r, p), base64.b64decode(salt_b64, validate=True), base64.b64decode(digest_b64, validate=True)
    except (ValueError, KeyError, binascii.Error):
        return None


# ───────────────────────── Session ─────────────────────────

# 落地頁路徑（D-057）。頁面由 M2（/reports）、M3（/review）實作；這裡只決定「去哪裡」。
_LANDING = {Role.USER: "/reports", Role.ADMIN: "/review", Role.OWNER: "/review"}


def landing_path_for(role: Role) -> str:
    """登入後（或已登入的人打開登入頁時）該去的頁面。SYSTEM 不會登入，沒有落地頁。"""
    try:
        return _LANDING[role]
    except KeyError:
        raise ValueError(f"role {role.value} has no landing page") from None


@dataclass(frozen=True)
class IssuedSession:
    token: str  # 只在登入回應的 cookie 出現一次，資料庫裡只有它的雜湊
    anti_forgery_token: str  # T-103 的 anti-forgery 檢查比對的值


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_session(conn: psycopg.Connection, account_id: int) -> IssuedSession:
    """替帳戶發出新的 session。寫進呼叫端的 transaction，由呼叫端提交（與其他寫入同生同死）。"""
    issued = IssuedSession(token=secrets.token_urlsafe(32), anti_forgery_token=secrets.token_urlsafe(32))
    now = clock.now()
    conn.execute(
        "insert into yc_v3.sessions(account_id, token_hash, anti_forgery_token, created_at, last_used_at) "
        "values (%s, %s, %s, %s, %s)",
        (account_id, _token_hash(issued.token), issued.anti_forgery_token, now, now),
    )
    return issued


def set_session_cookie(response: Response, token: str) -> None:
    """HttpOnly（JavaScript 讀不到）、SameSite=Lax（跨站的 POST 不帶）、正式環境才加 Secure（IAM-R12）。

    不設 max_age／expires：這是 session cookie，關掉瀏覽器就消失，沒有「記住我」（Q-011）。
    Secure 由環境變數 APP_ENV=production 開啟：本機與測試用 http，加了 Secure 瀏覽器不會送回 cookie。
    """
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=os.environ.get("APP_ENV") == "production", path="/")


def actor_for_token(conn: psycopg.Connection, token: str) -> Actor | None:
    """session 憑證 → 行為者；沒有這個 session、或帳戶已封存（封存的帳戶不能登入）回傳 None。

    T-103 會在這裡加閒置逾時（last_used_at）與更新最後使用時間。
    """
    row = conn.execute(
        "select a.id, a.name, a.role from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
        "where s.token_hash = %s and not a.archived",
        (_token_hash(token),),
    ).fetchone()
    return None if row is None else Actor(id=row[0], name=row[1], role=Role(row[2]))


def get_current_actor(request: Request, conn: psycopg.Connection = Depends(get_db)) -> Actor:
    """FastAPI dependency：其他模組由這裡取得目前的行為者。沒有有效 session 就丟 UNAUTHENTICATED。

        @router.get("/x")
        def x(actor: Actor = Depends(get_current_actor)): ...

    UNAUTHENTICATED 沒有 spec 規定的錯誤字串（見 outcomes.py），所以 message 為 None。
    """
    token = request.cookies.get(SESSION_COOKIE)
    actor = actor_for_token(conn, token) if token else None
    if actor is None:
        raise OutcomeError(Outcome.UNAUTHENTICATED)
    return actor
