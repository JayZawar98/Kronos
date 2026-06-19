import os
from dotenv import load_dotenv
import ccxt
from kronos.broker.base import Broker, Order

load_dotenv()

LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

class FyersBroker(Broker):
    def __init__(self):
        self.client = None
        if LIVE_TRADING_ENABLED:
            try:
                from fyers_apiv3 import fyersModel
                client_id = os.getenv("FYERS_CLIENT_ID")
                access_token = os.getenv("FYERS_ACCESS_TOKEN")
                if client_id and access_token:
                    self.client = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
            except Exception as e:
                print(f"[FyersBroker] Failed to initialize: {e}")

    def place_order(self, order: Order) -> str:
        if not LIVE_TRADING_ENABLED:
            print(f"[FyersBroker] 📄 PAPER TRADE: {order.side} {order.qty} {order.symbol} @ {order.price}")
            return "simulated_order_id"
            
        if not self.client:
            print(f"[FyersBroker] ❌ Client not initialized. Cannot trade {order.symbol}.")
            return ""
            
        data = {
            "symbol": order.symbol,
            "qty": int(order.qty),
            "type": 2 if order.order_type == "MARKET" else 1,
            "side": 1 if order.side == "BUY" else -1,
            "productType": "INTRADAY",
            "validity": "DAY",
            "disclosedQty": 0,
            "offlineOrder": False,
        }
        response = self.client.place_order(data=data)
        if response and response.get("s") == "ok":
            print(f"[FyersBroker] 🟢 ORDER PLACED: {order.side} {order.qty} {order.symbol}")
            return response.get("id", "unknown_id")
        else:
            print(f"[FyersBroker] ❌ ORDER FAILED: {response}")
            return ""

    def cancel_order(self, order_id: str) -> bool:
        return False

    def get_positions(self) -> list[dict]:
        return []

    def get_balance(self) -> float:
        return 0.0

class BinanceBroker(Broker):
    def __init__(self):
        self.client = None
        if LIVE_TRADING_ENABLED:
            try:
                api_key = os.getenv("BINANCE_API_KEY")
                secret = os.getenv("BINANCE_SECRET")
                if api_key and secret:
                    self.client = ccxt.binance({
                        'apiKey': api_key,
                        'secret': secret,
                        'enableRateLimit': True,
                    })
            except Exception as e:
                print(f"[BinanceBroker] Failed to initialize: {e}")

    def place_order(self, order: Order) -> str:
        if not LIVE_TRADING_ENABLED:
            print(f"[BinanceBroker] 📄 PAPER TRADE: {order.side} {order.qty} {order.symbol} @ {order.price}")
            return "simulated_order_id"
            
        if not self.client:
            print(f"[BinanceBroker] ❌ Client not initialized.")
            return ""
            
        ccxt_symbol = order.symbol.replace("USDT", "/USDT")
        try:
            if order.side == "BUY":
                res = self.client.create_market_buy_order(ccxt_symbol, order.qty)
            else:
                res = self.client.create_market_sell_order(ccxt_symbol, order.qty)
            print(f"[BinanceBroker] 🟢 ORDER PLACED: {order.side} {order.qty} {order.symbol}")
            return str(res.get("id", "unknown_id"))
        except Exception as e:
            print(f"[BinanceBroker] ❌ EXCEPTION placing order: {e}")
            return ""

    def cancel_order(self, order_id: str) -> bool:
        return False

    def get_positions(self) -> list[dict]:
        return []

    def get_balance(self) -> float:
        return 0.0

# --- Legacy wrapper for trader_daemon.py backwards compatibility ---
_fyers_instance = FyersBroker()
_binance_instance = BinanceBroker()

def place_order(symbol: str, side: str, qty: float, last_price: float, category: str) -> bool:
    order = Order(
        symbol=symbol,
        qty=qty,
        side=side,
        order_type="MARKET",
        price=last_price
    )
    
    if category.startswith("india"):
        res = _fyers_instance.place_order(order)
        return bool(res)
    elif category.startswith("crypto"):
        res = _binance_instance.place_order(order)
        return bool(res)
    else:
        print(f"[Broker API] ⚠️ Live trading not supported for category {category} yet. Simulating.")
        return True
