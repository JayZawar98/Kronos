"""
Kronos Data Fetcher
====================
Fetches OHLCV candlestick data from:
  - Binance REST API  (crypto, completely free, no API key needed)
  - Yahoo Finance     (NSE/BSE Indian stocks, global equities, indices)

Saves data as CSV files into the ./data/ directory in the format
Kronos expects: columns [timestamps, open, high, low, close, volume]
"""

import os
import sys

# --- Code-level IDE resolution for missing modules ---
venv_site_packages = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'lib', 'python3.12', 'site-packages')
if venv_site_packages not in sys.path:
    sys.path.insert(0, venv_site_packages)

import time
import requests
import pandas as pd
from typing import Tuple
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Binance  (crypto, no API key)
# ---------------------------------------------------------------------------

BINANCE_BASE = "https://api.binance.com/api/v3/klines"

BINANCE_INTERVAL_MAP = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "1h",
    "4h":  "4h",
    "1d":  "1d",
    "1w":  "1w",
}


def _binance_fetch_chunk(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch up to 1 000 candles from Binance for one chunk."""
    params = {
        "symbol": symbol.upper(),
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1000,
    }
    resp = requests.get(BINANCE_BASE, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_binance(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    days: int = 60,
) -> pd.DataFrame:
    """
    Download up to `days` days of candlestick data from Binance.

    Args:
        symbol:   Binance trading pair, e.g. 'BTCUSDT', 'ETHUSDT', 'BNBUSDT'
        interval: Candle interval — '1m','5m','15m','30m','1h','4h','1d','1w'
        days:     How many calendar days of history to download

    Returns:
        DataFrame with columns: timestamps, open, high, low, close, volume
    """
    if interval not in BINANCE_INTERVAL_MAP:
        raise ValueError(f"Unsupported interval: {interval}. Choose from {list(BINANCE_INTERVAL_MAP)}")

    end_ms   = int(datetime.utcnow().timestamp() * 1000)
    start_ms = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)

    print(f"[Binance] Fetching {symbol} {interval} for last {days} days …")
    all_rows = []
    chunk_start = start_ms

    while chunk_start < end_ms:
        rows = _binance_fetch_chunk(symbol, interval, chunk_start, end_ms)
        if not rows:
            break
        all_rows.extend(rows)
        chunk_start = rows[-1][6] + 1   # close_time + 1 ms
        if len(rows) < 1000:
            break
        time.sleep(0.05)

    if not all_rows:
        raise RuntimeError(f"No data returned for {symbol}/{interval}")

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ])

    df["timestamps"] = pd.to_datetime(df["open_time"], unit="ms")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df = df[["timestamps", "open", "high", "low", "close", "volume"]].copy()
    df.sort_values("timestamps", inplace=True)
    df.reset_index(drop=True, inplace=True)

    fname = f"BINANCE_{symbol}_{interval}_{days}d.csv"
    fpath = os.path.join(DATA_DIR, fname)
    df.to_csv(fpath, index=False)
    print(f"[Binance] Saved {len(df)} rows → {fpath}")
    return df


# ---------------------------------------------------------------------------
# Yahoo Finance  (NSE / BSE / global stocks)
# ---------------------------------------------------------------------------

def fetch_yfinance(
    ticker: str = "RELIANCE.NS",
    interval: str = "1h",
    period: str = "60d",
) -> pd.DataFrame:
    """
    Download candlestick data from Yahoo Finance.

    Args:
        ticker:   Yahoo Finance ticker, e.g.:
                    NSE stocks → 'RELIANCE.NS', 'TCS.NS', 'INFY.NS'
                    BSE stocks → 'RELIANCE.BO', 'TCS.BO'
                    Crypto     → 'BTC-USD', 'ETH-USD'
                    US stocks  → 'AAPL', 'TSLA', 'NVDA'
        interval: '1m','2m','5m','15m','30m','60m','90m','1h','1d','5d','1wk','1mo'
        period:   '1d','5d','1mo','3mo','6mo','1y','2y','5y','10y','ytd','max'
                  For intraday (< 1d), max period is '60d'

    Returns:
        DataFrame with columns: timestamps, open, high, low, close, volume
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance is not installed. Run: pip install yfinance")

    print(f"[yfinance] Fetching {ticker} {interval} for period={period} …")
    tkr = yf.Ticker(ticker)
    df = tkr.history(interval=interval, period=period)

    if df.empty:
        raise RuntimeError(f"No data returned for {ticker}. Check the ticker symbol.")

    df.reset_index(inplace=True)

    # Yahoo returns 'Datetime' for intraday, 'Date' for daily
    time_col = "Datetime" if "Datetime" in df.columns else "Date"
    df.rename(columns={
        time_col: "timestamps",
        "Open":   "open",
        "High":   "high",
        "Low":    "low",
        "Close":  "close",
        "Volume": "volume",
    }, inplace=True)

    df["timestamps"] = pd.to_datetime(df["timestamps"])
    # Strip timezone for Kronos compatibility
    if df["timestamps"].dt.tz is not None:
        df["timestamps"] = df["timestamps"].dt.tz_localize(None)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[["timestamps", "open", "high", "low", "close", "volume"]].dropna()
    df.sort_values("timestamps", inplace=True)
    df.reset_index(drop=True, inplace=True)

    safe_ticker = ticker.replace(".", "_").replace("-", "_")
    fname = f"YF_{safe_ticker}_{interval}_{period}.csv"
    fpath = os.path.join(DATA_DIR, fname)
    df.to_csv(fpath, index=False)
    print(f"[yfinance] Saved {len(df)} rows → {fpath}")
    return df


# ---------------------------------------------------------------------------
# FYERS API (True Real-Time NSE/BSE)
# ---------------------------------------------------------------------------

def fetch_fyers(
    symbol: str = "NSE:RELIANCE-EQ",
    interval: str = "60",
    days: int = 60,
) -> pd.DataFrame:
    """
    Download candlestick data from FYERS.
    Requires FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in .env.
    """
    try:
        from fyers_apiv3 import fyersModel
    except ImportError:
        raise ImportError("fyers-apiv3 is not installed. Run: pip install fyers-apiv3")

    load_dotenv(override=True)
    client_id = os.getenv("FYERS_CLIENT_ID")
    access_token = os.getenv("FYERS_ACCESS_TOKEN")

    if not client_id or not access_token or "your_" in client_id:
        raise ValueError("Please enter your actual FYERS_CLIENT_ID and FYERS_ACCESS_TOKEN in the .env file.")

    print(f"[FYERS] Fetching {symbol} {interval} for last {days} days …")
    
    fyers = fyersModel.FyersModel(client_id=client_id, is_async=False, token=access_token, log_path="")

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = {
        "symbol": symbol,
        "resolution": interval,
        "date_format": "1",
        "range_from": start_date,
        "range_to": end_date,
        "cont_flag": "1"
    }

    response = fyers.history(data=data)
    if response.get("s") != "ok":
        raise RuntimeError(f"FYERS API error: {response}")

    candles = response.get("candles", [])
    if not candles:
        raise RuntimeError(f"No data returned for {symbol}. Check the ticker symbol.")

    df = pd.DataFrame(candles, columns=["timestamps", "open", "high", "low", "close", "volume"])
    
    # FYERS returns epoch timestamp in seconds
    df["timestamps"] = pd.to_datetime(df["timestamps"], unit="s")
    
    # Strip timezone
    if df["timestamps"].dt.tz is not None:
        df["timestamps"] = df["timestamps"].dt.tz_localize(None)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[["timestamps", "open", "high", "low", "close", "volume"]].dropna()
    df.drop_duplicates(subset=["timestamps"], keep="last", inplace=True)
    df.sort_values("timestamps", inplace=True)
    df.reset_index(drop=True, inplace=True)

    safe_ticker = symbol.replace(":", "_").replace("-", "_")
    fname = f"FYERS_{safe_ticker}_{interval}_{days}d.csv"
    fpath = os.path.join(DATA_DIR, fname)
    df.to_csv(fpath, index=False)
    print(f"[FYERS] Saved {len(df)} rows → {fpath}")
    return df


# ---------------------------------------------------------------------------
# Fallback Fetcher (Fyers -> YFinance)
# ---------------------------------------------------------------------------

def fetch_indian_stock(fyers_symbol: str, yf_ticker: str, interval: str, days: int) -> Tuple[pd.DataFrame, str]:
    """Try Fyers first (real-time), fall back to Yahoo Finance (15-min delayed)."""
    try:
        df = fetch_fyers(fyers_symbol, interval, days)
        print(f"[Data] ✅ Fyers success: {fyers_symbol}")
        return df, "fyers"
    except Exception as e:
        print(f"[Data] ⚠️ Fyers failed ({e}). Falling back to Yahoo Finance for {yf_ticker}.")
        try:
            # yf_interval mapping: '60' (fyers 60m) -> '1h' (yfinance)
            yf_int = "1h" if interval == "60" else interval
            # Yahoo finance requires period like "60d"
            df = fetch_yfinance(yf_ticker, yf_int, f"{days}d")
            print(f"[Data] ✅ Yahoo Finance fallback success: {yf_ticker}")
            return df, "yfinance"
        except Exception as e2:
            raise RuntimeError(f"Both Fyers and Yahoo Finance failed. YF error: {e2}")

# ---------------------------------------------------------------------------
# Convenience: fetch a preset basket of assets
# ---------------------------------------------------------------------------

PRESET_ASSETS = [
    # Crypto via Binance
    dict(source="binance", symbol="BTCUSDT",  interval="1h",  days=90),
    dict(source="binance", symbol="ETHUSDT",  interval="1h",  days=90),
    dict(source="binance", symbol="BNBUSDT",  interval="1h",  days=90),
    # Indian stocks via yfinance
    dict(source="yfinance", ticker="RELIANCE.NS", interval="1d", period="2y"),
    dict(source="yfinance", ticker="TCS.NS",      interval="1d", period="2y"),
    dict(source="yfinance", ticker="INFY.NS",     interval="1d", period="2y"),
    dict(source="yfinance", ticker="NIFTY50.NS",  interval="1d", period="2y"),
]


def fetch_all_presets():
    """Download all preset assets and save CSVs to ./data/"""
    results = {}
    for asset in PRESET_ASSETS:
        try:
            if asset["source"] == "binance":
                df = fetch_binance(asset["symbol"], asset["interval"], asset["days"])
                key = f"BINANCE_{asset['symbol']}_{asset['interval']}"
            elif asset["source"] == "fyers":
                df = fetch_fyers(asset["symbol"], asset["interval"], asset["days"])
                key = f"FYERS_{asset['symbol']}_{asset['interval']}"
            else:
                df = fetch_yfinance(asset["ticker"], asset["interval"], asset["period"])
                key = f"YF_{asset['ticker']}"
            results[key] = {"rows": len(df), "status": "ok"}
        except Exception as e:
            key = asset.get("symbol") or asset.get("ticker")
            results[key] = {"rows": 0, "status": f"ERROR: {e}"}
            print(f"  ⚠  Failed: {e}")
    return results


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Kronos Data Fetcher")
    sub = parser.add_subparsers(dest="cmd")

    # binance sub-command
    p_b = sub.add_parser("binance", help="Fetch from Binance")
    p_b.add_argument("--symbol",   default="BTCUSDT")
    p_b.add_argument("--interval", default="1h")
    p_b.add_argument("--days",     type=int, default=90)

    # yfinance sub-command
    p_y = sub.add_parser("yfinance", help="Fetch from Yahoo Finance")
    p_y.add_argument("--ticker",   default="RELIANCE.NS")
    p_y.add_argument("--interval", default="1d")
    p_y.add_argument("--period",   default="2y")

    # all sub-command
    p_a = sub.add_parser("all", help="Fetch all preset assets")

    args = parser.parse_args()

    if args.cmd == "binance":
        fetch_binance(args.symbol, args.interval, args.days)
    elif args.cmd == "yfinance":
        fetch_yfinance(args.ticker, args.interval, args.period)
    elif args.cmd == "all":
        r = fetch_all_presets()
        print("\n=== Fetch Summary ===")
        for k, v in r.items():
            print(f"  {k}: {v['rows']} rows — {v['status']}")
    else:
        parser.print_help()
