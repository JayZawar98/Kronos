import os
from dotenv import load_dotenv
import ccxt

load_dotenv()

# Global Safety Switch
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"

# Fyers initialization (mocked or loaded if available)
fyers = None
if LIVE_TRADING_ENABLED:
    try:
        from fyers_apiv3 import fyersModel
        client_id = os.getenv("FYERS_CLIENT_ID")
        access_token = os.getenv("FYERS_ACCESS_TOKEN")
        if client_id and access_token:
            fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")
    except ImportError:
        print("[Broker] Fyers SDK not installed. Run: pip install fyers-apiv3")
    except Exception as e:
        print(f"[Broker] Failed to initialize Fyers: {e}")

# CCXT initialization (mocked or loaded if available)
binance = None
if LIVE_TRADING_ENABLED:
    try:
        api_key = os.getenv("BINANCE_API_KEY")
        secret = os.getenv("BINANCE_SECRET")
        if api_key and secret:
            binance = ccxt.binance({
                'apiKey': api_key,
                'secret': secret,
                'enableRateLimit': True,
            })
    except Exception as e:
        print(f"[Broker] Failed to initialize CCXT Binance: {e}")


def place_order(symbol: str, side: str, qty: float, last_price: float, category: str) -> bool:
    """
    Routes the order to the correct broker API.
    Returns True if the order was successfully placed (or simulated), False otherwise.
    """
    if not LIVE_TRADING_ENABLED:
        # Paper Trading Mode (Simulation)
        print(f"[Broker API] 📄 PAPER TRADE EXECUTED: {side} {qty} {symbol} @ {last_price}")
        return True
        
    try:
        if category.startswith("india"):
            if not fyers:
                print(f"[Broker API] ❌ Live trading enabled but Fyers not initialized. Cannot trade {symbol}.")
                return False
                
            # Place Fyers order
            # Fyers requires specific order dict format
            data = {
                "symbol": symbol,
                "qty": int(qty),  # Fyers equities require integer qty
                "type": 2,        # 2 = Market Order
                "side": 1 if side == "BUY" else -1,
                "productType": "INTRADAY",
                "validity": "DAY",
                "disclosedQty": 0,
                "offlineOrder": False,
            }
            response = fyers.place_order(data=data)
            if response and response.get("s") == "ok":
                print(f"[Broker API] 🟢 LIVE FYERS ORDER PLACED: {side} {qty} {symbol}")
                return True
            else:
                print(f"[Broker API] ❌ FYERS ORDER FAILED: {response}")
                return False

        elif category.startswith("crypto"):
            if not binance:
                print(f"[Broker API] ❌ Live trading enabled but Binance not initialized. Cannot trade {symbol}.")
                return False
                
            # Place CCXT order
            # Format symbol from "BTCUSDT" to "BTC/USDT" for CCXT
            ccxt_symbol = symbol.replace("USDT", "/USDT")
            if side == "BUY":
                order = binance.create_market_buy_order(ccxt_symbol, qty)
            else:
                order = binance.create_market_sell_order(ccxt_symbol, qty)
            print(f"[Broker API] 🟢 LIVE BINANCE ORDER PLACED: {side} {qty} {symbol}")
            return True
            
        else:
            # US Stocks or unhandled
            print(f"[Broker API] ⚠️ Live trading not supported for category {category} yet. Simulating.")
            return True
            
    except Exception as e:
        print(f"[Broker API] ❌ EXCEPTION placing order for {symbol}: {e}")
        return False
