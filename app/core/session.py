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
import functools
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
