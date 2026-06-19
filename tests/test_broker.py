import pytest
from kronos.broker.base import Broker, Order
from kronos.broker.fyers import FyersBroker, BinanceBroker

class MockBroker(Broker):
    def place_order(self, order: Order) -> str:
        return "mock_id_123"

    def cancel_order(self, order_id: str) -> bool:
        return True

    def get_positions(self) -> list[dict]:
        return []

    def get_balance(self) -> float:
        return 1000.0

def test_mock_broker():
    broker = MockBroker()
    order = Order(symbol="AAPL", qty=10, side="BUY", order_type="MARKET")
    assert broker.place_order(order) == "mock_id_123"
    assert broker.get_balance() == 1000.0
    assert broker.cancel_order("mock_id_123") is True

def test_fyers_broker_instantiation():
    broker = FyersBroker()
    assert hasattr(broker, 'place_order')

def test_binance_broker_instantiation():
    broker = BinanceBroker()
    assert hasattr(broker, 'place_order')
