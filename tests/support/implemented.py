"""tests/implemented.txt 的解析，以及從 Rule 名稱取出規則 ID。"""
from __future__ import annotations

import re
from pathlib import Path

RULE_ID = re.compile(r"^\s*([A-Z]{2,5}-R\d+)\b")


def rule_id_of(rule_name: str | None) -> str | None:
    """`Rule: IAM-R01 The name list ...` → `IAM-R01`；沒有 ID 回傳 None。"""
    if not rule_name:
        return None
    m = RULE_ID.match(rule_name)
    return m.group(1) if m else None


def load_implemented(path: str | Path) -> set[str]:
    ids: set[str] = set()
    p = Path(path)
    if not p.exists():
        return ids
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids
