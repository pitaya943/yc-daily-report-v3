"""tests/ci 共用：用暫存的 git repo 重現「目標分支 → PR 分支」，讓 CI 檢查在真實的 git 歷史上執行。

不碰資料庫（覆寫 tests/conftest.py 的 autouse fixture），也不依賴目前 repo 的內容。
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from scripts.ci.checks import BOT_EMAIL, Ctx

TICKET = textwrap.dedent("""\
    ---
    id: {id}
    title: demo
    milestone: M9
    depends_on: []
    migration: {migration}
    migration_number: {number}
    allowed_paths:
    {paths}
    status: todo
    ---

    # {id} demo

    ## 完成條件

    {done}

    ## 範圍

    只能修改 allowed_paths。
""")


def make_ticket(tid="T-900", paths=("app/feature/**",), migration=False, number="null", done="1. 見規則。"):
    return TICKET.format(
        id=tid, migration="true" if migration else "false", number=number,
        paths="\n".join(f"  - {p}" for p in paths), done=done,
    )


@pytest.fixture(autouse=True)
def world():
    """CI 檢查的測試不需要資料庫：覆寫 tests/conftest.py 的 autouse fixture。"""
    yield


class Repo:
    """暫存 git repo。`base` 是目標分支，`branch()` 開出 PR 分支。"""

    def __init__(self, root: Path):
        self.root = root
        self._git("init", "-q", "-b", "milestone/M9")

    def _git(self, *args, author=BOT_EMAIL, check=True):
        env = {
            "GIT_AUTHOR_NAME": "tester", "GIT_AUTHOR_EMAIL": author,
            "GIT_COMMITTER_NAME": "tester", "GIT_COMMITTER_EMAIL": author,
            "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.root),
        }
        r = subprocess.run(["git", *args], cwd=self.root, env=env, capture_output=True, text=True, check=False)
        if check and r.returncode != 0:
            raise AssertionError(r.stderr)
        return r.stdout.strip()

    def write(self, files: dict[str, str | None]):
        for path, content in files.items():
            p = self.root / path
            if content is None:
                p.unlink()
                continue
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

    def commit(self, files: dict[str, str | None], author=BOT_EMAIL, msg="change"):
        self.write(files)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", msg, author=author)
        return self._git("rev-parse", "HEAD")

    def branch(self, name):
        self._git("checkout", "-q", "-b", name)

    def checkout(self, name):
        self._git("checkout", "-q", name)

    def ctx(self, head_ref="ticket/T-900", base_ref="milestone/M9", pr_body="", base="milestone/M9") -> Ctx:
        return Ctx(root=self.root, base=base, head="HEAD", base_ref=base_ref, head_ref=head_ref, pr_body=pr_body)


@pytest.fixture
def repo(tmp_path):
    """目標分支上有 ticket T-900（allowed_paths: app/feature/**）；已切到 ticket/T-900。"""
    r = Repo(tmp_path)
    r.commit({"docs/tickets/T-900.md": make_ticket(), "README.md": "base\n", "tests/implemented.txt": "AAA-R01\n"},
             msg="base")
    r.branch("ticket/T-900")
    return r
