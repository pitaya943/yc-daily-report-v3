"""從 spec 取出被斷言的事實，測試與 spec 逐字比對，而不是把同一份清單抄進測試。"""
from __future__ import annotations

import re
from pathlib import Path

SPEC = Path(__file__).resolve().parents[3] / "spec"


def outcome_http_table() -> dict[str, int]:
    """spec/README.md「結果類別」表：類別 → HTTP status。"""
    out: dict[str, int] = {}
    for line in (SPEC / "README.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| `([A-Z_]+)` \|[^|]*\| (\d{3}) \|", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def audit_types() -> set[str]:
    """spec/appendix-c-audit-types.md 的合法類型（不含「已移除」那一行）。"""
    text = (SPEC / "appendix-c-audit-types.md").read_text(encoding="utf-8")
    table = text.split("已移除")[0]
    return set(re.findall(r"`([A-Z_]+)`", table)) - {"SYSTEM"}


def removed_audit_types() -> set[str]:
    text = (SPEC / "appendix-c-audit-types.md").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("已移除"))
    return set(re.findall(r"`([A-Z_]+)`", line))
