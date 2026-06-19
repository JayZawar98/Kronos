import time
import threading
from datetime import datetime
from kronos.data.repository import get_setting, set_setting, get_open_positions, open_position, close_position, get_portfolio, update_sell_signal_count, update_position_peak_price
from kronos.strategy.strategist import StrategyAnalyzer
from kronos.research.skills import SkillsEngine
from kronos.strategy.objective_tracker import ObjectiveTracker
from kronos.research.node import ResearchNode
import kronos.broker.fyers as broker_api

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
    research_node = ResearchNode()
    
    # Initialize epoch tracking
    port = get_portfolio()
    current_equity = port["total_equity"]
    
    epoch_time_str = get_setting("epoch_start_time")
    week_eq_str = get_setting("epoch_week_start_equity")
    month_eq_str = get_setting("epoch_month_start_equity")
    
    if not epoch_time_str or not week_eq_str or not month_eq_str:
        epoch_start_time = datetime.now()
        start_of_week = current_equity
        start_of_month = current_equity
        set_setting("epoch_start_time", epoch_start_time.isoformat())
        set_setting("epoch_week_start_equity", str(start_of_week))
        set_setting("epoch_month_start_equity", str(start_of_month))
    else:
        epoch_start_time = datetime.fromisoformat(epoch_time_str)
        start_of_week = float(week_eq_str)
        start_of_month = float(month_eq_str)
    
    while True:
        try:
            enabled = get_setting("daemon_enabled")
            if enabled == "true":
                analyzer.analyze()
                
                # Rollover check
                now = datetime.now()
                delta_days = (now - epoch_start_time).days
                port = get_portfolio()
                current_equity = port["total_equity"]
                
                if delta_days >= 7:
                    start_of_week = current_equity
                    set_setting("epoch_week_start_equity", str(start_of_week))
                    if delta_days >= 30:
                        start_of_month = current_equity
                        set_setting("epoch_month_start_equity", str(start_of_month))
                    
                    epoch_start_time = now
                    set_setting("epoch_start_time", epoch_start_time.isoformat())
                    print("[Daemon] Epoch Rollover Triggered. Memory updated.")
                
                # Hunger Engine evaluation
                port = get_portfolio()
                tracker = ObjectiveTracker(start_of_week, start_of_month, port["total_equity"])
                drive_state = tracker.evaluate()
                
                print(f"[Daemon] State: {drive_state['state']} | Reason: {drive_state['reason']}")
                
                if drive_state["state"] == "RESEARCH_MODE":
                    # Trigger Strategy Shift
                    shift_plan = research_node.execute_deep_research()
                    # Apply the greedy recovery multiplier
                    drive_state["position_multiplier"] = shift_plan.get("greedy_recovery_multiplier", 1.5)
                    # We reset the epoch tracking so it doesn't stay stuck in RESEARCH_MODE
                    start_of_week = port["total_equity"]
                    start_of_month = port["total_equity"]
                    epoch_start_time = datetime.now()
                    set_setting("epoch_start_time", epoch_start_time.isoformat())
                    set_setting("epoch_week_start_equity", str(start_of_week))
                    set_setting("epoch_month_start_equity", str(start_of_month))
                    print("[Daemon] Strategy Shift Applied. Resetting Epoch base balances.")

                _evaluate_trades(eval_func, analyzer, skills_engine, drive_state)
            time.sleep(60)
        except Exception as e:
            print(f"[Daemon] Error in loop: {e}")
            time.sleep(60)

def _evaluate_trades(eval_func, analyzer, skills_engine, drive_state):
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
                signal, confidence, last_price_raw, df = result
            else:
                signal, confidence, last_price_raw = result
                df = None
                
            # Currency Normalization: Convert USD assets to INR for unified portfolio math
            USD_INR_RATE = 83.5
            is_usd = category.startswith("crypto_") or category.startswith("us_")
            last_price = last_price_raw * USD_INR_RATE if is_usd else last_price_raw
                
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            now = datetime.now()
            
            pos = open_symbols.get(symbol)
            
            if not pos:
                # ── OPEN POSITION LOGIC ───────────────────────────────────────
                if signal == "BUY":
                    profile = analyzer.get_profile(category)
                    
                    # Apply Strategist Base
                    base_floor = profile.get("confidence_floor", 0.60)
                    base_mult = profile.get("position_mult", 1.0)
                    
                    # Apply Hunger Engine (VDBE) Modifications
                    confidence_floor = base_floor + drive_state.get("confidence_modifier", 0.0)
                    position_mult = base_mult * drive_state.get("position_multiplier", 1.0)
                    
                    # Clamp confidence floor between 0.3 and 0.95
                    confidence_floor = max(0.30, min(0.95, confidence_floor))
                    
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
                        
                        # Cash Overdraw Limit: Leave 5% buffer
                        trade_amount = min(trade_amount, cash * 0.95)
                        
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

