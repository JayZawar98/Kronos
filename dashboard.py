"""
Kronos Live Dashboard
======================
An enhanced Flask web app that wraps the Kronos webui/app.py with:
  • Live data fetching from Binance & Yahoo Finance
  • BUY / SELL / HOLD signal generation
  • Multi-asset & multi-timeframe analysis
  • Clean REST API for the frontend

Run:
    cd /path/to/Kronos
    .venv/bin/python dashboard.py
    → http://localhost:7071
"""

import os
import sys

# --- Code-level IDE resolution for missing modules ---
venv_site_packages = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.venv', 'lib', 'python3.12', 'site-packages')
if venv_site_packages not in sys.path:
    sys.path.insert(0, venv_site_packages)

import json
import warnings
import datetime
import traceback
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.utils
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Kronos model imports ─────────────────────────────────────────────────────
try:
    from model import Kronos, KronosTokenizer, KronosPredictor
    MODEL_AVAILABLE = True
except ImportError:
    MODEL_AVAILABLE = False
    print("⚠  Kronos model not importable (missing deps?). Some features disabled.")

# ── Data fetcher ──────────────────────────────────────────────────────────────
from data_fetcher import fetch_binance, fetch_yfinance, fetch_fyers, fetch_indian_stock, DATA_DIR

# ── Virtual Broker ────────────────────────────────────────────────────────────
from database import get_portfolio, get_open_positions, get_trade_history, get_setting, set_setting, init_db
from trader_daemon import start_daemon

app = Flask(__name__, template_folder="webui/templates", static_folder="webui/static")
app.jinja_env.auto_reload = True
app.config["TEMPLATES_AUTO_RELOAD"] = True
CORS(app)

# ── Globals ───────────────────────────────────────────────────────────────────
_tokenizer = None
_model     = None
_predictor = None

MODELS = {
    "kronos-mini": {
        "name": "Kronos-mini",
        "model_id": "NeoQuasar/Kronos-mini",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "context_length": 2048,
        "params": "4.1M",
        "desc": "Fastest · CPU-friendly · 2048-token context",
    },
    "kronos-small": {
        "name": "Kronos-small",
        "model_id": "NeoQuasar/Kronos-small",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "context_length": 512,
        "params": "24.7M",
        "desc": "Balanced speed/quality · 512-token context",
    },
    "kronos-base": {
        "name": "Kronos-base",
        "model_id": "NeoQuasar/Kronos-base",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "context_length": 512,
        "params": "102.3M",
        "desc": "Best quality · 512-token context",
    },
}

PRESET_SYMBOLS = {
    "Crypto (Binance)": [
        {"label": "BTC/USDT",  "source": "binance", "symbol": "BTCUSDT"},
        {"label": "ETH/USDT",  "source": "binance", "symbol": "ETHUSDT"},
        {"label": "BNB/USDT",  "source": "binance", "symbol": "BNBUSDT"},
        {"label": "SOL/USDT",  "source": "binance", "symbol": "SOLUSDT"},
        {"label": "XRP/USDT",  "source": "binance", "symbol": "XRPUSDT"},
    ],
    "Indian Stocks (NSE)": [
        {"label": "Reliance",  "source": "yfinance", "ticker": "RELIANCE.NS"},
        {"label": "TCS",       "source": "yfinance", "ticker": "TCS.NS"},
        {"label": "Infosys",   "source": "yfinance", "ticker": "INFY.NS"},
        {"label": "HDFC Bank", "source": "yfinance", "ticker": "HDFCBANK.NS"},
        {"label": "Wipro",     "source": "yfinance", "ticker": "WIPRO.NS"},
        {"label": "Nifty 50",  "source": "yfinance", "ticker": "^NSEI"},
    ],
    "Indian Stocks (FYERS)": [
        {"label": "Reliance (FYERS)",  "source": "fyers", "symbol": "NSE:RELIANCE-EQ"},
        {"label": "TCS (FYERS)",       "source": "fyers", "symbol": "NSE:TCS-EQ"},
        {"label": "Infosys (FYERS)",   "source": "fyers", "symbol": "NSE:INFY-EQ"},
        {"label": "HDFC Bank (FYERS)", "source": "fyers", "symbol": "NSE:HDFCBANK-EQ"},
        {"label": "Nifty 50 (FYERS)",  "source": "fyers", "symbol": "NSE:NIFTY50-INDEX"},
        {"label": "Bank Nifty (FYERS)","source": "fyers", "symbol": "NSE:NIFTYBANK-INDEX"},
    ],
    "US Equities": [
        {"label": "Apple",     "source": "yfinance", "ticker": "AAPL"},
        {"label": "NVIDIA",    "source": "yfinance", "ticker": "NVDA"},
        {"label": "Tesla",     "source": "yfinance", "ticker": "TSLA"},
    ],
}

