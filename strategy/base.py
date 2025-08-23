from abc import ABC, abstractmethod
from models.option import OptionContract
from models.generated.Position import Position

class BuyStrategy(ABC):
    @property
    def name(self) -> str:
        pass
    
    @abstractmethod
    def should_buy(self, option: OptionContract, context: dict) -> tuple[bool,str]:
        pass

class SellStrategy(ABC):
    @property
    def name(self) -> str:
        pass
    
    @abstractmethod
    def should_sell(self, position: Position, context: dict) -> tuple[bool,str]:
        pass
