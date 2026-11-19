"""銀行帳號的加解密（D-113）：AES-256-GCM，金鑰從環境變數 `BANK_NUMBER_KEY` 讀取。

    key = load_key()                       # bytes（32），或 None：金鑰缺少或格式不對（IAM-R43）
    blob = encrypt(key, "12345678901234", aad)
    plain = decrypt(key, blob, aad)        # 解不開 → Unreadable

設計選擇：
- 為什麼 AES-GCM：它是「認證加密」，密文被竄改或金鑰不對時解密一定失敗（驗證標籤不符），不會解出一串看似合理的亂碼。
  對照：AES-CBC 沒有完整性保護，要另外加 HMAC，容易做錯。
- 每次加密都用新的隨機 nonce（12 bytes，`os.urandom`）。GCM 在同一把金鑰下重複使用 nonce 會洩漏明文的關係，
  甚至讓攻擊者偽造密文，所以 nonce 絕不能固定或遞增到溢位。副作用：同一個帳號加密兩次，密文不同。
- 儲存格式：nonce ‖ 密文 ‖ 16 bytes 標籤，全部放在同一個 bytea 欄位（不需要另一欄放 nonce）。
- AAD（額外認證資料）綁定帳戶：把 A 的密文複製到 B 的列，解密會失敗，而不是顯示 A 的帳號。
- 金鑰缺少與格式不對視為同一件事（`load_key()` 回傳 None）：呼叫端的行為一樣（顯示「無法讀取」、不能修改），
  也就不必讓「哪裡錯了」的細節流到畫面或紀錄。這個模組不印出、不記錄、不放進例外訊息任何金鑰或明文。
- 為什麼不是每次請求都重新讀環境變數以外的地方：金鑰只活在環境（部署時由 Kuei 設定），不進資料庫、不進 repo。
  測試在自己的 fixture 裡設定測試用的金鑰；真正的金鑰永遠不提交。
- 金鑰輪替不在範圍內：換金鑰後，舊密文會是 `Unreadable`（顯示「無法讀取」），管理員重新設定銀行帳號即可。
"""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV = "BANK_NUMBER_KEY"
KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12  # GCM 的標準 nonce 長度（NIST SP 800-38D）


class Unreadable(Exception):
    """這份密文解不開：金鑰不是當初加密的那把、密文被改過、或密文屬於別的帳戶。訊息不含任何內容。"""


def load_key() -> bytes | None:
    """讀 `BANK_NUMBER_KEY`（base64 的 32 bytes）。沒設、空白、不是 base64、長度不是 32 → None。"""
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        return None
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        return None
    return key if len(key) == KEY_BYTES else None


def aad_for(account_id: int) -> bytes:
    """把密文綁在特定帳戶上（見模組說明）。"""
    return f"yc_v3.accounts/{account_id}/bank_number".encode("ascii")


def encrypt(key: bytes, plaintext: str, aad: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode("ascii"), aad)


def decrypt(key: bytes, blob: bytes, aad: bytes) -> str:
    blob = bytes(blob)  # psycopg 回傳 bytes；memoryview 也接受
    if len(blob) <= NONCE_BYTES:
        raise Unreadable()
    try:
        return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], aad).decode("ascii")
    except (InvalidTag, UnicodeDecodeError):
        raise Unreadable() from None
