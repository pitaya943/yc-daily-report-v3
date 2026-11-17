"""E2E 冒煙測試的資料準備（T-307）。只連本機 PostgreSQL，不 import 產品程式（`app.*`）。

    python3 tests/e2e/seed.py            建立（先清掉上一次留下的同名資料，所以可重複執行）
    python3 tests/e2e/seed.py --cleanup  只清掉

為什麼不 import 產品程式：E2E 要證明的是「從外面（HTTP＋瀏覽器）看到的行為」。如果資料準備也走產品的函式，
產品改壞時資料準備可能跟著壞得一樣，測試就看不出來。代價：密碼雜湊的格式在這裡複製了一份
（`scrypt$n=…,r=…,p=…$salt$digest`，見 app/core/session.py）。格式改了，登入會失敗，冒煙測試馬上紅，
不會默默放行；那時只要同步改這裡。

「只連本機」的防線：連線前以子行程執行 `python3 -m app.core.local_url`（與 scripts/dev/* 同一份檢查），
被拒絕就整個停止，所以防線照常生效。
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys

import psycopg

DEFAULT_URL = "postgresql://postgres@127.0.0.1:5433/yc"
PASSWORD = "e2e-password"  # 只存在於這個測試用的本機資料庫；不是任何真實帳戶的密碼

# 帳戶名稱放在 spec/background.md 的名單之外，避免與規格的固定帳戶混在一起
ADMIN = "E2E管理員"
ALICE = "E2E甲"
BOB = "E2E乙"
NAMES = (ADMIN, ALICE, BOB)

# (提交者, 日期)：兩張一般（WEST）回報，日期不同，篩選才看得出差別
REPORTS = ((ALICE, "2026-11-10"), (BOB, "2026-11-11"))


def guard() -> str:
    url = os.environ.get("DATABASE_URL") or DEFAULT_URL
    r = subprocess.run([sys.executable, "-m", "app.core.local_url"], env={**os.environ, "DATABASE_URL": url}, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{(r.stdout + r.stderr).strip()}。E2E 只使用本機 PostgreSQL。")
    return url


def scrypt_hash(password: str) -> str:
    n, r, p = 2**17, 8, 1
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=2 * 128 * n * r, dklen=32)
    b64 = lambda raw: base64.b64encode(raw).decode("ascii")  # noqa: E731
    return f"scrypt$n={n},r={r},p={p}${b64(salt)}${b64(digest)}"


def cleanup(conn: psycopg.Connection) -> None:
    ids = "select id from yc_v3.accounts where name = any(%s)"
    names = list(NAMES)
    # 依外鍵由子到父；report_items、report_crew 隨 reports 一起 cascade
    conn.execute(f"delete from yc_v3.reports where submitter_id in ({ids})", (names,))
    conn.execute(f"delete from yc_v3.report_crew where account_id in ({ids})", (names,))
    conn.execute(f"delete from yc_v3.sessions where account_id in ({ids})", (names,))
    conn.execute(f"delete from yc_v3.sign_in_failures where account_id in ({ids})", (names,))
    conn.execute(f"delete from yc_v3.audit_log where actor_account_id in ({ids})", (names,))
    conn.execute("delete from yc_v3.accounts where name = any(%s)", (names,))


def seed(conn: psycopg.Connection) -> None:
    cleanup(conn)
    pw = scrypt_hash(PASSWORD)
    ids = {}
    for name, role in ((ADMIN, "ADMIN"), (ALICE, "USER"), (BOB, "USER")):
        ids[name] = conn.execute(
            "insert into yc_v3.accounts(name, role, zone, password_hash) values (%s, %s, 'WEST', %s) returning id", (name, role, pw)
        ).fetchone()[0]
    for submitter, day in REPORTS:
        rid = conn.execute(
            "insert into yc_v3.reports(submitter_id, report_date, catalogue, status, created_at, updated_at) "
            "values (%s, %s, 'WEST', 'PENDING', now(), now()) returning id",
            (ids[submitter], day),
        ).fetchone()[0]
        conn.execute("insert into yc_v3.report_items(report_id, item_code, tenths) values (%s, 'direct_13', 10)", (rid,))


def main() -> None:
    url = guard()
    with psycopg.connect(url) as conn:  # with 區塊結束時提交；例外時回滾
        if "--cleanup" in sys.argv:
            cleanup(conn)
            print("e2e: 已清掉測試資料")
        else:
            seed(conn)
            print(f"e2e: 已建立 {len(NAMES)} 個帳戶與 {len(REPORTS)} 張回報")


if __name__ == "__main__":
    main()