TIMEFRAME_CONFIG = {
    "15m": {"binance_interval": "15m", "yf_interval": "15m", "yf_period": "60d",  "binance_days": 30, "fyers_interval": "15",  "fyers_days": 30},
    "1h":  {"binance_interval": "1h",  "yf_interval": "1h",  "yf_period": "60d",  "binance_days": 60, "fyers_interval": "60",  "fyers_days": 60},
    "4h":  {"binance_interval": "4h",  "yf_interval": "60m", "yf_period": "60d",  "binance_days": 90, "fyers_interval": "240", "fyers_days": 90},
    "1d":  {"binance_interval": "1d",  "yf_interval": "1d",  "yf_period": "2y",   "binance_days": 500, "fyers_interval": "D",   "fyers_days": 500},
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_df(source: str, symbol: str = None, ticker: str = None,
             interval: str = "1h") -> pd.DataFrame:
    """Fetch and return a DataFrame for the requested asset/interval."""
    cfg = TIMEFRAME_CONFIG.get(interval, TIMEFRAME_CONFIG["1h"])
    if source == "binance":
        return fetch_binance(symbol, cfg["binance_interval"], cfg["binance_days"])
    elif source == "fyers":
        return fetch_fyers(symbol, cfg["fyers_interval"], cfg["fyers_days"])
    elif source == "fyers_fallback":
        df, _ = fetch_indian_stock(symbol, ticker, cfg["fyers_interval"], cfg["fyers_days"])
        return df
    else:
        return fetch_yfinance(ticker, cfg["yf_interval"], cfg["yf_period"])


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 0.0
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h[1:] - l[1:],
         np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    atr = float(np.mean(tr[-period:]))
    return atr / float(c[-1])


def _generate_signal(df: pd.DataFrame, pred_df: pd.DataFrame,
                     context_len: int = 2048) -> dict:
    """
    Derive a BUY/SELL/HOLD signal from a Kronos prediction.
    Uses ATR as a noise-adaptive threshold.
    """
    last_close     = float(df["close"].iloc[-1])
    forecast_close = float(pred_df["close"].iloc[-1])
    forecast_high  = float(pred_df["high"].max())
    forecast_low   = float(pred_df["low"].min())
    return_pct     = (forecast_close - last_close) / last_close * 100.0

    atr_pct   = _compute_atr(df) * 100.0          # as %
    threshold = max(atr_pct * 0.5, 0.10)           # at least 0.10%

    if return_pct > threshold:
        signal, color = "BUY",  "#26de81"
    elif return_pct < -threshold:
        signal, color = "SELL", "#ff4d4d"
    else:
        signal, color = "HOLD", "#f7b731"

    # Confidence: how many σ above threshold
    sigma = atr_pct / 2.0 if atr_pct > 0 else 0.5
    confidence = min(abs(return_pct) / max(threshold + sigma, 0.01), 1.0)

    return {
        "signal":           signal,
        "color":            color,
        "confidence":       round(confidence, 3),
        "confidence_pct":   f"{confidence:.0%}",
        "return_pct":       round(return_pct, 3),
        "last_close":       round(last_close, 6),
        "forecast_close":   round(forecast_close, 6),
        "forecast_high":    round(forecast_high, 6),
        "forecast_low":     round(forecast_low, 6),
        "atr_pct":          round(atr_pct, 4),
        "threshold_pct":    round(threshold, 4),
    }


def _make_chart(df: pd.DataFrame, pred_df: pd.DataFrame,
                lookback: int, pred_len: int, title: str = "") -> str:
    hist = df.iloc[-lookback:]

    time_diff = (hist["timestamps"].iloc[-1] - hist["timestamps"].iloc[-2]
                 if len(hist) >= 2 else pd.Timedelta(hours=1))
    pred_ts = pd.date_range(
        start=hist["timestamps"].iloc[-1] + time_diff,
        periods=pred_len, freq=time_diff
    )

    fig = go.Figure()

    # Historical candlesticks
    fig.add_trace(go.Candlestick(
        x=hist["timestamps"], open=hist["open"], high=hist["high"],
        low=hist["low"], close=hist["close"], name="Historical",
        increasing_line_color="#26A69A", decreasing_line_color="#EF5350",
    ))

    # Predicted candlesticks
    fig.add_trace(go.Candlestick(
        x=pred_ts, open=pred_df["open"], high=pred_df["high"],
        low=pred_df["low"], close=pred_df["close"], name="Forecast (Kronos)",
        increasing_line_color="#66BB6A", decreasing_line_color="#FF7043",
    ))

    # Forecast close line
    fig.add_trace(go.Scatter(
        x=pred_ts, y=pred_df["close"], mode="lines",
        name="Forecast Close",
        line=dict(color="#FFD700", width=2, dash="dot"),
    ))

    fig.update_layout(
        title=title or "Kronos Forecast",
        xaxis_title="Time", yaxis_title="Price",
        template="plotly_dark",
        height=550,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=-0.12),
        font=dict(family="Inter, sans-serif"),
    )
    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/models")
