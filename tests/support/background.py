"""解析 spec/background.md 的固定資料（單一來源：改規格不必改測試程式）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BACKGROUND_MD = Path(__file__).resolve().parents[2] / "spec" / "background.md"


@dataclass(frozen=True)
class Background:
    clock: datetime
    accounts: list[dict]


def _yes_no(v: str) -> bool:
    if v not in ("yes", "no"):
        raise ValueError(f"expected yes/no, got {v!r}")
    return v == "yes"


def parse_background(path: Path = BACKGROUND_MD) -> Background:
    text = path.read_text(encoding="utf-8")
    m = re.search(r'the clock is "([\d-]+ [\d:]+)" in ([\w/]+)', text)
    if not m:
        raise ValueError("background.md: clock step not found")
    clock = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(m.group(2)))

    rows = []
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if "these accounts exist:" in s:
            in_table = True
            continue
        if in_table:
            if not s.startswith("|"):
                break
            rows.append([c.strip() for c in s.strip("|").split("|")])
    header, *body = rows
    accounts = []
    for r in body:
        d = dict(zip(header, r))
        accounts.append({
            "name": d["name"], "role": d["role"], "zone": d["zone"],
            "big_meter": _yes_no(d["big_meter"]), "archived": _yes_no(d["archived"]),
        })
    if not accounts:
        raise ValueError("background.md: no accounts parsed")
    return Background(clock=clock, accounts=accounts)
