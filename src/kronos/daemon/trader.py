import time
import threading
import asyncio
import random
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from kronos.data.repository import get_setting, set_setting, get_open_positions, open_position, close_position, get_portfolio, update_sell_signal_count, update_position_peak_price
from kronos.strategy.strategist import StrategyAnalyzer
from kronos.research.skills import SkillsEngine
from kronos.strategy.objective_tracker import ObjectiveTracker
from kronos.research.node import ResearchNode
import kronos.broker.fyers as broker_api
import numpy as np
import pandas as pd
import pytz

AUTO_TRADE_POOL = [
    # Crypto (Binance)
    {"source": "binance", "symbol": "BTCUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "ETHUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "BNBUSDT",  "interval": "1h", "category": "crypto_large"},
    {"source": "binance", "symbol": "SOLUSDT",  "interval": "1h", "category": "crypto_mid"},
    {"source": "binance", "symbol": "XRPUSDT",  "interval": "1h", "category": "crypto_mid"},

    # India Large Cap (Angel One token / Yahoo Finance)
    {"source": "angelone_fallback", "symbol": "RELIANCE",  "token": "2885",  "yf_ticker": "RELIANCE.NS",  "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "TCS",       "token": "11536", "yf_ticker": "TCS.NS",       "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "HDFCBANK",  "token": "1333",  "yf_ticker": "HDFCBANK.NS",  "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "ICICIBANK", "token": "4963",  "yf_ticker": "ICICIBANK.NS", "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "INFY",      "token": "1594",  "yf_ticker": "INFY.NS",      "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "LT",        "token": "11483", "yf_ticker": "LT.NS",        "interval": "60", "category": "india_large"},
    {"source": "angelone_fallback", "symbol": "WIPRO",     "token": "3787",  "yf_ticker": "WIPRO.NS",     "interval": "60", "category": "india_large"},

    # India Mid Cap
    {"source": "angelone_fallback", "symbol": "TATAMOTORS", "token": "3456",  "yf_ticker": "TATAMOTORS.NS",  "interval": "60", "category": "india_mid"},
    {"source": "angelone_fallback", "symbol": "ZOMATO",     "token": "5097",  "yf_ticker": "ZOMATO.NS",      "interval": "60", "category": "india_mid"},
    {"source": "angelone_fallback", "symbol": "ADANIPORTS", "token": "15083", "yf_ticker": "ADANIPORTS.NS",  "interval": "60", "category": "india_mid"},
    {"source": "angelone_fallback", "symbol": "BAJFINANCE", "token": "317",   "yf_ticker": "BAJFINANCE.NS",  "interval": "60", "category": "india_mid"},
    {"source": "angelone_fallback", "symbol": "HAVELLS",    "token": "9819",  "yf_ticker": "HAVELLS.NS",     "interval": "60", "category": "india_mid"},

    # India Small Cap
    {"source": "angelone_fallback", "symbol": "IRFC",      "token": "2029",  "yf_ticker": "IRFC.NS",     "interval": "60", "category": "india_small"},
    {"source": "angelone_fallback", "symbol": "NMDC",      "token": "15332", "yf_ticker": "NMDC.NS",     "interval": "60", "category": "india_small"},
    {"source": "angelone_fallback", "symbol": "ASHOKLEY",  "token": "212",   "yf_ticker": "ASHOKLEY.NS", "interval": "60", "category": "india_small"},

    # US Stocks
    {"source": "yfinance", "symbol": "NVDA", "interval": "1h", "category": "us_large"},
    {"source": "yfinance", "symbol": "AAPL", "interval": "1h", "category": "us_large"},
]

HOLD_RULES = {
    "india_large": {"min_hold_hours": 4,  "profit_pct": 3.0, "early_override_pct": 12.0, "trail_pct": 1.5, "stop_pct": 3.0, "signals_needed": 3},
    "india_mid":   {"min_hold_hours": 2,  "profit_pct": 5.0, "early_override_pct": 10.0, "trail_pct": 2.5, "stop_pct": 4.0, "signals_needed": 3},
    "india_small": {"min_hold_hours": 3,  "profit_pct": 8.0, "early_override_pct": 15.0, "trail_pct": 4.0, "stop_pct": 4.0, "signals_needed": 4},
    "crypto_large":{"min_hold_hours": 2,  "profit_pct": 4.0, "early_override_pct": 8.0,  "trail_pct": 2.0, "stop_pct": 3.0, "signals_needed": 3},
    "crypto_mid":  {"min_hold_hours": 2,  "profit_pct": 5.0, "early_override_pct": 15.0, "trail_pct": 2.0, "stop_pct": 5.0, "signals_needed": 3},
    "us_large":    {"min_hold_hours": 24, "profit_pct": 5.0, "early_override_pct": 10.0, "trail_pct": 2.5, "stop_pct": 3.0, "signals_needed": 2},
}

TIMEFRAME_CONFIG = {
    "15m": {"binance_interval": "15m", "yf_interval": "15m", "yf_period": "60d",  "binance_days": 30, "fyers_interval": "15",  "fyers_days": 30},
    "1h":  {"binance_interval": "1h",  "yf_interval": "1h",  "yf_period": "60d",  "binance_days": 60, "fyers_interval": "60",  "fyers_days": 60},
    "4h":  {"binance_interval": "4h",  "yf_interval": "60m", "yf_period": "60d",  "binance_days": 90, "fyers_interval": "240", "fyers_days": 90},
    "1d":  {"binance_interval": "1d",  "yf_interval": "1d",  "yf_period": "2y",   "binance_days": 500, "fyers_interval": "D",   "fyers_days": 500},
}

def _load_df(source: str, symbol: str = None, token: str = None, ticker: str = None, interval: str = "1h") -> pd.DataFrame:
    from kronos.data.fetcher import fetch_binance, fetch_yfinance, fetch_indian_stock, fetch_angel_one
    cfg = TIMEFRAME_CONFIG.get(interval, TIMEFRAME_CONFIG["1h"])
    if source == "binance": return fetch_binance(symbol, cfg["binance_interval"], cfg["binance_days"])
    elif source == "angelone": return fetch_angel_one(token or symbol, "NSE", cfg["fyers_interval"], cfg["fyers_days"])
    elif source == "angelone_fallback": 
        df, src = fetch_indian_stock(token or symbol, ticker, cfg["fyers_interval"], cfg["fyers_days"])
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

def _is_market_open(category: str) -> bool:
    if category.startswith("crypto"):
        return True
    now_utc = datetime.now(pytz.utc)
    if category.startswith("india"):
        ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
        if ist.weekday() >= 5: return False
        market_open = ist.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= ist <= market_close
    if category.startswith("us"):
        est = now_utc.astimezone(pytz.timezone('America/New_York'))
        if est.weekday() >= 5: return False
        market_open = est.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = est.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= est <= market_close
    return True

async def _fetch_and_batch_predict(assets, predictor, loop, executor):
    open_assets = []
    for a in assets:
        if _is_market_open(a.get("category", "crypto")):
            open_assets.append(a)
        else:
            print(f"[Daemon] 💤 Skipping {a['symbol']}: Market is closed.")
            
    if not open_assets: return []

    async def fetch_one(asset):
        await asyncio.sleep(random.uniform(0.1, 0.5))
        try:
            source = asset["source"]
            symbol = asset["symbol"]
            token = asset.get("token", symbol)
            ticker = asset.get("yf_ticker", symbol)
            interval = asset["interval"]
            df = await loop.run_in_executor(executor, _load_df, source, symbol, token, ticker, interval)
            return asset, df
        except Exception as e:
            print(f"[Daemon] Error fetching {asset['symbol']}: {e}")
            return asset, None
            
    print(f"[Daemon] 📡 Fetching {len(open_assets)} assets asynchronously...")
    tasks = [fetch_one(a) for a in open_assets]
    results = await asyncio.gather(*tasks)
    
    valid_assets = []
    df_list = []
    x_ts_list = []
    y_ts_list = []
    ctx = predictor.max_context if hasattr(predictor, "max_context") else 512
    lookback = 200
    
    for asset, df in results:
        if df is None or len(df) < lookback + 35:
            continue
            
        df.drop_duplicates(subset=["timestamps"], keep="last", inplace=True)
        x_df = df.iloc[-lookback:][["open", "high", "low", "close"] + (["volume"] if "volume" in df.columns else [])].copy()
        x_ts = df.iloc[-lookback:]["timestamps"].reset_index(drop=True)
        time_diff = x_ts.iloc[-1] - x_ts.iloc[-2] if len(x_ts) >= 2 else pd.Timedelta(hours=1)
        y_ts = pd.Series(pd.date_range(start=x_ts.iloc[-1] + time_diff, periods=30, freq=time_diff))
        
        valid_assets.append((asset, df))
        df_list.append(x_df)
        x_ts_list.append(x_ts)
        y_ts_list.append(y_ts)
        
    if not valid_assets: return []
    
    print(f"[Daemon] 🚀 Batch Predicting {len(valid_assets)} assets using Matrix Inference...")
    try:
        preds = predictor.predict_batch(df_list, x_ts_list, y_ts_list, pred_len=30, T=0.8, top_p=0.9, sample_count=1, verbose=False)
    except Exception as e:
        print(f"[Daemon Evaluator Error] Batch predict failed: {e}")
        return []
        
    final_results = []
    for (asset, df), pred_df in zip(valid_assets, preds):
        sig_info = _generate_signal(df.iloc[-lookback:], pred_df, ctx)
        final_results.append((asset, sig_info["signal"], sig_info["confidence"], float(df.iloc[-1]["close"]), df))
        
    return final_results

def _get_usd_inr_rate() -> float:
    rate_str = get_setting("usdinr_rate")
    last_update_str = get_setting("usdinr_last_update")
    
    now = datetime.now()
    if rate_str and last_update_str:
        try:
            last_update = datetime.fromisoformat(last_update_str)
            if (now - last_update).total_seconds() < 86400: # 24 hours cache
                return float(rate_str)
        except:
            pass
            
    # Fetch from yfinance
    try:
        import yfinance as yf
        # Use single string standard call to avoid DataFrame errors
        df = yf.download("USDINR=X", period="1d", interval="1d", progress=False)
        if not df.empty:
            # Handle MultiIndex column returned by modern yfinance
            if isinstance(df.columns, pd.MultiIndex):
                rate = float(df['Close'].iloc[-1].iloc[0])
            else:
                rate = float(df['Close'].iloc[-1])
            set_setting("usdinr_rate", str(rate))
            set_setting("usdinr_last_update", now.isoformat())
            print(f"[Daemon] Cached new USD/INR exchange rate: {rate:.2f}")
            return rate
    except Exception as e:
        print(f"[Daemon] Warning: Failed to fetch live USD/INR rate: {e}")
        
    return float(rate_str) if rate_str else 83.5

async def _evaluate_trades_async(analyzer, skills_engine, drive_state, predictor, loop, executor):
    open_pos = get_open_positions()
    open_symbols = {p["symbol"]: p for p in open_pos}
    
    cat_counts = {}
    for p in open_pos:
        cat = p.get("category", "crypto_mid")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        
    usd_inr_rate = await loop.run_in_executor(executor, _get_usd_inr_rate)
    
    batch_results = await _fetch_and_batch_predict(AUTO_TRADE_POOL, predictor, loop, executor)
    
    for asset, signal, confidence, last_price_raw, df in batch_results:
        symbol = asset["symbol"]
        category = asset["category"]
        
        try:
            # Currency Normalization: Convert USD assets to INR for unified portfolio math
            is_usd = category.startswith("crypto_") or category.startswith("us_")
            last_price = last_price_raw * usd_inr_rate if is_usd else last_price_raw
                
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
                        
                # 4. Emergency Confidence Override (Gap-downs)
                elif signal == "SELL" and confidence >= 0.95 and pnl_pct <= -1.5:
                    should_sell = True
                    reason = f"CONFIDENCE OVERRIDE (Confidence: {confidence}, PnL: {pnl_pct:.1f}%)"
                
                # 5. Zone 1 / Standard exit (Min hold + Signals)
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

async def daemon_loop(predictor, loop, executor):
    print("[Daemon] Virtual Broker daemon started (Async-Batch Mode).")
    analyzer = StrategyAnalyzer()
    skills_engine = SkillsEngine()
    research_node = ResearchNode()
    
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
                
                port = get_portfolio()
                tracker = ObjectiveTracker(start_of_week, start_of_month, port["total_equity"])
                drive_state = tracker.evaluate()
                
                print(f"[Daemon] State: {drive_state['state']} | Reason: {drive_state['reason']}")
                
                if drive_state["state"] == "RESEARCH_MODE":
                    shift_plan = research_node.execute_deep_research()
                    drive_state["position_multiplier"] = shift_plan.get("greedy_recovery_multiplier", 1.5)
                    start_of_week = port["total_equity"]
                    start_of_month = port["total_equity"]
                    epoch_start_time = datetime.now()
                    set_setting("epoch_start_time", epoch_start_time.isoformat())
                    set_setting("epoch_week_start_equity", str(start_of_week))
                    set_setting("epoch_month_start_equity", str(start_of_month))
                    print("[Daemon] Strategy Shift Applied. Resetting Epoch base balances.")

                await _evaluate_trades_async(analyzer, skills_engine, drive_state, predictor, loop, executor)
            await asyncio.sleep(60)
        except Exception as e:
            print(f"[Daemon] Error in loop: {e}")
            await asyncio.sleep(60)

def start_daemon(predictor):
    def run_async():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        executor = ThreadPoolExecutor(max_workers=10)
        loop.run_until_complete(daemon_loop(predictor, loop, executor))
        
    t = threading.Thread(target=run_async, daemon=True)
    t.start()

if __name__ == "__main__":
    from kronos.model.kronos import Kronos, KronosTokenizer, KronosPredictor
    from kronos.data.repository import init_db
    
    print("[Daemon] Initializing Database...")
    init_db()

    print("[Daemon] Loading Kronos AI Model (kronos-mini) for automated trading...")
    try:
        _tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
        _model = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
        
        import torch
        _model = torch.quantization.quantize_dynamic(
            _model, {torch.nn.Linear}, dtype=torch.qint8
        )
        print("[Daemon] Applied PyTorch INT8 Dynamic Quantization. (RAM footprint reduced by 75%)")
        
        _predictor = KronosPredictor(_model, _tokenizer, device="cpu", max_context=2048)
        print("[Daemon] AI Model Loaded Successfully!")
    except Exception as e:
        print(f"[Daemon] WARNING: AI Model load failed: {e}. Falling back to sleep.")
        _predictor = None

    if _predictor is not None:
        print("[Daemon] Handing over to main trading loop...")
        start_daemon(_predictor)
        while True: time.sleep(60)
    else:
        print("[Daemon] Idle mode. AI model not found.")
        while True:
            time.sleep(60)