def api_models():
    return jsonify({"models": MODELS, "available": MODEL_AVAILABLE})


@app.route("/api/symbols")
def api_symbols():
    return jsonify(PRESET_SYMBOLS)


@app.route("/api/portfolio", methods=["GET"])
def api_portfolio():
    try:
        port = get_portfolio()
        pos = get_open_positions()
        hist = get_trade_history(limit=20)
        enabled = get_setting("daemon_enabled") == "true"
        return jsonify({"status": "ok", "portfolio": port, "positions": pos, "history": hist, "daemon_enabled": enabled})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/daemon/toggle", methods=["POST"])
def api_daemon_toggle():
    try:
        req = request.json or {}
        enabled = req.get("enabled", False)
        set_setting("daemon_enabled", "true" if enabled else "false")
        return jsonify({"status": "ok", "daemon_enabled": enabled})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/model-status")
def api_model_status():
    loaded = _predictor is not None
    return jsonify({
        "available": MODEL_AVAILABLE,
        "loaded":    loaded,
        "message":   ("Model loaded ✓" if loaded
                      else ("Model available — load it first"
                            if MODEL_AVAILABLE else "Kronos not installed")),
    })


@app.route("/api/load-model", methods=["POST"])
def api_load_model():
    global _tokenizer, _model, _predictor
    if not MODEL_AVAILABLE:
        return jsonify({"error": "Kronos model library not importable"}), 400

    data      = request.get_json() or {}
    model_key = data.get("model_key", "kronos-mini")
    device    = data.get("device", "cpu")

    if model_key not in MODELS:
        return jsonify({"error": f"Unknown model key: {model_key}"}), 400

    cfg = MODELS[model_key]
    try:
        print(f"Loading {cfg['name']} …")
        _tokenizer = KronosTokenizer.from_pretrained(cfg["tokenizer_id"])
        _model     = Kronos.from_pretrained(cfg["model_id"])
        _predictor = KronosPredictor(
            _model, _tokenizer, device=device,
            max_context=cfg["context_length"]
        )
        return jsonify({
            "success": True,
            "message": f"{cfg['name']} ({cfg['params']}) loaded on {device}",
            "model_info": cfg,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/fetch-data", methods=["POST"])
def api_fetch_data():
    """Download live OHLCV data and return metadata."""
    data     = request.get_json() or {}
    source   = data.get("source", "binance")
    symbol   = data.get("symbol")
    ticker   = data.get("ticker")
    interval = data.get("interval", "1h")

    try:
        df = _load_df(source, symbol=symbol, ticker=ticker, interval=interval)
        return jsonify({
            "success":   True,
            "rows":      len(df),
            "start":     str(df["timestamps"].iloc[0]),
            "end":       str(df["timestamps"].iloc[-1]),
            "last_close": float(df["close"].iloc[-1]),
            "message":   f"Fetched {len(df)} candles",
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/predict-live", methods=["POST"])
def api_predict_live():
    """
    Full pipeline: fetch data → run Kronos → return signal + chart.
    """
    if _predictor is None:
        return jsonify({"error": "Load a model first via /api/load-model"}), 400

    data      = request.get_json() or {}
    source    = data.get("source", "binance")
    symbol    = data.get("symbol")
    ticker    = data.get("ticker")
    interval  = data.get("interval", "1h")
    pred_len  = int(data.get("pred_len", 30))
    T         = float(data.get("temperature", 0.8))
    top_p     = float(data.get("top_p", 0.9))
    n_samples = int(data.get("sample_count", 3))

    try:
        # 1. Data
        df = _load_df(source, symbol=symbol, ticker=ticker, interval=interval)
        df.drop_duplicates(subset=["timestamps"], keep="last", inplace=True)
        ctx      = _predictor.max_context if hasattr(_predictor, "max_context") else 512
        lookback = min(int(ctx * 0.8), len(df) - pred_len - 5)
        if lookback < 10:
            return jsonify({"error": "Not enough data for the selected timeframe"}), 400

        x_df = df.iloc[-lookback:][["open", "high", "low", "close"] +
                                    (["volume"] if "volume" in df.columns else [])].copy()
        x_ts = df.iloc[-lookback:]["timestamps"].reset_index(drop=True)

        time_diff = x_ts.iloc[-1] - x_ts.iloc[-2] if len(x_ts) >= 2 else pd.Timedelta(hours=1)
        y_ts = pd.Series(pd.date_range(
            start=x_ts.iloc[-1] + time_diff, periods=pred_len, freq=time_diff
        ))

        # 2. Predict (average multiple samples)
        all_preds = []
        for _ in range(n_samples):
            p = _predictor.predict(
                df=x_df.copy(), x_timestamp=x_ts.copy(),
                y_timestamp=y_ts.copy(), pred_len=pred_len,
                T=T, top_p=top_p, sample_count=1,
            )
            all_preds.append(p)

        pred_df = all_preds[0].copy()
        for col in ["open", "high", "low", "close"]:
            pred_df[col] = np.mean([p[col].values for p in all_preds], axis=0)

        # 3. Signal
        label = symbol or ticker or "Asset"
        signal_info = _generate_signal(df.iloc[-lookback:], pred_df, ctx)

        # 4. Chart
        chart_json = _make_chart(
            df, pred_df, lookback, pred_len,
            title=f"{label} [{interval}] — Kronos Forecast  →  {signal_info['signal']}"
        )

        # 5. Table data (last 5 + forecast horizon)
        pred_rows = []
        for idx, (_, row) in enumerate(pred_df.iterrows()):
            ts = y_ts.iloc[idx] if idx < len(y_ts) else ""
            pred_rows.append({
                "timestamp": str(ts)[:19],
                "open":  round(float(row["open"]),  6),
                "high":  round(float(row["high"]),  6),
                "low":   round(float(row["low"]),   6),
                "close": round(float(row["close"]), 6),
            })

        return jsonify({
            "success":        True,
            "signal":         signal_info,
            "chart":          chart_json,
            "predictions":    pred_rows,
            "candles_used":   lookback,
            "pred_len":       pred_len,
            "label":          label,
            "interval":       interval,
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/local-files")
def api_local_files():
    """List CSV files in ./data/"""
    files = []
    if os.path.isdir(DATA_DIR):
        for f in sorted(os.listdir(DATA_DIR)):
            if f.endswith(".csv"):
                size = os.path.getsize(os.path.join(DATA_DIR, f))
                files.append({
                    "name": f,
                    "path": os.path.join(DATA_DIR, f),
                    "size": f"{size/1024:.1f} KB" if size < 1_048_576
                            else f"{size/1_048_576:.1f} MB",
                })
    return jsonify(files)


# ─────────────────────────────────────────────────────────────────────────────
def load_default_model():
    """Auto-load kronos-mini on startup if available."""
    global _tokenizer, _model, _predictor
    try:
        from model.kronos import KronosPredictor, KronosTokenizer, Kronos
        print("  Auto-loading Kronos-mini model (CPU)...")
        cfg = MODELS["kronos-mini"]
        _tokenizer = KronosTokenizer.from_pretrained(cfg["tokenizer_id"])
        _model     = Kronos.from_pretrained(cfg["model_id"])
        _predictor = KronosPredictor(
            _model, _tokenizer, device="cpu",
            max_context=cfg["context_length"]
        )
        print("  ✓ Model loaded successfully!")
    except Exception as e:
        print(f"  ⚠ Failed to auto-load model: {e}")

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
        y_ts = pd.Series(pd.date_range(start=x_ts.iloc[-1] + time_diff, periods=30, freq=time_diff))
        
        all_preds = []
        for _ in range(3):
            p = _predictor.predict(df=x_df.copy(), x_timestamp=x_ts.copy(), y_timestamp=y_ts.copy(), pred_len=30, T=0.8, top_p=0.9, sample_count=1)
            all_preds.append(p)
            
        pred_df = all_preds[0].copy()
        for col in ["open", "high", "low", "close"]:
            import numpy as np
            pred_df[col] = np.mean([p[col].values for p in all_preds], axis=0)
            
        sig_info = _generate_signal(df.iloc[-lookback:], pred_df, ctx)
        return sig_info["signal"], sig_info["confidence"], df.iloc[-1]["close"]
    except Exception as e:
        print(f"[Daemon Evaluator Error] {e}")
        return None

if __name__ == "__main__":
    init_db()
    
    print("Starting Virtual Broker background daemon...")
    start_daemon(_daemon_evaluator)
        
    print("=" * 60)
    print("  Kronos Live Dashboard")
    print(f"  Model library : {'✓ available' if MODEL_AVAILABLE else '✗ not importable'}")
    print(f"  Data directory: {DATA_DIR}")

    if MODEL_AVAILABLE:
        load_default_model()

    print("  Open → http://localhost:7071")
    print("=" * 60)
    app.run(debug=False, host="0.0.0.0", port=7071)
