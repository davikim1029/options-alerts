from __future__ import annotations
from models.generated.Position import Position
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class Account:
    accountId: Optional[str] = None
    Position: Optional[List[Position]] = None
    totalPages: Optional[int] = None
