from dataclasses import dataclass
from typing import Optional

@dataclass
class HeldOption:
    symbol: str
    quantity: int
    gainPct: float
    daysHeld: int
    underlyingSymbol: str
    delta: Optional[float]
    theta: Optional[float]
    gamma: Optional[float]
    vega: Optional[float]
