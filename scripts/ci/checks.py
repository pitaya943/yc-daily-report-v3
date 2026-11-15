"""CI 檢查的實作（對應 docs/ci-checks.md 的每一列）。

設計重點
--------
* 只用標準函式庫：CI 的「政策檢查」job 不必安裝專案套件，也不會因為套件版本而壞掉。
* 每個檢查是一個函式 `check_xxx(ctx) -> list[str]`，回傳違規訊息；空 list 代表通過。
  CLI（scripts/ci/run.py）只負責把 GitHub 事件的資料填進 `Ctx`，不含判斷邏輯，
  所以 tests/ci/ 可以用暫存的 git repo 直接呼叫同一批函式，證明每個檢查真的會失敗。
* Ticket 檔（docs/tickets/T-xxx.md）一律從「目標分支」讀，不從 PR 的分支讀：
  否則 PR 可以先改自己的 allowed_paths 再通過 path-scope。
* fail-closed：看不懂的輸入（找不到 ticket、不認得的 SQL 語句）視為違規，而不是放行。
"""
from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

BOT_EMAIL = "354516064+bullet-bots@users.noreply.github.com"

# spec-readonly 的禁止清單（docs/ci-checks.md）。`X/**` 代表整個目錄。
FORBIDDEN = ("spec/**", "AGENTS.md", ".claude/**", ".github/**", "docs/decisions.md", "docs/board.md")

RULE_ID = r"[A-Z]{2,5}-R\d+"


class CheckError(Exception):
    """檢查無法進行（例如找不到 ticket）。CLI 一律當作失敗。"""


@dataclass
class Ctx:
    root: Path
    base: str = ""  # 目標分支的 commit（SHA 或 ref）
    head: str = "HEAD"  # PR 的 head commit
    base_ref: str = ""  # 目標分支名稱，例如 milestone/M0
    head_ref: str = ""  # 來源分支名稱，例如 ticket/T-002
    pr_body: str = ""


# ---------------------------------------------------------------- git 與檔案工具


def git(ctx: Ctx, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=ctx.root, capture_output=True, text=True, check=False)
    if check and r.returncode != 0:
        raise CheckError(f"git {' '.join(args)} 失敗：{r.stderr.strip()}")
    return r


