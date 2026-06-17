import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from data_fetcher import fetch_binance, fetch_yfinance, fetch_indian_stock
from skills_engine import SkillsEngine
import pandas_ta as ta

class Backtester:
    def __init__(self, use_llm=False):
        self.skills_engine = SkillsEngine()
        self.use_llm = use_llm
        self.predictor = None
        
        if self.use_llm:
            try:
                from kronos import Kronos, KronosPredictor, KronosTokenizer
                print("[Backtester] Loading Kronos-Mini LLM (This will be slow during backtest)...")
                tokenizer = KronosTokenizer.from_pretrained("amazon/kronos-tokenizer")
                model = Kronos.from_pretrained("amazon/kronos-mini")
                self.predictor = KronosPredictor(model, tokenizer, device="cpu", max_context=512)
            except Exception as e:
                print(f"[Backtester] Failed to load LLM: {e}")
                self.use_llm = False

    def fetch_data(self, source, symbol, ticker=None, days=30):
        print(f"[Backtester] Fetching {days} days of data for {symbol}...")
        if source == "binance":
            df = fetch_binance(symbol, interval="1h", days=days)
        elif source == "yfinance":
            df = fetch_yfinance(symbol, interval="1h", days=days)
        elif source == "fyers_fallback":
            df, _ = fetch_indian_stock(symbol, ticker, interval="60", days=days)
        else:
            raise ValueError("Unknown source")
            
        df.drop_duplicates(subset=["timestamps"], keep="last", inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    def _mock_signal_generator(self, df):
        """Fast SMA-crossover proxy if not using LLM"""
        df_ta = df.copy()
        df_ta.ta.sma(length=10, append=True)
        df_ta.ta.sma(length=50, append=True)
        
        last = df_ta.iloc[-1]
        prev = df_ta.iloc[-2]
        
        sma10_last = last.get("SMA_10")
        sma50_last = last.get("SMA_50")
        sma10_prev = prev.get("SMA_10")
        sma50_prev = prev.get("SMA_50")
        
        if pd.isna(sma10_last) or pd.isna(sma50_last):
            return "HOLD", 0.0, last["close"]
            
        # Golden cross
        if sma10_last > sma50_last and sma10_prev <= sma50_prev:
            return "BUY", 0.85, last["close"]
        # Death cross
        elif sma10_last < sma50_last and sma10_prev >= sma50_prev:
            return "SELL", 0.85, last["close"]
            
        return "HOLD", 0.0, last["close"]

    def run(self, source, symbol, ticker, category, initial_capital=10000):
        df = self.fetch_data(source, symbol, ticker, days=30)
        
        print(f"\n[Backtester] Starting simulation on {len(df)} candles...")
        print(f"Asset: {symbol} | Category: {category} | LLM Mode: {self.use_llm}\n")
        
        capital = initial_capital
        position = 0
        entry_price = 0
        peak_price = 0
        trades = []
        
        # We need a minimum lookback to start generating signals
        lookback = 100
        
        # Hardcoded HOLD_RULES
        rules = {
            "india_large": {"min_hold_hours": 4,  "profit_pct": 3.0, "early_override_pct": 6.0,  "trail_pct": 1.5, "stop_pct": 2.0, "signals_needed": 3},
            "us_large":    {"min_hold_hours": 24, "profit_pct": 5.0, "early_override_pct": 10.0, "trail_pct": 2.5, "stop_pct": 3.0, "signals_needed": 2},
            "crypto_mid":  {"min_hold_hours": 2,  "profit_pct": 5.0, "early_override_pct": 8.0,  "trail_pct": 2.0, "stop_pct": 3.5, "signals_needed": 3},
        }
        r = rules.get(category, rules["crypto_mid"])
        
        asset = {"symbol": symbol, "category": category, "yf_ticker": ticker}
        
        for i in range(lookback, len(df)):
            window = df.iloc[:i]
            last_price = window.iloc[-1]["close"]
            timestamp = window.iloc[-1]["timestamps"]
            
            # 1. Generate Signal
            if self.use_llm and self.predictor:
                # LLM execution would go here, omitting for speed/safety unless fully required
                pass
            
            signal, conf, _ = self._mock_signal_generator(window)
            
            # 2. Open Position Logic
            if position == 0 and signal == "BUY":
                # Master Orchestrator Validation
                is_allowed, reason = self.skills_engine.evaluate_trade(asset, signal, window, [])
                
                if is_allowed:
                    # Execute 2% Risk Trade
                    trade_amount = capital * 0.02
                    position = trade_amount / last_price
                    capital -= trade_amount
                    entry_price = last_price
                    peak_price = last_price
                    self.skills_engine.increment_trade_counter()
                    
                    trades.append({"type": "BUY", "price": last_price, "time": timestamp, "reason": "Signal + Orchestrator"})
            
            # 3. Close Position Logic
            elif position > 0:
                pnl_pct = ((last_price - entry_price) / entry_price) * 100.0
                if last_price > peak_price:
                    peak_price = last_price
                    
                should_sell = False
                sell_reason = ""
                
                if pnl_pct <= -r["stop_pct"]:
                    should_sell, sell_reason = True, "Stop Loss"
                elif pnl_pct >= r["early_override_pct"]:
                    should_sell, sell_reason = True, "Early Override"
                elif pnl_pct >= r["profit_pct"]:
                    trail_floor = peak_price * (1 - (r["trail_pct"] / 100.0))
                    if last_price <= trail_floor:
                        should_sell, sell_reason = True, "Trailing Stop"
                elif signal == "SELL":
                    should_sell, sell_reason = True, "Sell Signal"
                    
                if should_sell:
                    capital += position * last_price
                    trades.append({"type": "SELL", "price": last_price, "time": timestamp, "reason": sell_reason, "pnl": pnl_pct})
                    position = 0

        # Close any open positions at the end
        if position > 0:
            capital += position * df.iloc[-1]["close"]
            pnl_pct = ((df.iloc[-1]["close"] - entry_price) / entry_price) * 100.0
            trades.append({"type": "SELL", "price": df.iloc[-1]["close"], "time": df.iloc[-1]["timestamps"], "reason": "End of Backtest", "pnl": pnl_pct})
            
        self._print_report(initial_capital, capital, trades)

    def _print_report(self, init_cap, final_cap, trades):
        print("\n" + "="*50)
        print("📊 BACKTEST REPORT")
        print("="*50)
        print(f"Initial Capital: ${init_cap:,.2f}")
        print(f"Final Capital:   ${final_cap:,.2f}")
        print(f"Net Profit:      ${(final_cap - init_cap):,.2f} ({((final_cap - init_cap)/init_cap)*100:.2f}%)")
        
        sell_trades = [t for t in trades if t["type"] == "SELL"]
        if not sell_trades:
            print("No trades completed.")
            return
            
        wins = [t for t in sell_trades if t["pnl"] > 0]
        losses = [t for t in sell_trades if t["pnl"] <= 0]
        
        print(f"Total Trades:    {len(sell_trades)}")
        print(f"Win Rate:        {len(wins)/len(sell_trades)*100:.1f}%")
        if wins:
            print(f"Avg Win:         +{sum(t['pnl'] for t in wins)/len(wins):.2f}%")
        if losses:
            print(f"Avg Loss:        {sum(t['pnl'] for t in losses)/len(losses):.2f}%")
        print("="*50 + "\n")

if __name__ == "__main__":
    bt = Backtester(use_llm=False)
    
    # Test Crypto
    bt.run("binance", "BTCUSDT", "BTC-USD", "crypto_large")
    
    # Test Indian Equity
    bt.run("fyers_fallback", "NSE:RELIANCE-EQ", "RELIANCE.NS", "india_large")
