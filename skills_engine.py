import pandas as pd
import yfinance as yf
from datetime import datetime
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

# Initialize NLTK VADER (it needs the lexicon)
try:
    nltk.data.find('vader_lexicon')
except LookupError:
    nltk.download('vader_lexicon', quiet=True)

class SkillsEngine:
    def __init__(self):
        self.sia = SentimentIntensityAnalyzer()
        self.session_trade_counts = {}

    def evaluate_trade(self, asset, signal, df, open_positions):
        """
        Runs all three validator nodes on a proposed trade.
        Returns: (bool allowed, str reason)
        """
        if signal != "BUY":
            return True, "Not a BUY, skipping blocks"

        symbol = asset["symbol"]
        category = asset.get("category", "crypto_mid")
        is_indian = category.startswith("india")
        is_crypto = category.startswith("crypto")

        # 1. Market Regime & Risk Node
        regime_allowed, regime_reason = self._check_regime_and_risk(asset, is_indian, is_crypto, df, open_positions)
        if not regime_allowed:
            return False, regime_reason

        # 2. Technical Analysis Node
        if df is not None and len(df) > 50:
            ta_allowed, ta_reason = self._check_technical_analysis(df, signal)
            if not ta_allowed:
                return False, ta_reason

        # 3. Fundamental / News Sentiment Node
        if not is_crypto:
            news_allowed, news_reason = self._check_news_sentiment(asset, is_indian)
            if not news_allowed:
                return False, news_reason

        return True, "Trade approved by Master Orchestrator"

    def _check_regime_and_risk(self, asset, is_indian, is_crypto, df, open_positions):
        today_str = datetime.now().strftime("%Y-%m-%d")
        trade_count = self.session_trade_counts.get(today_str, 0)
        
        if is_indian and trade_count >= 4:
            return False, "Regime Node: Indian Session cap reached (4 trades/session)"
        if is_crypto and trade_count >= 10:
            return False, "Regime Node: Crypto 24h cap reached (10 trades/24h)"
        if (not is_indian and not is_crypto) and trade_count >= 4:
            return False, "Regime Node: US Session cap reached (4 trades/session)"

        return True, "Regime OK"

    def increment_trade_counter(self):
        today_str = datetime.now().strftime("%Y-%m-%d")
        self.session_trade_counts[today_str] = self.session_trade_counts.get(today_str, 0) + 1

    def _check_technical_analysis(self, df, signal):
        try:
            # We must operate on a copy to avoid SettingWithCopyWarning
            work_df = df.copy()
            
            # Native RSI (14) Calculation
            delta = work_df['close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
            rs = avg_gain / avg_loss
            work_df['RSI_14'] = 100 - (100 / (1 + rs))
            
            # Native SMA (200) Calculation
            work_df['SMA_200'] = work_df['close'].rolling(window=200).mean()
                
            latest = work_df.iloc[-1]
            
            if signal == "BUY":
                rsi = latest.get("RSI_14")
                if pd.notna(rsi) and rsi > 80:
                    return False, f"TA Node: RSI is {rsi:.1f} (Overbought context). Waiting for pullback."
                
                sma = latest.get("SMA_200")
                if pd.notna(sma) and latest['close'] < sma * 0.95:
                    return False, "TA Node: Multi-Timeframe Confluence VETO. Severe bearish trend."
                    
            return True, "TA OK"
        except Exception as e:
            print(f"TA eval error: {e}")
            return True, "TA calculation failed, defaulting to allow"

    def _check_news_sentiment(self, asset, is_indian):
        ticker = asset.get("yf_ticker", asset["symbol"])
        if is_indian and not ticker.endswith((".NS", ".BO")):
            ticker = ticker.replace("NSE:", "").replace("-EQ", "") + ".NS"
            
        try:
            stock = yf.Ticker(ticker)
            news = stock.news
            if not news:
                return True, "No news available"
                
            scores = []
            for item in news[:5]:
                title = item.get("title", "")
                sentiment = self.sia.polarity_scores(title)
                scores.append(sentiment['compound'])
                
            if not scores:
                return True, "No headlines found"
                
            avg_sentiment = sum(scores) / len(scores)
            
            if avg_sentiment < -0.30:
                return False, f"Fundamental Node: VETO. Negative news sentiment ({avg_sentiment:.2f})"
                
            return True, f"Sentiment OK ({avg_sentiment:.2f})"
        except Exception as e:
            print(f"News sentiment error for {ticker}: {e}")
            return True, "Sentiment fetch failed"
