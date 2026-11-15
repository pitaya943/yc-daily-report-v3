#!/usr/bin/env python3
"""CI 檢查的命令列入口：`python3 scripts/ci/run.py <檢查名稱>`。

輸入從環境變數來（workflow 設定）：
  CI_BASE_SHA／CI_HEAD_SHA   目標分支與 PR head 的 commit
  CI_BASE_REF／CI_HEAD_REF   目標分支與來源分支的名稱
  CI_PR_BODY                 PR 說明（透過環境變數傳入，不插進 shell 指令，避免注入）
  YC_RULE_REPORT             done-when 讀取的規則報告（預設 rule-report.json）
migration-scope 另外需要本機 PostgreSQL（DATABASE_URL，只接受本機位址）。
違規會逐行印出並以 exit 1 結束；檢查本身無法進行（CheckError）也是 exit 1。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.ci import checks  # noqa: E402

NAMES = ["tests", "spec-readonly", "path-scope", "evidence", "migration-scope", "no-weakened-tests",
         "done-when", "strings", "commit-author", "lint"]


def sandbox_problems() -> list[str]:
    """migration-scope 的第二層：在拋棄式資料庫上真的執行（見 scripts/ci/migration_sandbox.py）。"""
    from app.core.db import database_url
    from scripts.ci import migration_sandbox

    migrations = [(p.name, p.read_text(encoding="utf-8")) for p in sorted((ROOT / "migrations").glob("*.sql"))]
    return migration_sandbox.run_sandbox(database_url(), migrations)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in NAMES:
        print(f"用法：run.py <{'|'.join(NAMES)}>", file=sys.stderr)
        return 2
    name = argv[1]
    ctx = checks.Ctx(
        root=ROOT,
        base=os.environ.get("CI_BASE_SHA", ""),
        head=os.environ.get("CI_HEAD_SHA", "HEAD"),
        base_ref=os.environ.get("CI_BASE_REF", ""),
        head_ref=os.environ.get("CI_HEAD_REF", ""),
        pr_body=os.environ.get("CI_PR_BODY", ""),
    )
    try:
        if name == "done-when":
            rp = Path(os.environ.get("YC_RULE_REPORT", "rule-report.json"))
            report = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None
            problems = checks.check_done_when(ctx, report)
        else:
            problems = getattr(checks, "check_" + name.replace("-", "_"))(ctx)
            if name == "migration-scope":
                problems += sandbox_problems()
    except checks.CheckError as e:
        print(f"[{name}] 無法檢查：{e}")
        return 1
    except Exception as e:  # noqa: BLE001  資料庫連不上、URL 被防線拒絕…：fail-closed，只印類型與第一行（不含連線字串）
        print(f"[{name}] 無法檢查：{type(e).__name__}：{str(e).splitlines()[0] if str(e) else ''}")
        return 1
    for p in problems:
        print(f"[{name}] {p}")
    print(f"[{name}] {'失敗：' + str(len(problems)) + ' 項' if problems else '通過'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