def show(ctx: Ctx, rev: str, path: str) -> str | None:
    """`git show rev:path`；檔案不存在回傳 None。"""
    r = git(ctx, "show", f"{rev}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def blob(ctx: Ctx, rev: str, path: str) -> str | None:
    r = git(ctx, "rev-parse", "--verify", "--quiet", f"{rev}:{path}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def tree_files(ctx: Ctx, rev: str, *paths: str) -> list[str]:
    r = git(ctx, "ls-tree", "-r", "--name-only", rev, "--", *paths, check=False)
    return [p for p in r.stdout.splitlines() if p]


def changed_files(ctx: Ctx) -> list[tuple[str, str]]:
    """這個 PR 自己改的檔案：(狀態, 路徑)。三個點 = 從 merge-base 到 head，不含目標分支後來才有的變動。
    關掉 rename 偵測：改名一律拆成「刪除舊路徑 + 新增新路徑」，兩個路徑都要通過檢查。"""
    out = git(ctx, "diff", "--name-status", "--no-renames", "-z", f"{ctx.base}...{ctx.head}").stdout
    parts = out.split("\0")
    result = []
    for i in range(0, len(parts) - 1, 2):
        result.append((parts[i], parts[i + 1]))
    return result


def path_matches(pattern: str, path: str) -> bool:
    """`**` 跨目錄，`*` 不跨目錄，`?` 單一字元。"""
    rx, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            rx += ".*"
            i += 2
        elif pattern[i] == "*":
            rx += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            rx += "[^/]"
            i += 1
        else:
            rx += re.escape(pattern[i])
            i += 1
    return re.fullmatch(rx, path) is not None


# ---------------------------------------------------------------- ticket


def ticket_id_of(head_ref: str) -> str | None:
    m = re.fullmatch(r"ticket/(T-\d+)(?:[-/].*)?", head_ref)
    return m.group(1) if m else None


def parse_ticket(text: str) -> dict:
    """只解析 front matter 用到的欄位（不依賴 PyYAML）。"""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not m:
        raise CheckError("ticket 沒有 front matter")
    meta: dict = {"allowed_paths": []}
    key = None
    for line in m.group(1).splitlines():
        item = re.match(r"\s+-\s+(.+?)\s*$", line)
        if item and key == "allowed_paths":
            meta["allowed_paths"].append(item.group(1).strip("\"'"))
            continue
        kv = re.match(r"(\w+):\s*(.*?)\s*$", line)
        if kv:
            key = kv.group(1)
            if key != "allowed_paths":
                meta[key] = kv.group(2).strip("\"'")
    meta["migration"] = meta.get("migration", "false") == "true"
    return meta


def load_ticket(ctx: Ctx, ticket_id: str) -> tuple[dict, str]:
    """從目標分支讀 ticket；回傳 (front matter, 全文)。"""
    path = f"docs/tickets/{ticket_id}.md"
    text = show(ctx, ctx.base, path)
    if text is None:
        raise CheckError(f"目標分支 {ctx.base_ref or ctx.base} 上找不到 {path}")
    return parse_ticket(text), text


def ticket_context(ctx: Ctx) -> tuple[str, dict, str] | None:
    """來源分支是 ticket/* 時回傳 (ticket 編號, front matter, 全文)，不是 ticket 分支回傳 None。
    fail-closed：分支名稱是 ticket/ 開頭、卻不是 ticket/T-數字，或目標分支上沒有對應的 ticket 檔，一律拋 CheckError。"""
    if not ctx.head_ref.startswith("ticket/"):
        return None
    tid = ticket_id_of(ctx.head_ref)
    if tid is None:
        raise CheckError(f"分支 {ctx.head_ref} 的名稱不是 ticket/T-數字，找不到對應的 docs/tickets/T-xxx.md")
    meta, text = load_ticket(ctx, tid)
    return tid, meta, text


def done_section(ticket_text: str) -> str:
    m = re.search(r"^## 完成條件\s*\n(.*?)(?=^## |\Z)", ticket_text, re.S | re.M)
    return m.group(1) if m else ""


def rule_ids_in(ticket_text: str) -> list[tuple[str, int | None]]:
    """完成條件裡寫成 `IAM-R01`（2） 的規則 ID 與 scenario 數（沒寫數量則為 None）。"""
    found = []
    for m in re.finditer(rf"`({RULE_ID})`(?:（(\d+)）)?", done_section(ticket_text)):
        found.append((m.group(1), int(m.group(2)) if m.group(2) else None))
    return found


# ---------------------------------------------------------------- spec-readonly


def _explicit_pattern(pattern: str) -> bool:
    """allowed_paths 的這一條是否「明確列出」禁止清單裡的路徑（D-031）。
    明確 = 第一個萬用字元之前的固定前綴，已經落在禁止的目錄或檔案之內。
    `.github/workflows/**` 明確；`**` 或 `.github*` 不明確，不能用來開後門。"""
    prefix = re.split(r"[*?\[]", pattern, maxsplit=1)[0]
    if not prefix:
        return False
    for f in FORBIDDEN:
        if f.endswith("/**"):
            if prefix.startswith(f[:-2]):
                return True
        elif prefix == f:
            return True
    return False


def check_spec_readonly(ctx: Ctx) -> list[str]:
    bad: list[str] = []
    try:
        tc = ticket_context(ctx)
    except CheckError as e:
        # 找不到 ticket：沒有任何例外可以套用，禁止清單照樣生效，而且本身就是失敗
        bad.append(str(e))
        tc = (ctx.head_ref, {"allowed_paths": []}, "")
    if tc is None:
        return []  # 只管 ticket/* 的 PR
    tid, meta, _ = tc
    exceptions = [p for p in meta["allowed_paths"] if _explicit_pattern(p)]
    for status, path in changed_files(ctx):
        if any(path_matches(f, path) for f in FORBIDDEN) and not any(path_matches(p, path) for p in exceptions):
            bad.append(f"{tid} 不得修改 {path}（{status}）")
    return bad


# ---------------------------------------------------------------- path-scope


def check_path_scope(ctx: Ctx) -> list[str]:
    try:
        tc = ticket_context(ctx)
    except CheckError as e:
        return [str(e)]  # 找不到 ticket 就無從判斷範圍：失敗
    if tc is None:
        return []
    tid, meta, _ = tc
    bad = []
    for status, path in changed_files(ctx):
        if not any(path_matches(p, path) for p in meta["allowed_paths"]):
            bad.append(f"{path}（{status}）不在 {tid} 的 allowed_paths 內")
    return bad


# ---------------------------------------------------------------- evidence

_PLACEHOLDERS = {"無", "n/a", "na", "-", "todo", "tbd", "待補"}
_IMAGE = re.compile(r"\.(png|jpe?g|gif|webp)$", re.I)


def evidence_section(pr_body: str) -> str | None:
    m = re.search(r"^##[ \t]*證據[ \t]*\n(.*?)(?=^##[ \t]|\Z)", pr_body, re.S | re.M)
    if m is None:
        return None
    text = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S)
    return text.strip()


def _ticket_has_screens(meta: dict) -> bool:
    return any("templates" in p or "static" in p for p in meta["allowed_paths"])


def check_evidence(ctx: Ctx) -> list[str]:
    tc = ticket_context(ctx)
    if tc is None:
        return []
    tid, meta, _ = tc
    bad = []
    section = evidence_section(ctx.pr_body)
    if section is None:
        bad.append("PR 說明沒有「## 證據」一節")
    elif not section or section.lower() in _PLACEHOLDERS:
        bad.append("PR 說明的「證據」一節是空的")
    if _ticket_has_screens(meta):
        shots = [p for p in tree_files(ctx, ctx.head, f"docs/evidence/{tid}") if _IMAGE.search(p)]
        if not shots:
            bad.append(f"{tid} 涉及畫面，但 docs/evidence/{tid}/ 沒有任何截圖")
    return bad


# ---------------------------------------------------------------- migration-scope

from scripts.ci.sql_scope import sql_violations  # noqa: E402,F401  (re-export：測試與 CLI 都從 checks 取用)


def check_migration_scope(ctx: Ctx) -> list[str]:
    bad = []
    # 1. 所有 migration 只能操作 yc_v3
    for path in sorted(p for p in tree_files(ctx, ctx.head, "migrations") if re.fullmatch(r"migrations/[^/]+\.sql", p)):
        for v in sql_violations(show(ctx, ctx.head, path) or ""):
            bad.append(f"{path}：{v}")
    # 2. 已合併（目標分支上已存在）的 migration 不得被修改
    for _status, path in changed_files(ctx):
        if not re.fullmatch(r"migrations/[^/]+\.sql", path):
            continue
        base_blob = blob(ctx, ctx.base, path)
        if base_blob is not None and base_blob != blob(ctx, ctx.head, path):
            bad.append(f"{path} 已存在於目標分支，不得修改或刪除")
    # 3. 只有 migration: true 的 ticket 能新增 migration，編號等於 migration_number
    tc = ticket_context(ctx)
    if tc is not None:
        tid, meta, _ = tc
        for status, path in changed_files(ctx):
            if status != "A" or not re.fullmatch(r"migrations/[^/]+\.sql", path):
                continue
            if blob(ctx, ctx.base, path) is not None:
                continue
            if not meta["migration"]:
                bad.append(f"{tid} 的 migration 是 false，不得新增 {path}")
                continue
            number = re.match(r"migrations/(\d{4})_", path)
            if not number or number.group(1) != meta.get("migration_number", ""):
                bad.append(f"{path} 的編號必須是 {meta.get('migration_number')}（{tid} 的 migration_number）")
    return bad


# ---------------------------------------------------------------- no-weakened-tests

_SKIP_NAMES = {
    "skip", "skipif", "xfail", "importorskip", "skipIf", "skipUnless", "expectedFailure", "skipTest", "SkipTest", "Skipped",
}
_COLLECT_IGNORE = {"collect_ignore", "collect_ignore_glob"}
# 會在收集或執行階段動手腳的 pytest hook：在測試程式裡定義它們，等於可以把任何測試反選掉
_SELECTION_HOOKS = {
    "pytest_collection_modifyitems", "pytest_ignore_collect", "pytest_runtest_protocol", "pytest_runtest_setup",
    "pytest_runtest_call", "pytest_collection_finish", "pytest_pyfunc_call",
}
_DYNAMIC_CALLS = {"eval", "exec", "compile", "__import__"}
# 唯一的豁免：T-001 的 tests/implemented.txt 機制（不在清單內的 scenario 標成「尚未實作」）。
# 縮到最小：只有這一個檔案，而且必須與目標分支上的內容完全相同；改了哪怕一行，豁免就失效。
SKIP_EXEMPT = {"tests/support/bdd_plugin.py"}
_FEATURE_TAG = re.compile(r"^\s*@\S*(skip|xfail|wip|ignore)\b", re.I | re.M)
_BAD_OPTION = re.compile(r"^(--deselect|--ignore|--ignore-glob|--co|--collect-only|--continue-on-collection-errors)(=|$)|^-[km]")
_NARROWING_KEYS = {"norecursedirs", "collect_ignore"}


def weakening_in_python(source: str, filename: str) -> list[str]:
    """用 AST 找跳過／預期失敗的標記與等價物；字串與註解裡出現 skip 這個字不算。"""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{filename}:{e.lineno} 語法錯誤，無法檢查"]
    out = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute) and node.attr in _SKIP_NAMES:
            out.append(f"{filename}:{line} 出現 .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in _SKIP_NAMES | _COLLECT_IGNORE:
            out.append(f"{filename}:{line} 出現 {node.id}")
        elif isinstance(node, ast.ImportFrom):
            out += [f"{filename}:{line} import {a.name}" for a in node.names if a.name in _SKIP_NAMES | _COLLECT_IGNORE]
        elif isinstance(node, ast.Assign):
            out += [f"{filename}:{line} 設定 {t.id}" for t in node.targets if isinstance(t, ast.Name) and t.id in _COLLECT_IGNORE]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _SELECTION_HOOKS:
            out.append(f"{filename}:{line} 定義 {node.name}（可以把測試反選掉）")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _DYNAMIC_CALLS:
                out.append(f"{filename}:{line} 動態執行 {fn.id}()，無法檢查")
            elif isinstance(fn, ast.Attribute) and fn.attr in ("import_module", "__import__"):
                out.append(f"{filename}:{line} 動態 import，無法檢查")
            elif isinstance(fn, ast.Name) and fn.id in ("getattr", "setattr", "delattr") and len(node.args) >= 2:
                name = node.args[1]
                if not (isinstance(name, ast.Constant) and isinstance(name.value, str)):
                    out.append(f"{filename}:{line} {fn.id}() 的屬性名稱不是字串常數，無法檢查")
                elif name.value in _SKIP_NAMES | _COLLECT_IGNORE:
                    out.append(f"{filename}:{line} {fn.id}() 取用 {name.value}")
    return out


def _bad_pytest_options(tokens: list[str]) -> list[str]:
    return [t for t in tokens if _BAD_OPTION.match(t)]


def pytest_option_problems(root: Path) -> list[str]:
    """pytest 設定檔的 addopts（--deselect、-k、-m、--ignore…）與 workflow 的 pytest 指令。"""
    import configparser
    import shlex
    import tomllib

    out = []

    def opts_from(value) -> list[str]:
        return shlex.split(value) if isinstance(value, str) else [str(x) for x in (value or [])]

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            ini = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {}).get("ini_options", {})
        except tomllib.TOMLDecodeError:
            out.append("pyproject.toml 解析失敗，無法檢查 pytest 設定")
            ini = {}
        out += [f"pyproject.toml 的 addopts 含 {t}" for t in _bad_pytest_options(opts_from(ini.get("addopts")))]
        out += [f"pyproject.toml 設定 {k}（會縮小收集範圍）" for k in _NARROWING_KEYS & ini.keys()]
    for name, section in (("pytest.ini", "pytest"), ("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        path = root / name
        if path.exists():
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(path, encoding="utf-8")
            if cp.has_section(section):
                out += [f"{name} 的 addopts 含 {t}" for t in _bad_pytest_options(opts_from(cp.get(section, "addopts", fallback="")))]
                out += [f"{name} 設定 {k}（會縮小收集範圍）" for k in _NARROWING_KEYS if cp.has_option(section, k)]
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")) if (root / ".github" / "workflows").exists() else []:
        for n, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if "pytest" in line and not line.lstrip().startswith("#"):
                tail = line.split("pytest", 1)[1]
                try:
                    tokens = shlex.split(tail)
                except ValueError:
                    tokens = tail.split()
                out += [f"{wf.relative_to(root).as_posix()}:{n} pytest 指令含 {t}" for t in _bad_pytest_options(tokens)]
    return out


def read_implemented(text: str | None) -> set[str]:
    ids = set()
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def _scan_targets(root: Path) -> list[Path]:
    """tests/ 全部，加上 tests/ 以外任何位置的 conftest.py（根目錄、scripts/…）。"""
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", "spec"}
    found = {p for p in (root / "tests").rglob("*") if p.is_file()} if (root / "tests").exists() else set()
    for p in root.rglob("conftest.py"):
        if not skip_dirs & set(p.relative_to(root).parts):
            found.add(p)
    return sorted(found)


def check_no_weakened_tests(ctx: Ctx) -> list[str]:
    bad = []
    for p in _scan_targets(ctx.root):
        rel = p.relative_to(ctx.root).as_posix()
        if "__pycache__" in rel:
            continue
        if rel in SKIP_EXEMPT and (not ctx.base or show(ctx, ctx.base, rel) == p.read_text(encoding="utf-8")):
            continue  # 目標分支上原樣不變的 implemented.txt 機制
        if p.suffix == ".py":
            bad += weakening_in_python(p.read_text(encoding="utf-8"), rel)
        elif p.suffix == ".feature" and _FEATURE_TAG.search(p.read_text(encoding="utf-8")):
            bad.append(f"{rel} 有 skip／xfail 類的標籤")
    bad += pytest_option_problems(ctx.root)
    if ctx.base:
        before = read_implemented(show(ctx, ctx.base, "tests/implemented.txt"))
        now_file = ctx.root / "tests" / "implemented.txt"
        after = read_implemented(now_file.read_text(encoding="utf-8") if now_file.exists() else None)
        for rid in sorted(before - after):
            bad.append(f"tests/implemented.txt 少了 {rid}（只能增加，不能減少）")
    return bad


# ---------------------------------------------------------------- done-when / 規則報告


def check_done_when(ctx: Ctx, report: dict | None) -> list[str]:
    """report 是 scripts/ci/rule_report.py 產生的 {規則 ID: {scenario 鍵: 結果}}。"""
    implemented = read_implemented((ctx.root / "tests" / "implemented.txt").read_text(encoding="utf-8")
                                   if (ctx.root / "tests" / "implemented.txt").exists() else None)
    wanted: list[tuple[str, int | None]]
    tc = ticket_context(ctx)
    if tc is not None:
        wanted = rule_ids_in(tc[2])
    elif ctx.base_ref == "main" and re.fullmatch(r"milestone/M\d+", ctx.head_ref):
        # Milestone PR：該 milestone 所有 ticket 規劃的規則 ID 都要完成
        milestone = ctx.head_ref.split("/", 1)[1]
        wanted = []
        for path in sorted((ctx.root / "docs" / "tickets").glob("T-*.md")):
            text = path.read_text(encoding="utf-8")
            if parse_ticket(text).get("milestone") == milestone:
                wanted += rule_ids_in(text)
    else:
        return []
    bad = []
    rules = (report or {}).get("rules", {})
    for rid, count in wanted:
        if rid not in implemented:
            bad.append(f"{rid} 不在 tests/implemented.txt")
            continue
        scenarios = rules.get(rid, {})
        if not scenarios:
            bad.append(f"{rid} 沒有任何 scenario 被收集（規則 ID 與 feature 檔的 Rule 對不上？）")
            continue
        not_passed = {k: v for k, v in scenarios.items() if v != "passed"}
        if not_passed:
            bad.append(f"{rid} 有 {len(not_passed)} 個 scenario 沒有通過：{', '.join(sorted(set(not_passed.values())))}")
        if count is not None and len(scenarios) != count:
            bad.append(f"{rid} 的 ticket 寫 {count} 個 scenario，實際收集到 {len(scenarios)} 個")
    return bad


# ---------------------------------------------------------------- strings

_CJK = re.compile(r"[　-〿㐀-鿿＀-￯]")


def allowed_messages(appendix_text: str) -> set[str]:
    """附錄 B 允許出現在介面上的文字：「」裡的訊息，加上表格第一欄的欄位名稱。"""
    allowed = {m.strip() for m in re.findall(r"「([^」]+)」", appendix_text)}
    for line in appendix_text.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|?$", line):
            first = line.strip().strip("|").split("|", 1)[0].strip().strip("`")
            if first and _CJK.search(first):
                allowed.add(first)
    return allowed


# 非 Python 的產品檔案：樣板（templates/）與前端靜態檔（static/）
_FRONTEND_COMMENTS = {
    ".html": [r"\{#.*?#\}", r"<!--.*?-->"], ".htm": [r"\{#.*?#\}", r"<!--.*?-->"], ".jinja": [r"\{#.*?#\}", r"<!--.*?-->"],
    ".j2": [r"\{#.*?#\}", r"<!--.*?-->"], ".xml": [r"<!--.*?-->"], ".svg": [r"<!--.*?-->"],
    ".js": [r"/\*.*?\*/", r"(?m)(?<![:\w/])//[^\n]*"], ".mjs": [r"/\*.*?\*/", r"(?m)(?<![:\w/])//[^\n]*"],
    ".ts": [r"/\*.*?\*/", r"(?m)(?<![:\w/])//[^\n]*"], ".css": [r"/\*.*?\*/"],
}
# 一段「從中文字開始、到引號／標籤／樣板語法為止」的文字；`請輸入{{ name }}` 會只取到 `請輸入`，所以拼出來的訊息一定不符
_CJK_RUN = re.compile(r"[\u3000-\u303f\u3400-\u9fff\uff00-\uffef][^<>\"'`\n\r{}]*")


def _frontend_files(root: Path) -> list[Path]:
    app = root / "app"
    if not app.exists():
        return []
    return sorted(p for p in app.rglob("*") if p.is_file() and {"templates", "static"} & set(p.relative_to(app).parts))


def check_strings(ctx: Ctx) -> list[str]:
    appendix = ctx.root / "spec" / "appendix-b-fields.md"
    if not appendix.exists():
        return ["找不到 spec/appendix-b-fields.md"]
    allowed = allowed_messages(appendix.read_text(encoding="utf-8"))
    bad = []
    for p in sorted((ctx.root / "app").rglob("*.py")):
        rel = p.relative_to(ctx.root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError as e:
            bad.append(f"{rel}:{e.lineno} 語法錯誤，無法檢查")
            continue
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docstrings.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                # f-string：訊息必須逐字出現在附錄，不能在執行時拼出來
                if any(isinstance(v, ast.Constant) and _CJK.search(v.value) for v in node.values):
                    bad.append(f"{rel}:{node.lineno} f-string 含中文，錯誤訊息必須逐字寫成常數")
            elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
                if _CJK.search(node.value) and node.value.strip() not in allowed:
                    bad.append(f"{rel}:{node.lineno} 字串「{node.value[:40]}」不在 spec/appendix-b-fields.md")
    for p in _frontend_files(ctx.root):
        rel = p.relative_to(ctx.root).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # 圖片、字型等二進位檔
        for pattern in _FRONTEND_COMMENTS.get(p.suffix.lower(), []):
            # 註解不是使用者看得到的文字；換成同樣數量的換行，行號才不會跑掉
            text = re.sub(pattern, lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        for m in _CJK_RUN.finditer(text):
            run = m.group(0).rstrip()
            if run.strip("「」") not in allowed and run not in allowed:
                bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} 文字「{run[:40]}」不在 spec/appendix-b-fields.md")
    return bad


# ---------------------------------------------------------------- tests（workflow 的 tests job 本身）

_SELECTION_TAIL = re.compile(r"(?s)\|\||;\s*(?:true|:|exit\s+0)\b|&&\s*true\b|\bset\s+\+e\b")


def check_tests(ctx: Ctx) -> list[str]:
    """`tests` 這一項本身的守衛：確認 workflow 的 tests job 真的會在測試失敗時失敗。
    （規則 scenario 失敗時 pytest 回傳非零，由 tests/ci 用 pytester 實際跑一次來證明；
    這裡負責另一半：job 裡沒有任何寫法能把非零吞掉、把測試縮小，或把資料庫換成別的版本。）"""
    wf = ctx.root / ".github" / "workflows" / "ci.yml"
    if not wf.exists():
        return ["找不到 .github/workflows/ci.yml"]
    text = wf.read_text(encoding="utf-8")
    m = re.search(r"(?ms)^  tests:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text)
    if not m:
        return ["workflow 沒有 tests job"]
    block = m.group(1)
    bad = []
    if not re.search(r"(?m)^\s*image:\s*postgres:17\s*$", block):
        bad.append("tests job 沒有使用 postgres:17 service（D-033）")
    if re.search(r"(?m)^\s*continue-on-error:", block):
        bad.append("tests job 有 continue-on-error，失敗會被吞掉")
    if re.search(r"(?m)^\s*if:\s*(?:\$\{\{\s*)?(?:false|0)\b", block):
        bad.append("tests job 有永遠不執行的 if")
    lines = [ln for ln in block.splitlines() if "pytest" in ln and not ln.lstrip().startswith("#")]
    runs = [ln for ln in lines if re.search(r"\brun:|^\s*-?\s*python3?\s+-m\s+pytest|^\s*pytest\b", ln)]
    if not runs:
        bad.append("tests job 沒有執行 pytest")
    for ln in runs:
        tail = ln.split("pytest", 1)[1]
        if _SELECTION_TAIL.search(tail):
            bad.append(f"pytest 指令的結果可能被吞掉：{ln.strip()}")
        for t in _bad_pytest_options(tail.split()):
            bad.append(f"pytest 指令含 {t}：{ln.strip()}")
    return bad


# ---------------------------------------------------------------- commit-author


def check_commit_author(ctx: Ctx) -> list[str]:
    """PR 範圍內（head 有、目標分支沒有）的每個 commit，包含 merge commit，作者 email 都必須是機器帳號。
    只看 author，不看 committer：GitHub 網頁操作（例如 Update branch）會把 committer 記成 GitHub。"""
    out = git(ctx, "log", "--format=%H%x1f%ae%x1f%P", f"{ctx.head}", "--not", ctx.base).stdout
    bad = []
    for line in out.splitlines():
        sha, email, parents = line.split("\x1f")
        if email.strip().lower() != BOT_EMAIL:
            kind = "merge commit" if len(parents.split()) > 1 else "commit"
            bad.append(f"{kind} {sha[:7]} 的作者是 {email}，必須是 {BOT_EMAIL}")
    return bad


# ---------------------------------------------------------------- lint


def check_lint(ctx: Ctx, config: Path | None = None) -> list[str]:
    config = config or Path(__file__).with_name("ruff.toml")
    try:
        r = subprocess.run(
            ["ruff", "check", "--config", str(config), "--output-format", "concise", str(ctx.root)],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        raise CheckError("找不到 ruff（pip install ruff）") from None
    bad = []
    if r.returncode != 0:
        bad += [ln for ln in r.stdout.splitlines() if ln.strip() and not ln.startswith(("Found ", "[*]", "No fixes"))]
    # shell script 的語法
    for p in sorted((ctx.root / "scripts").rglob("*")):
        if p.is_file() and p.suffix in ("", ".sh"):
            first = p.read_text(encoding="utf-8", errors="ignore").split("\n", 1)[0]
            if first.startswith("#!") and "bash" in first:
                sh = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True, check=False)
                if sh.returncode != 0:
                    bad.append(f"{p.relative_to(ctx.root)}: bash 語法錯誤：{sh.stderr.strip()}")
    return bad
