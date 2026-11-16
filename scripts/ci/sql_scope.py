"""migration 的靜態檢查：這個 SQL 有沒有碰 yc_v3 以外的東西（docs/ci-checks.md 的 migration-scope）。

流程：詞法分析（lex）→ 依分號切成語句 → 逐句套用規則。原則是 fail-closed：
解析不了、不認得、無法確定的語句一律回報違規，由人決定，而不是放行。

為什麼自己寫詞法分析而不是用 regex 清掉註解與字串：PostgreSQL 的詞法有幾個陷阱，
過去的版本就是栽在這些地方（Verifier 第 1 輪）：
* 有引號的識別字區分大小寫：`"YC_V3"` 是另一個 schema，不是 `yc_v3`；沒有引號的才會被折成小寫。
* dollar quoting：`$$…$$`、`$tag$…$tag$` 之間的文字是一個字串，裡面的 `;` 不是語句分隔；
  函式本體（plpgsql／sql）裡的語句會在之後被執行，所以本體要另外檢查，不能當成字串丟掉。
* `E'…'` 的反斜線跳脫、巢狀的 `/* … */`。

靜態檢查再嚴也追不完所有寫法（search_path、動態 SQL、型別轉換…）。
所以還有第二層：scripts/ci/migration_sandbox.py 把 migration 真的套用在拋棄式資料庫上，由引擎判定。
兩層都過才算過；這一層負責在 PR 上給出明確、可讀的原因。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SCHEMA = "yc_v3"
# 只能「引用」（不能當作操作對象）的系統 schema
READ_ONLY_SCHEMAS = {"pg_catalog"}


class SqlError(Exception):
    """詞法層就解析不了（字串或註解沒有結束…）。"""


@dataclass(frozen=True)
class Tok:
    kind: str  # word | qid | str | dollar | num | punct | op
    val: str  # word：原文；qid：去掉引號後的內容；dollar：本體；其他：原文
    pos: int


_WORD = re.compile(r"[^\W\d][\w$]*")
_NUM = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_DOLLAR = re.compile(r"\$(?:[^\W\d]\w*)?\$")
_STRING_PREFIX = {"e", "b", "x", "n"}


def lex(sql: str, base: int = 0) -> list[Tok]:
    toks: list[Tok] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c.isspace():
            i += 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
        elif sql.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif sql.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise SqlError("區塊註解沒有結束")
            i = j
        elif c == "'":
            prev = toks[-1] if toks else None
            prefixed = prev is not None and prev.kind == "word" and prev.val.lower() in _STRING_PREFIX and prev.pos + len(prev.val) == i + base
            backslash = prefixed and prev.val.lower() == "e"
            j = i + 1
            while True:
                if j >= n:
                    raise SqlError("字串沒有結束")
                if backslash and sql[j] == "\\":
                    j += 2
                    continue
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if prefixed:
                toks.pop()
            toks.append(Tok("str", sql[i + 1 : j], base + i))
            i = j + 1
        elif c == '"':
            j = i + 1
            while True:
                if j >= n:
                    raise SqlError("有引號的識別字沒有結束")
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            toks.append(Tok("qid", sql[i + 1 : j].replace('""', '"'), base + i))
            i = j + 1
        elif c == "$" and (m := _DOLLAR.match(sql, i)):
            tag = m.group(0)
            end = sql.find(tag, m.end())
            if end < 0:
                raise SqlError(f"dollar quoting {tag} 沒有結束")
            toks.append(Tok("dollar", sql[m.end() : end], base + m.end()))
            i = end + len(tag)
        elif m := _WORD.match(sql, i):
            toks.append(Tok("word", m.group(0), base + i))
            i = m.end()
        elif m := _NUM.match(sql, i):
            toks.append(Tok("num", m.group(0), base + i))
            i = m.end()
        else:
            toks.append(Tok("punct" if c in ";(),." else "op", c, base + i))
            i += 1
    return toks


def split_statements(toks: list[Tok]) -> list[list[Tok]]:
    out, cur = [], []
    for t in toks:
        if t.kind == "punct" and t.val == ";":
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def render(toks: list[Tok]) -> str:
    """把語句還原成「乾淨文字」：註解已去掉、字串內容換成 ''、dollar 本體換成 $$、有引號的識別字保留原樣（含大小寫）。"""
    s = ""
    prev = None
    for t in toks:
        if t.kind == "str":
            piece = "''"
        elif t.kind == "dollar":
            piece = "$$"
        elif t.kind == "qid":
            piece = '"' + t.val.replace('"', '""') + '"'
        else:
            piece = t.val
        tight = (t.kind == "punct" and t.val in ".,)") or (prev is not None and prev.kind == "punct" and prev.val in ".(")
        s += piece if (not s or tight) else " " + piece
        prev = t
    return s


# ---------------------------------------------------------------- 名稱

_ID = r'(?:"(?:[^"]|"")+"|[^\W\d][\w$]*)'
NAME = rf"{_ID}(?:\s*\.\s*{_ID})*"


def split_name(name: str) -> list[str]:
    """沒有引號的識別字折成小寫；有引號的保持原樣（區分大小寫）。"""
    parts = []
    for m in re.finditer(r'"((?:[^"]|"")+)"|([^\W\d][\w$]*)', name):
        parts.append(m.group(1).replace('""', '"') if m.group(1) is not None else m.group(2).lower())
    return parts


def bad_target(name: str) -> str | None:
    """操作對象必須明確寫成 yc_v3.名稱。沒寫 schema 會落在 search_path（可能是 public），一律不接受。"""
    parts = split_name(name)
    if len(parts) < 2:
        return f"{name} 沒有指定 schema（必須寫成 {SCHEMA}.名稱）"
    if parts[0] != SCHEMA:
        return f"{name} 不在 {SCHEMA}"
    return None


# ---------------------------------------------------------------- 逐句規則

_MODIFIERS = re.compile(
    r"(?is)^(?:or\s+replace|unique|temporary|temp|unlogged|global|local|materialized|recursive|concurrently|"
    r"if\s+not\s+exists|if\s+exists|only|constraint(?=\s+trigger\b))\b\s*"
)
_QUALIFIED_KINDS = {"table", "view", "sequence", "type", "domain", "function", "procedure", "index"}
_ON_KINDS = {"trigger", "policy", "rule"}
_GLOBAL_KINDS = {"database", "role", "user", "group", "tablespace", "publication", "subscription", "server", "system", "language"}
# 最上層只允許這些語句開頭；其他一律「無法判定」
_TOP_VERBS = {"create", "alter", "drop", "truncate", "comment", "grant", "revoke", "insert", "update", "delete", "select", "with", "set"}
_SAFE_SET = re.compile(
    r"(?is)^set\s+(?:local\s+|session\s+)?(?:lock_timeout|statement_timeout|idle_in_transaction_session_timeout|client_min_messages)\b"
)
_KEYWORDS_NOT_ALIAS = {
    "on", "set", "where", "values", "select", "using", "join", "inner", "left", "right", "full", "cross", "natural",
    "returning", "group", "order", "limit", "having", "union", "for", "from", "as", "and", "or", "when", "then", "end",
    "begin", "loop", "if", "else", "elsif", "into", "default", "check", "references", "not", "null", "primary", "unique",
}


def _strip_modifiers(text: str) -> str:
    while True:
        m = _MODIFIERS.match(text)
        if not m:
            return text
        text = text[m.end():]


def _split_top(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def _ddl(text: str) -> list[str]:
    """create / alter / drop / truncate：操作對象一律要是 yc_v3.xxx。"""
    m = re.match(r"(?is)(create|alter|drop|truncate)\b\s*(.*)", text)
    if not m:
        return []
    verb, rest = m.group(1).lower(), _strip_modifiers(m.group(2))
    if verb == "truncate":
        kind, rest = "table", re.sub(r"(?is)^table\b\s*", "", rest)
    else:
        km = re.match(r"(?is)([a-z]+)\b\s*(.*)", rest)
        if not km:
            return ["看不懂的語句"]
        kind, rest = km.group(1).lower(), _strip_modifiers(km.group(2))
    if kind in _GLOBAL_KINDS:
        return [f"{verb} {kind} 不是 {SCHEMA} 內的物件"]
    if kind == "schema":
        nm = re.match(NAME, rest)
        return [] if nm and split_name(nm.group(0)) == [SCHEMA] else [f"{verb} schema 只能對 {SCHEMA}（大小寫要完全一致）"]
    if kind == "extension":
        return [] if re.search(rf'(?i)\bschema\s+(?:{SCHEMA}\b|"{SCHEMA}")', rest) else [f"{verb} extension 必須指定 schema {SCHEMA}"]
    if kind in _ON_KINDS or (kind == "index" and verb == "create"):
        om = re.search(rf"(?is)\bon\s+(?:only\s+)?({NAME})", rest)
        err = bad_target(om.group(1)) if om else f"{verb} {kind} 找不到 ON 的資料表"
        return [err] if err else []
    if kind in _QUALIFIED_KINDS:
        problems = []
        for seg in _split_top(rest) if verb in ("drop", "truncate") else [rest]:
            nm = re.match(NAME, _strip_modifiers(seg.strip()))
            err = bad_target(nm.group(0)) if nm else f"{verb} {kind} 找不到物件名稱"
            if err:
                problems.append(err)
        sm = re.search(rf"(?is)\bset\s+schema\s+({NAME})", rest)
        if sm and split_name(sm.group(1)) != [SCHEMA]:
            problems.append(f"set schema 把物件搬出 {SCHEMA}")
        return problems
    return [f"不認得的 {verb} {kind}，無法判定是否只碰 {SCHEMA}"]


_DML_TARGETS = [
    (re.compile(rf"(?is)\binsert\s+into\s+({NAME})"), "insert into"),
    (re.compile(rf"(?is)\bupdate\s+(?:only\s+)?({NAME})\s+(?:as\s+)?(?:{_ID}\s+)?set\b"), "update"),
    (re.compile(rf"(?is)\bdelete\s+from\s+(?:only\s+)?({NAME})"), "delete from"),
    (re.compile(rf"(?is)\bmerge\s+into\s+(?:only\s+)?({NAME})"), "merge into"),
    (re.compile(rf"(?is)\bcopy\s+({NAME})"), "copy"),
    (re.compile(rf"(?is)\bcall\s+({NAME})"), "call"),
]


def _dml(text: str) -> list[str]:
    problems = []
    for rx, label in _DML_TARGETS:
        for m in rx.finditer(text):
            err = bad_target(m.group(1))
            if err:
                problems.append(f"{label}：{err}")
    return problems


_COMMENT = re.compile(
    rf"(?is)^comment\s+on\s+(column|table|view|materialized\s+view|index|sequence|function|procedure|type|domain|schema|"
    rf"trigger|policy|rule|constraint|extension|aggregate)\s+({NAME})(?:\s*\([^)]*\))?(?:\s+on\s+(?:domain\s+)?({NAME}))?\s+is\b"
)


def _comment(text: str) -> list[str]:
    m = _COMMENT.match(text)
    if not m:
        return ["comment on 的形式無法判定"]
    kind = re.sub(r"\s+", " ", m.group(1).lower())
    if kind == "schema":
        return [] if split_name(m.group(2)) == [SCHEMA] else [f"comment on schema 只能對 {SCHEMA}"]
    if kind == "extension":
        return ["comment on extension 不是 yc_v3 內的物件"]
    if kind in ("trigger", "policy", "rule", "constraint") and m.group(3):
        err = bad_target(m.group(3))
    else:
        err = bad_target(m.group(2))
    return [err] if err else []


def _grant(text: str) -> list[str]:
    m = re.match(r"(?is)^(grant|revoke)\b(.*?)\bon\b(.*)$", text)
    if not m:
        return ["grant/revoke 沒有 ON（角色授權）無法判定是否只碰 yc_v3"]
    target = re.split(r"(?i)\s+(?:to|from)\s+", m.group(3), maxsplit=1)[0].strip()
    am = re.match(r"(?is)^all\s+(?:tables|sequences|functions|procedures|routines)\s+in\s+schema\s+(.+)$", target)
    problems = []
    if am:
        for part in _split_top(am.group(1)):
            if split_name(part.strip()) != [SCHEMA]:
                problems.append(f"grant/revoke 的 schema {part.strip()} 不是 {SCHEMA}")
        return problems
    km = re.match(r"(?is)^(schema|table|sequence|function|procedure|routine|type|domain)\b\s*(.*)$", target)
    kind, names = (km.group(1).lower(), km.group(2)) if km else ("table", target)
    if re.match(r"(?i)^(database|tablespace|language|parameter|foreign|large)\b", target):
        return [f"grant/revoke on {target.split()[0]} 不是 {SCHEMA} 內的物件"]
    for part in _split_top(names):
        nm = re.match(NAME, part.strip())
        if not nm:
            problems.append("grant/revoke 找不到物件名稱")
        elif kind == "schema":
            if split_name(nm.group(0)) != [SCHEMA]:
                problems.append(f"grant/revoke 的 schema {nm.group(0)} 不是 {SCHEMA}")
        elif (err := bad_target(nm.group(0))) :
            problems.append(err)
    return problems


def _aliases(text: str) -> set[str]:
    names = {"new", "old", "excluded"}
    for rx in (
        rf'(?is)\bas\s+({_ID})',
        rf'(?is)\b{SCHEMA}\s*\.\s*{_ID}\s+(?:as\s+)?({_ID})',
        rf'(?is)\bfor\s+({_ID})\s+in\b',
    ):
        for m in re.finditer(rx, text):
            names |= {p for p in split_name(m.group(1)) if p not in _KEYWORDS_NOT_ALIAS}
    return names


def _dotted_names(text: str) -> list[str]:
    """所有 a.b 形式的名稱，第一段必須是 yc_v3（或系統 schema、別名）。"""
    aliases = _aliases(text)
    problems = []
    for m in re.finditer(NAME, text):
        parts = split_name(m.group(0))
        if len(parts) < 2:
            continue
        first = parts[0]
        if first == SCHEMA or first in READ_ONLY_SCHEMAS or first in aliases:
            continue
        problems.append(f"{m.group(0)} 引用了 {SCHEMA} 以外的 schema")
    return problems


_DYNAMIC = re.compile(r"(?is)\bexecute\b(?!\s+(?:function|procedure)\b)")
_BODY_DDL = re.compile(r"(?is)\b(create|alter|drop|truncate)\b")


def _common(text: str) -> list[str]:
    problems = []
    if _DYNAMIC.search(text):
        problems.append("含有動態 SQL（EXECUTE），無法靜態檢查它碰了哪個 schema")
    return problems + _dml(text) + _dotted_names(text)


# D-045：程序碼整類禁止（不再試著分析函式本體）。ticket front matter 為 allow_functions: true 時才例外，
# 由 Kuei 依 D-012 親自閱讀 SQL。函式本體的語句要等日後被呼叫才執行，沙盒層看不到，靜態分析又追不完所有寫法
# （單引號本體、別名遮蔽、字串參數裡的名稱…），所以直接不允許定義。
_PROCEDURAL = re.compile(
    r"(?is)^create\s+(?:or\s+replace\s+)?(?:constraint\s+|event\s+)?(function|procedure|trigger)\b"
)
_LARGE_OBJECT = re.compile(r"(?i)^(?:lo_\w*|pg_largeobject\w*)$")
D045 = "D-045：migration 不得{what}（只有 ticket front matter 為 allow_functions: true 時例外，由 Kuei 親自閱讀 SQL）"


def _procedural(stmt: list[Tok], text: str, first: str) -> list[str]:
    problems = []
    if first == "do":
        problems.append(D045.format(what="使用 DO 區塊"))
    m = _PROCEDURAL.match(text)
    if m:
        problems.append(D045.format(what=f"定義 {m.group(1).lower()}"))
    # 只看「詞」：字串、註解、dollar 本體裡的 lo_ 不算呼叫
    if any(t.kind in ("word", "qid") and _LARGE_OBJECT.match(t.val) for t in stmt):
        problems.append(D045.format(what="呼叫大型物件函式 lo_*（large object 不屬於任何 schema）"))
    return problems


def _statement(stmt: list[Tok], src: str, allow_functions: bool = False) -> list[str]:
    """最上層的一個語句。"""
    text = render(stmt)
    first = stmt[0].val.lower() if stmt[0].kind == "word" else ""
    snippet = text[:70]
    # 被禁止的整類寫法先報；其餘規則照樣檢查，讓訊息完整（例如本體裡碰了 public 也一併列出）
    banned = [] if allow_functions else [f"{v}：{snippet}" for v in _procedural(stmt, text, first)]
    if first == "do":
        # allow_functions: true 時本體仍要只碰 yc_v3
        return banned + [p for t in stmt if t.kind == "dollar" for p in _body(t, src)]
    if first not in _TOP_VERBS:
        return banned + [f"不在允許清單內的語句（只允許 create/alter/drop/truncate/comment/grant/revoke/insert/update/delete/select/with 與少數 set）：{snippet}"]
    problems: list[str] = []
    if first == "set" and not _SAFE_SET.match(text):
        return banned + [f"set 只允許 lock_timeout、statement_timeout 等無害的參數（不得改 search_path 或角色）：{snippet}"]
    if first in ("create", "alter", "drop", "truncate"):
        problems += _ddl(text)
    elif first == "comment":
        problems += _comment(text)
    elif first in ("grant", "revoke"):
        problems += _grant(text)
    if first != "set":
        problems += _common(text)
    problems = banned + [f"{v}：{snippet}" for v in problems]
    for t in stmt:
        if t.kind == "dollar":
            problems += _body(t, src)
    return problems


def _body(tok: Tok, src: str) -> list[str]:
    """dollar quoting 的本體（函式、程序）：裡面的語句日後會被執行，所以逐項檢查。"""
    try:
        inner = lex(tok.val, base=tok.pos)
    except SqlError as e:
        return [f"函式本體解析失敗（fail-closed）：{e}"]
    problems = []
    for stmt in split_statements(inner):
        text = render(stmt)
        found = []
        for m in _BODY_DDL.finditer(text):
            found += _ddl(text[m.start():])
        found += _common(text)
        problems += [f"函式本體：{v}：{text[:70]}" for v in found]
        for t in stmt:
            if t.kind == "dollar":
                problems += _body(t, src)
    return problems


def sql_violations(sql: str, allow_functions: bool = False) -> list[str]:
    """allow_functions：ticket front matter 為 allow_functions: true（D-045）時才傳 True。"""
    try:
        toks = lex(sql)
    except SqlError as e:
        return [f"解析失敗（fail-closed）：{e}"]
    out = []
    for stmt in split_statements(toks):
        out += _statement(stmt, sql, allow_functions)
    return out
