"""
Kronos Signal Generator
========================
Generates BUY / SELL / HOLD signals from Kronos price forecasts.

Signal Logic
------------
• Compares the **median forecasted close** across all sampled paths
  against the **last known close** price.
• Adds an ATR-based confidence threshold to avoid noise.
• Optionally aggregates signals across multiple timeframes
  (short / medium / long) into a single composite recommendation.

Usage
-----
    from signal_generator import KronosSignalGenerator
    gen = KronosSignalGenerator(predictor, context_len=2048)
    result = gen.analyze(df, timeframes=["15m","1h","1d"])
    print(result)
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SignalResult:
    signal: str                  # "BUY" | "SELL" | "HOLD"
    confidence: float            # 0.0 – 1.0
    forecast_return_pct: float   # expected % move
    last_close: float
    forecast_close: float
    forecast_high: float
    forecast_low: float
    pred_len: int
    timeframe: str
    details: dict = field(default_factory=dict)

    def __str__(self) -> str:
        arrow = "📈" if self.signal == "BUY" else ("📉" if self.signal == "SELL" else "➡️")
        return (
            f"{arrow} [{self.timeframe}] {self.signal}  "
            f"conf={self.confidence:.0%}  "
            f"Δ={self.forecast_return_pct:+.2f}%  "
            f"last={self.last_close:.4f}  "
            f"target={self.forecast_close:.4f}"
        )


@dataclass
class CompositeSignal:
    signal: str           # majority-vote across timeframes
    confidence: float
    timeframe_signals: List[SignalResult]
    summary: str

    def __str__(self) -> str:
        lines = [f"=== Composite Signal: {self.signal}  (conf={self.confidence:.0%}) ==="]
        for s in self.timeframe_signals:
            lines.append(f"  {s}")
        lines.append(f"\n{self.summary}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Average True Range as % of close — used as noise filter."""
    if len(df) < period + 1:
        return 0.0
    high  = df["high"].values
    low   = df["low"].values
    close = df["close"].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr = np.mean(tr[-period:])
    return float(atr / close[-1])          # as fraction of last close


