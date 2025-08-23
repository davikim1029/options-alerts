from dataclasses import dataclass,asdict,is_dataclass
from datetime import datetime

from typing import Optional

@dataclass
class OptionContract:
    symbol: str
    display: str
    underlyingPrice: float
    lastPrice: float
    bid:float
    bidSize: float
    ask: float
    askSize: float
    volume: int
    inTheMoney: str
    openInterest: int
    expiryDate: str
    strikePrice: float
    underlyingSymbol: str
    delta: Optional[float]
    gamma: Optional[float]
    theta: Optional[float]
    vega: Optional[float]
    impliedVolatility: Optional[float]

    def to_dict(obj):
        if is_dataclass(obj):
            result = asdict(obj)
            for key, value in result.items():
                if isinstance(value, datetime):
                    result[key] = value.isoformat()  # e.g. "2025-08-19T10:20:30"
            return result
        raise TypeError(f"Object of type {type(obj)} is not a dataclass")

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)