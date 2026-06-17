import time
import threading
from datetime import datetime
from database import get_setting, get_open_positions, open_position, close_position, get_portfolio, update_sell_signal_count, update_position_peak_price
from strategist import StrategyAnalyzer
from skills_engine import SkillsEngine
import broker_api

AUTO_TRADE_POOL = [
    # Crypto (Binance)
    {"source": "binance", "symbol": "BTCUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "ETHUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "BNBUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "SOLUSDT",  "interval": "1h", "category": "crypto_mid"},
    {"source": "binance", "symbol": "XRPUSDT",  "interval": "1h", "category": "crypto_mid"},

    # India Large Cap
    {"source": "fyers_fallback", "symbol": "NSE:RELIANCE-EQ",  "yf_ticker": "RELIANCE.NS",  "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:TCS-EQ",       "yf_ticker": "TCS.NS",       "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:HDFCBANK-EQ",  "yf_ticker": "HDFCBANK.NS",  "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:ICICIBANK-EQ", "yf_ticker": "ICICIBANK.NS", "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:INFY-EQ",      "yf_ticker": "INFY.NS",      "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:LT-EQ",        "yf_ticker": "LT.NS",        "interval": "60", "category": "india_large"},
    {"source": "fyers_fallback", "symbol": "NSE:WIPRO-EQ",     "yf_ticker": "WIPRO.NS",     "interval": "60", "category": "india_large"},

    # India Mid Cap
    {"source": "fyers_fallback", "symbol": "NSE:TATAMOTORS-EQ",  "yf_ticker": "TATAMOTORS.NS",  "interval": "60", "category": "india_mid"},
    {"source": "fyers_fallback", "symbol": "NSE:ZOMATO-EQ",      "yf_ticker": "ZOMATO.NS",      "interval": "60", "category": "india_mid"},
    {"source": "fyers_fallback", "symbol": "NSE:ADANIPORTS-EQ",  "yf_ticker": "ADANIPORTS.NS",  "interval": "60", "category": "india_mid"},
    {"source": "fyers_fallback", "symbol": "NSE:BAJFINANCE-EQ",  "yf_ticker": "BAJFINANCE.NS",  "interval": "60", "category": "india_mid"},
    {"source": "fyers_fallback", "symbol": "NSE:HAVELLS-EQ",     "yf_ticker": "HAVELLS.NS",     "interval": "60", "category": "india_mid"},

    # India Small Cap
    {"source": "fyers_fallback", "symbol": "NSE:IRFC-EQ",     "yf_ticker": "IRFC.NS",     "interval": "60", "category": "india_small"},
    {"source": "fyers_fallback", "symbol": "NSE:NMDC-EQ",     "yf_ticker": "NMDC.NS",     "interval": "60", "category": "india_small"},
    {"source": "fyers_fallback", "symbol": "NSE:ASHOKLEY-EQ", "yf_ticker": "ASHOKLEY.NS", "interval": "60", "category": "india_small"},

    # US Stocks
    {"source": "yfinance", "symbol": "NVDA", "interval": "1h", "category": "us_large"},
    {"source": "yfinance", "symbol": "AAPL", "interval": "1h", "category": "us_large"},
]

HOLD_RULES = {
    "india_large": {"min_hold_hours": 4,  "profit_pct": 3.0, "early_override_pct": 6.0,  "trail_pct": 1.5, "stop_pct": 2.0, "signals_needed": 3},
    "india_mid":   {"min_hold_hours": 2,  "profit_pct": 5.0, "early_override_pct": 10.0, "trail_pct": 2.5, "stop_pct": 3.0, "signals_needed": 3},
    "india_small": {"min_hold_hours": 6,  "profit_pct": 8.0, "early_override_pct": 15.0, "trail_pct": 4.0, "stop_pct": 4.0, "signals_needed": 3},
    "crypto_large":{"min_hold_hours": 2,  "profit_pct": 4.0, "early_override_pct": 8.0,  "trail_pct": 2.0, "stop_pct": 3.0, "signals_needed": 3},
    "crypto_mid":  {"min_hold_hours": 2,  "profit_pct": 5.0, "early_override_pct": 8.0,  "trail_pct": 2.0, "stop_pct": 3.5, "signals_needed": 3},
    "us_large":    {"min_hold_hours": 24, "profit_pct": 5.0, "early_override_pct": 10.0, "trail_pct": 2.5, "stop_pct": 3.0, "signals_needed": 2},
}

def daemon_loop(eval_func):
    print("[Daemon] Virtual Broker daemon started.")
    analyzer = StrategyAnalyzer()
    skills_engine = SkillsEngine()
    
    while True:
        try:
            enabled = get_setting("daemon_enabled")
            if enabled == "true":
                analyzer.analyze()
                _evaluate_trades(eval_func, analyzer, skills_engine)
            time.sleep(60)
        except Exception as e:
            print(f"[Daemon] Error in loop: {e}")
            time.sleep(60)

def _evaluate_trades(eval_func, analyzer, skills_engine):
    open_pos = get_open_positions()
    open_symbols = {p["symbol"]: p for p in open_pos}
    
    # Count positions per category for correlation cap
    cat_counts = {}
    for p in open_pos:
        cat = p.get("category", "crypto_mid")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
    
    for asset in AUTO_TRADE_POOL:
        symbol = asset["symbol"]
        category = asset["category"]
        
        try:
            result = eval_func(asset)
            if not result: continue
            
            if len(result) == 4:
                signal, confidence, last_price, df = result
            else:
                signal, confidence, last_price = result
                df = None
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            
            pos = open_symbols.get(symbol)
            
            if not pos:
                # ── OPEN POSITION LOGIC ───────────────────────────────────────
                if signal == "BUY":
                    profile = analyzer.get_profile(category)
                    confidence_floor = profile.get("confidence_floor", 0.60)
                    position_mult = profile.get("position_mult", 1.0)
                    
                    if confidence > confidence_floor:
                        if cat_counts.get(category, 0) >= 2:
                            print(f"[Daemon] ⏸️ Skipping {symbol} BUY: category '{category}' cap reached (2 max)")
                            continue
                            
                        # --- Master Orchestrator Validation ---
                        is_allowed, veto_reason = skills_engine.evaluate_trade(asset, signal, df, open_pos)
                        if not is_allowed:
                            print(f"[Daemon] 🛑 STRATEGIST VETO on {symbol}: {veto_reason}")
                            continue
                            
                        port = get_portfolio()
                        cash = port["cash_balance"]
                        
                        # Apply Strategist position sizing
                        # RULE 3: Strict 2% equity risk cap
                        base_amount = cash * 0.02
                        trade_amount = base_amount * position_mult
                        
                        if trade_amount > 100:
                            qty = round(trade_amount / last_price, 4)
                            
                            # Route through Broker API
                            if broker_api.place_order(symbol, "BUY", qty, last_price, category):
                                open_position(symbol, "BUY", qty, last_price, timestamp, category)
                                skills_engine.increment_trade_counter()
                                cat_counts[category] = cat_counts.get(category, 0) + 1
                                print(f"[Daemon] 🟢 RECORDED BUY {qty} {symbol} @ {last_price} (Mult: {position_mult}x) [Orchestrator Approved]")
                            else:
                                print(f"[Daemon] ❌ BUY FAILED AT BROKER for {symbol}")
                        
            else:
                # ── CLOSE POSITION LOGIC (THREE ZONES) ────────────────────────
                rules = HOLD_RULES.get(pos["category"], HOLD_RULES["crypto_mid"])
                
                # Parse entry time
                try:
                    entry_time = datetime.strptime(pos["entry_time"], "%Y-%m-%d %H:%M:%S")
                except:
                    entry_time = now # Fallback
                    
                hours_held = (now - entry_time).total_seconds() / 3600.0
                pnl_pct = ((last_price - pos["entry_price"]) / pos["entry_price"]) * 100.0
                
                # Track peak price
                peak = pos.get("peak_price") or pos["entry_price"]
                if last_price > peak:
                    peak = last_price
                    update_position_peak_price(pos["id"], peak)
                
                should_sell = False
                reason = ""
                
                profile = analyzer.get_profile(pos["category"])
                dynamic_stop_pct = rules["stop_pct"] * profile.get("stop_loss_mult", 1.0)
                
                # 1. Hard stop loss
                if pnl_pct <= -dynamic_stop_pct:
                    should_sell = True
                    reason = f"STOP LOSS (-{dynamic_stop_pct:.1f}%)"
                    
                # 2. Zone 2 - Early Override
                elif pnl_pct >= rules["early_override_pct"]:
                    should_sell = True
                    reason = f"EARLY OVERRIDE (+{rules['early_override_pct']}%)"
                    
                # 3. Zone 3 - Trailing Stop
                elif pnl_pct >= rules["profit_pct"]:
                    trail_floor = peak * (1 - (rules["trail_pct"] / 100.0))
                    if last_price <= trail_floor:
                        should_sell = True
                        reason = f"TRAILING STOP HIT (dropped {rules['trail_pct']}% from peak)"
                
                # 4. Zone 1 / Standard exit (Min hold + Signals)
                elif hours_held >= rules["min_hold_hours"] and signal == "SELL":
                    new_count = pos.get("sell_signal_count", 0) + 1
                    update_sell_signal_count(pos["id"], new_count)
                    if new_count >= rules["signals_needed"]:
                        should_sell = True
                        reason = f"SIGNAL CONFIRMED ({new_count} SELLs after min hold)"
                elif signal == "BUY":
                    # Reset sell signal count if trend reverses
                    if pos.get("sell_signal_count", 0) > 0:
                        update_sell_signal_count(pos["id"], 0)
                        
                if should_sell:
                    # Route through Broker API
                    if broker_api.place_order(symbol, "SELL", pos['quantity'], last_price, pos["category"]):
                        close_position(pos["id"], last_price, timestamp)
                        cat_counts[category] = cat_counts.get(category, 0) - 1
                        print(f"[Daemon] 🔴 RECORDED SELL {pos['quantity']} {symbol} @ {last_price} — {reason}")
                    else:
                        print(f"[Daemon] ❌ SELL FAILED AT BROKER for {symbol}")

        except Exception as e:
            print(f"[Daemon] Error evaluating {symbol}: {e}")

def start_daemon(eval_func):
    t = threading.Thread(target=daemon_loop, args=(eval_func,), daemon=True)
    t.start()
