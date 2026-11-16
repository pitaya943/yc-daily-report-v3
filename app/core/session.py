"""密碼雜湊與 session（IAM-F01 登入；IAM-F03 閒置逾時、登出、anti-forgery）。

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

## 閒置逾時、登出、anti-forgery（IAM-R10～R12）

`get_current_actor` 依序檢查（順序有意義）：
1. 有 session、帳戶未封存、距離最後使用**未滿** 30 分鐘（剛好 30 分鐘就逾時）→ 否則 `UNAUTHENTICATED`。
2. 不安全的方法（POST／PUT／PATCH／DELETE）要帶 `X-CSRF-Token`，且等於這個 session 的 anti-forgery token
   （`hmac.compare_digest`）→ 否則寫 `ACCESS_DENIED` 並丟 `FORBIDDEN`（D-053）。
3. 全部通過才把最後使用時間更新為現在（活動重新計時）。

被拒絕的請求除了 ACCESS_DENIED 之外不寫任何東西：不更新最後使用時間、也不順手刪掉逾時的 session 列。
取捨：逾時的列會留在表裡（M5 的清理排程可以處理）；換來的是「拒絕不改變狀態」這條規則沒有例外。

anti-forgery 用「每個 session 一個 token、放在標頭」而不是表單欄位：dependency 不必讀請求主體
（讀主體要 async，會把每個 DB 查詢放回 event loop），HTMX 以 `hx-headers` 帶上即可；
token 由 `GET /session`（或日後的版型）取得。cookie 的 SameSite=Lax 是第一道防線，token 是第二道。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import timedelta

import psycopg
from fastapi import Depends, Request, Response

from app.core import audit
from app.core.actor import Actor, Role
from app.core.clock import clock
from app.core.db import get_db
from app.core.outcomes import Outcome, OutcomeError

SESSION_COOKIE = "yc_session"
CSRF_HEADER = "X-CSRF-Token"
# IAM-R10：距離最後使用滿這段時間就逾時（剛好滿也算）
IDLE_TIMEOUT = timedelta(minutes=30)
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

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


# 登入端點改在 threadpool 執行（不阻塞 event loop）後，同時進行的 scrypt 最多有 threadpool 大小那麼多條（預設 40），
# 每條約 128 MiB；用號誌限制同時進行的數量，記憶體上限約 4 × 128 MiB，其餘的請求排隊。
_SCRYPT_SLOTS = threading.BoundedSemaphore(4)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    # OpenSSL 的記憶體上限預設 32 MiB，N=2^17、r=8 需要約 128 MiB；給 2 倍的餘裕
    with _SCRYPT_SLOTS:
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


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=os.environ.get("APP_ENV") == "production")


@dataclass(frozen=True)
class _SessionRow:
    id: int
    actor: Actor
    anti_forgery_token: str
    last_used_at: object


def _load(conn: psycopg.Connection, token: str) -> _SessionRow | None:
    """憑證 → session 列與行為者，只讀不寫。沒有這個 session、帳戶已封存（封存的帳戶不能登入）、
    或閒置滿 IDLE_TIMEOUT 都回傳 None。"""
    row = conn.execute(
        "select s.id, a.id, a.name, a.role, s.anti_forgery_token, s.last_used_at "
        "from yc_v3.sessions s join yc_v3.accounts a on a.id = s.account_id "
        "where s.token_hash = %s and not a.archived",
        (_token_hash(token),),
    ).fetchone()
    if row is None or clock.now() - row[5] >= IDLE_TIMEOUT:
        return None
    return _SessionRow(id=row[0], actor=Actor(id=row[1], name=row[2], role=Role(row[3])), anti_forgery_token=row[4], last_used_at=row[5])


def actor_for_token(conn: psycopg.Connection, token: str) -> Actor | None:
    """session 憑證 → 行為者（含閒置逾時檢查）；不更新最後使用時間，所以登入頁之類的唯讀查詢可以用。"""
    loaded = _load(conn, token)
    return None if loaded is None else loaded.actor


def anti_forgery_token_for(conn: psycopg.Connection, token: str) -> str | None:
    """目前有效 session 的 anti-forgery token；給頁面／HTMX 放進 `X-CSRF-Token`。"""
    loaded = _load(conn, token)
    return None if loaded is None else loaded.anti_forgery_token


def end_session(conn: psycopg.Connection, token: str) -> None:
    """登出：立刻刪除這個 session（只這一個；同一個人在別處的 session 不受影響）。由呼叫端提交。"""
    conn.execute("delete from yc_v3.sessions where token_hash = %s", (_token_hash(token),))


def get_current_actor(request: Request, conn: psycopg.Connection = Depends(get_db)) -> Actor:
    """FastAPI dependency：其他模組由這裡取得目前的行為者（IAM-R10～R12 的檢查都在這裡）。

        @router.get("/x")
        def x(actor: Actor = Depends(get_current_actor)): ...

    請用 `def`（不是 `async def`）寫端點：同步的資料庫呼叫才會在 threadpool 執行，不阻塞 event loop。
    UNAUTHENTICATED 與 FORBIDDEN 沒有 spec 規定的錯誤字串（見 outcomes.py），所以 message 為 None。
    """
    token = request.cookies.get(SESSION_COOKIE)
    loaded = _load(conn, token) if token else None
    if loaded is None:
        raise OutcomeError(Outcome.UNAUTHENTICATED)
    if request.method not in _SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER)
        if not sent or not hmac.compare_digest(sent.encode("utf-8"), loaded.anti_forgery_token.encode("utf-8")):
            # 先寫稽核（獨立連線、立刻提交），再拒絕；除此之外不寫任何東西（D-053）
            audit.write(loaded.actor, "ACCESS_DENIED", f"沒有有效的 anti-forgery token：{request.method} {request.url.path}")
            raise OutcomeError(Outcome.FORBIDDEN)
    conn.execute("update yc_v3.sessions set last_used_at = %s where id = %s", (clock.now(), loaded.id))
    conn.commit()
    return loaded.actor
