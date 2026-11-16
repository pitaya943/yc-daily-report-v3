"""行為者：誰在做這個動作。稽核與權限檢查共用，所以獨立成一個檔（避免兩邊互相 import）。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    USER = "USER"
    SYSTEM = "SYSTEM"  # 排程與自動動作（spec/glossary.md）


@dataclass(frozen=True)
class Actor:
    id: int | None  # accounts.id；SYSTEM 沒有帳戶
    name: str
    role: Role


SYSTEM = Actor(id=None, name="SYSTEM", role=Role.SYSTEM)