if __name__ == "__main__":
    from kronos.model.kronos import Kronos, KronosTokenizer, KronosPredictor
    from kronos.data.fetcher import fetch_binance, fetch_yfinance, fetch_fyers, fetch_indian_stock
    from kronos.data.repository import init_db
    import numpy as np
    import pandas as pd

    TIMEFRAME_CONFIG = {
        "15m": {"binance_interval": "15m", "yf_interval": "15m", "yf_period": "60d",  "binance_days": 30, "fyers_interval": "15",  "fyers_days": 30},
        "1h":  {"binance_interval": "1h",  "yf_interval": "1h",  "yf_period": "60d",  "binance_days": 60, "fyers_interval": "60",  "fyers_days": 60},
        "4h":  {"binance_interval": "4h",  "yf_interval": "60m", "yf_period": "60d",  "binance_days": 90, "fyers_interval": "240", "fyers_days": 90},
        "1d":  {"binance_interval": "1d",  "yf_interval": "1d",  "yf_period": "2y",   "binance_days": 500, "fyers_interval": "D",   "fyers_days": 500},
    }
    
    def _load_df(source: str, symbol: str = None, ticker: str = None, interval: str = "1h") -> pd.DataFrame:
        cfg = TIMEFRAME_CONFIG.get(interval, TIMEFRAME_CONFIG["1h"])
        if source == "binance": return fetch_binance(symbol, cfg["binance_interval"], cfg["binance_days"])
        elif source == "fyers": return fetch_fyers(symbol, cfg["fyers_interval"], cfg["fyers_days"])
        elif source == "fyers_fallback": 
            df, _ = fetch_indian_stock(symbol, ticker, cfg["fyers_interval"], cfg["fyers_days"])
            return df
        else: return fetch_yfinance(ticker, cfg["yf_interval"], cfg["yf_period"])

    def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
        if len(df) < period + 1: return 0.0
        h, l, c = df["high"].values, df["low"].values, df["close"].values
        tr = np.maximum(h[1:] - l[1:], np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
        atr = float(np.mean(tr[-period:]))
        return atr / float(c[-1])

    def _generate_signal(df: pd.DataFrame, pred_df: pd.DataFrame, context_len: int = 2048) -> dict:
        last_close = float(df["close"].iloc[-1])
        forecast_close = float(pred_df["close"].iloc[-1])
        return_pct = (forecast_close - last_close) / last_close * 100.0
        atr_pct = _compute_atr(df) * 100.0
        threshold = max(atr_pct * 0.5, 0.10)
        
        if return_pct > threshold: signal = "BUY"
        elif return_pct < -threshold: signal = "SELL"
        else: signal = "HOLD"
        
        sigma = atr_pct / 2.0 if atr_pct > 0 else 0.5
        confidence = min(abs(return_pct) / max(threshold + sigma, 0.01), 1.0)
        
        return {"signal": signal, "confidence": round(confidence, 3)}

    print("[Daemon] Initializing Database...")
    init_db()

    print("[Daemon] Loading Kronos AI Model (kronos-mini) for automated trading...")
    try:
        _tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
        _model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
        _predictor = KronosPredictor(_model, _tokenizer, device="cpu", max_context=2048)
        print("[Daemon] AI Model Loaded Successfully!")
    except Exception as e:
        print(f"[Daemon] WARNING: AI Model load failed: {e}. Falling back to sleep.")
        _predictor = None

    def _daemon_evaluator(asset):
        if _predictor is None: return None
        try:
            source = asset["source"]
            symbol = asset["symbol"]
            ticker = asset.get("yf_ticker", symbol)
            interval = asset["interval"]
            
            df = _load_df(source, symbol=symbol, ticker=ticker, interval=interval)
            df.drop_duplicates(subset=["timestamps"], keep="last", inplace=True)
            ctx = _predictor.max_context if hasattr(_predictor, "max_context") else 512
            lookback = min(int(ctx * 0.8), len(df) - 30 - 5)
            if lookback < 10: return None
            
            x_df = df.iloc[-lookback:][["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])].copy()
            x_ts = df.iloc[-lookback:]["timestamps"].reset_index(drop=True)
            time_diff = x_ts.iloc[-1] - x_ts.iloc[-2] if len(x_ts) >= 2 else pd.Timedelta(hours=1)
            import pandas as pd
            y_ts = pd.Series(pd.date_range(start=x_ts.iloc[-1] + time_diff, periods=30, freq=time_diff))
            
            all_preds = []
            for _ in range(3):
                p = _predictor.predict(df=x_df.copy(), x_timestamp=x_ts.copy(), y_timestamp=y_ts.copy(), pred_len=30, T=0.8, top_p=0.9, sample_count=1)
                all_preds.append(p)
                
            pred_df = all_preds[0].copy()
            for col in ["open", "high", "low", "close"]:
                pred_df[col] = np.mean([p[col].values for p in all_preds], axis=0)
                
            sig_info = _generate_signal(df.iloc[-lookback:], pred_df, ctx)
            return sig_info["signal"], sig_info["confidence"], df.iloc[-1]["close"], df
        except Exception as e:
            print(f"[Daemon Evaluator Error] {e}")
            return None

    if _predictor is not None:
        print("[Daemon] Handing over to main trading loop...")
        daemon_loop(_daemon_evaluator)
    else:
        print("[Daemon] Idle mode. AI model not found.")
        while True:
            time.sleep(60)