def _resample_to_timeframe(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """
    Resample a minute/hourly DataFrame to a coarser timeframe.
    `tf` accepts:  '15T','1H','4H','1D'  (pandas offset aliases)
    """
    alias_map = {
        "15m": "15min", "30m": "30min",
        "1h": "1h", "2h": "2h", "4h": "4h",
        "1d": "1D",
    }
    freq = alias_map.get(tf.lower(), tf)
    df2 = df.set_index("timestamps").sort_index()
    ohlcv = df2[["open", "high", "low", "close"]].resample(freq).agg({
        "open":  "first",
        "high":  "max",
        "low":   "min",
        "close": "last",
    })
    if "volume" in df2.columns:
        ohlcv["volume"] = df2["volume"].resample(freq).sum()
    ohlcv = ohlcv.dropna(subset=["open", "close"])
    ohlcv.reset_index(inplace=True)
    return ohlcv


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class KronosSignalGenerator:
    """
    Wraps a KronosPredictor and converts its raw forecast into
    actionable Buy / Sell / Hold signals.

    Parameters
    ----------
    predictor       : KronosPredictor instance
    context_len     : model max context (512 for small/base, 2048 for mini)
    lookback_ratio  : fraction of context used as lookback  (default 0.8)
    pred_len        : forecast horizon in candles           (default 30)
    sample_count    : Monte-Carlo samples for uncertainty   (default 5)
    temperature     : sampling temperature                  (default 0.8)
    top_p           : nucleus sampling probability          (default 0.9)
    atr_multiplier  : signal threshold = atr * multiplier  (default 0.5)
    """

    def __init__(
        self,
        predictor,
        context_len: int = 2048,
        lookback_ratio: float = 0.8,
        pred_len: int = 30,
        sample_count: int = 5,
        temperature: float = 0.8,
        top_p: float = 0.9,
        atr_multiplier: float = 0.5,
    ):
        self.predictor      = predictor
        self.context_len    = context_len
        self.pred_len       = pred_len
        self.lookback       = min(int(context_len * lookback_ratio), context_len - 10)
        self.sample_count   = sample_count
        self.temperature    = temperature
        self.top_p          = top_p
        self.atr_multiplier = atr_multiplier

    # ------------------------------------------------------------------
    def _single_tf_signal(self, df: pd.DataFrame, timeframe: str) -> SignalResult:
        """
        Run Kronos on `df` and return a SignalResult for one timeframe.
        `df` must already be at the desired timeframe resolution.
        """
        if len(df) < self.lookback + 5:
            # Fall back to shorter lookback if not enough data
            lb = max(len(df) - 10, 10)
        else:
            lb = self.lookback

        x_df = df.iloc[-lb:][["open", "high", "low", "close"] +
                              (["volume"] if "volume" in df.columns else [])].copy()
        x_ts = df.iloc[-lb:]["timestamps"].reset_index(drop=True)

        # Build future timestamps at the same frequency
        time_diff = x_ts.iloc[-1] - x_ts.iloc[-2] if len(x_ts) >= 2 else pd.Timedelta(hours=1)
        y_ts = pd.Series(
            pd.date_range(start=x_ts.iloc[-1] + time_diff, periods=self.pred_len, freq=time_diff)
        )

        # Run Kronos (multiple samples for uncertainty)
        samples = []
        for _ in range(self.sample_count):
            pred = self.predictor.predict(
                df=x_df.copy(),
                x_timestamp=x_ts.copy(),
                y_timestamp=y_ts.copy(),
                pred_len=self.pred_len,
                T=self.temperature,
                top_p=self.top_p,
                sample_count=1,
            )
            samples.append(pred["close"].values)

        # Aggregate samples
        all_closes  = np.stack(samples, axis=0)           # (n_samples, pred_len)
        median_path = np.median(all_closes, axis=0)
        std_path    = np.std(all_closes, axis=0)

        last_close      = float(df["close"].iloc[-1])
        forecast_close  = float(median_path[-1])           # end-of-horizon
        forecast_high   = float(self.predictor.predict(    # best-case high
            df=x_df.copy(), x_timestamp=x_ts.copy(),
            y_timestamp=y_ts.copy(), pred_len=self.pred_len,
            T=self.temperature, top_p=self.top_p, sample_count=1,
        )["high"].max() if self.sample_count > 0 else forecast_close)
        forecast_low    = float(self.predictor.predict(    # worst-case low
            df=x_df.copy(), x_timestamp=x_ts.copy(),
            y_timestamp=y_ts.copy(), pred_len=self.pred_len,
            T=self.temperature, top_p=self.top_p, sample_count=1,
        )["low"].min() if self.sample_count > 0 else forecast_close)

        return_pct = (forecast_close - last_close) / last_close * 100.0
        atr_pct    = _compute_atr(df.iloc[-lb:])
        threshold  = atr_pct * self.atr_multiplier * 100.0   # convert to %

        # Uncertainty (coefficient of variation at final period)
        cv = float(std_path[-1] / (abs(np.mean(all_closes[:, -1])) + 1e-9))

        # Confidence: inversely related to uncertainty, positively to signal strength
        raw_conf = min(abs(return_pct) / max(threshold * 2, 0.01), 1.0)
        confidence = float(raw_conf * max(0.1, 1.0 - cv))

        if return_pct > threshold:
            signal = "BUY"
        elif return_pct < -threshold:
            signal = "SELL"
        else:
            signal = "HOLD"

        return SignalResult(
            signal=signal,
            confidence=confidence,
            forecast_return_pct=return_pct,
            last_close=last_close,
            forecast_close=forecast_close,
            forecast_high=forecast_high,
            forecast_low=forecast_low,
            pred_len=self.pred_len,
            timeframe=timeframe,
            details={
                "atr_pct": round(atr_pct * 100, 4),
                "threshold_pct": round(threshold, 4),
                "uncertainty_cv": round(cv, 4),
                "n_samples": self.sample_count,
                "lookback": lb,
            },
        )

    # ------------------------------------------------------------------
    def analyze(
        self,
        df: pd.DataFrame,
        timeframes: Optional[List[str]] = None,
        source_tf: str = "1h",
    ) -> CompositeSignal:
        """
        Analyze one asset across multiple timeframes and return a
        CompositeSignal with a majority-vote recommendation.

        Parameters
        ----------
        df          : DataFrame with [timestamps, open, high, low, close, volume]
                      at the resolution of `source_tf`
        timeframes  : list of target TFs to analyze, e.g. ['1h', '4h', '1d']
                      If None, defaults to [source_tf]
        source_tf   : the candle resolution of the input `df`

        Returns
        -------
        CompositeSignal
        """
        if timeframes is None:
            timeframes = [source_tf]

        tf_signals: List[SignalResult] = []

        for tf in timeframes:
            try:
                # Resample if needed
                if tf.lower() == source_tf.lower():
                    df_tf = df.copy()
                else:
                    df_tf = _resample_to_timeframe(df, tf)

                if len(df_tf) < 20:
                    print(f"  ⚠  Not enough data for {tf}, skipping.")
                    continue

                sig = self._single_tf_signal(df_tf, tf)
                tf_signals.append(sig)
            except Exception as e:
                print(f"  ⚠  Error analyzing {tf}: {e}")

        if not tf_signals:
            return CompositeSignal(
                signal="HOLD",
                confidence=0.0,
                timeframe_signals=[],
                summary="Insufficient data to generate signals.",
            )

        # Majority vote
        from collections import Counter
        vote_weights = {s.signal: 0.0 for s in tf_signals}
        for s in tf_signals:
            vote_weights[s.signal] += s.confidence
        winner = max(vote_weights, key=vote_weights.get)
        total_conf = sum(vote_weights.values())
        composite_conf = vote_weights[winner] / max(total_conf, 1e-9)

        # Summary text
        lines = []
        for s in tf_signals:
            emoji = "🟢" if s.signal == "BUY" else ("🔴" if s.signal == "SELL" else "🟡")
            lines.append(
                f"  {emoji} {s.timeframe:<5s} → {s.signal:<4s}  "
                f"Δ={s.forecast_return_pct:+.2f}%  "
                f"conf={s.confidence:.0%}  "
                f"target={s.forecast_close:.4f}"
            )
        summary = "\n".join(lines)

        return CompositeSignal(
            signal=winner,
            confidence=composite_conf,
            timeframe_signals=tf_signals,
            summary=summary,
        )
