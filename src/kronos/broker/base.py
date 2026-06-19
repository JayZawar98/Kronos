from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Order:
    symbol: str
    qty: float
    side: str          # "BUY" | "SELL"
    order_type: str    # "MARKET" | "LIMIT"
    price: float | None = None

class Broker(ABC):
    @abstractmethod
    def place_order(self, order: Order) -> str:
        """Returns order_id"""
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_positions(self) -> list[dict]:
        pass

    @abstractmethod
    def get_balance(self) -> float:
        pass
