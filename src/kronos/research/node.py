import os
import requests
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from textblob import TextBlob

# Load the keys from .env file into os.environ
load_dotenv()

class ResearchNode:
    """
    Tri-Node Research Engine.
    Triggered when the agent hits RESEARCH_MODE (e.g. -5% severe drawdown).
    It orchestrates requests to FRED (Macro), FMP (Sentiment), and AlphaVantage (Correlation)
    to restructure the portfolio category allocations.
    """
    def __init__(self):
        self.fred_api_key = os.getenv("FRED_API_KEY", "")
        self.fmp_api_key = os.getenv("FMP_API_KEY", "")
        self.av_api_key = os.getenv("ALPHAVANTAGE_API_KEY", "")

    def _fetch_fred_macro(self) -> dict:
        """Fetch Federal Reserve interest rate/liquidity data."""
        if not self.fred_api_key:
            print("[ResearchNode] FRED API key missing. Using simulated macro data.")
            return {"status": "Hawkish", "fed_funds_rate": 5.25, "risk": "HIGH_YIELD_RISK"}
            
        try:
            # Example: DFF (Effective Federal Funds Rate)
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id=DFF&api_key={self.fred_api_key}&file_type=json&limit=5&sort_order=desc"
            res = requests.get(url, timeout=5)
            data = res.json()
            latest = float(data["observations"][0]["value"])
            return {"status": "Hawkish" if latest > 4.0 else "Dovish", "fed_funds_rate": latest}
        except Exception as e:
            return {"status": "Error", "error": str(e)}

    def _fetch_fmp_sentiment(self) -> dict:
        """Fetch broader market sentiment via FinancialModelingPrep News API."""
        if not self.fmp_api_key:
            print("[ResearchNode] FMP API key missing. Using simulated sentiment data.")
            return {"overall_sentiment": "BEARISH", "polarity": -0.15, "catalyst": "Tech Earnings Miss"}

        try:
            url = f"https://financialmodelingprep.com/api/v3/stock_news?limit=20&apikey={self.fmp_api_key}"
            res = requests.get(url, timeout=5)
            news = res.json()
            
            polarities = []
            for item in news:
                title = item.get("title", "")
                if title:
                    blob = TextBlob(title)
                    polarities.append(blob.sentiment.polarity)
                    
            avg_polarity = sum(polarities) / len(polarities) if polarities else 0.0
            
            if avg_polarity < -0.1:
                sentiment = "BEARISH"
            elif avg_polarity > 0.1:
                sentiment = "BULLISH"
            else:
                sentiment = "MIXED"
                
            return {"overall_sentiment": sentiment, "avg_polarity": round(avg_polarity, 3), "articles_scanned": len(news)}
        except Exception as e:
            return {"status": "Error", "error": str(e)}

    def _fetch_alpha_vantage_correlation(self) -> dict:
        """Fetch broad indices from AlphaVantage to find negatively correlated hedges."""
        if not self.av_api_key:
            print("[ResearchNode] AlphaVantage key missing. Using simulated correlation matrix.")
            return {"recommended_hedge": "Gold (XAU)", "crypto_correlation": 0.85, "equity_correlation": -0.2}

        try:
            # Example: Fetch SPY to correlate against Crypto/Other categories
            url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=SPY&apikey={self.av_api_key}"
            res = requests.get(url, timeout=5)
            data = res.json()
            return {"spy_latest": data.get("Global Quote", {}).get("05. price", "N/A")}
        except Exception as e:
            return {"status": "Error", "error": str(e)}

    def execute_deep_research(self) -> dict:
        """
        Orchestrates the 3-node scan and outputs a revised category allocation strategy.
        """
        print("\n[ResearchNode] Initiating Deep Tri-Node Market Scan...")
        
        macro_data = self._fetch_fred_macro()
        print(f"[ResearchNode] Macro Node (FRED) -> {macro_data}")
        
        sentiment_data = self._fetch_fmp_sentiment()
        print(f"[ResearchNode] Sentiment Node (FMP) -> {sentiment_data}")
        
        correlation_data = self._fetch_alpha_vantage_correlation()
        print(f"[ResearchNode] Correlation Node (AlphaVantage) -> {correlation_data}")

        # Synthesize a Strategy Shift based on data
        # Simulated logic: if hawkish and bearish, shift to defensive/hedge assets.
        shift_plan = {
            "action": "HALT_HIGH_BETA",
            "recommended_allocation": {
                "crypto_large": 0.20,
                "crypto_mid": 0.00,
                "india_large": 0.30,
                "commodities_gold": 0.50 # Hedging the drawdown
            },
            "greedy_recovery_multiplier": 1.5,
            "reasoning": "Macro environment hawkish. Sentiment bearish. Shifted to Gold (XAU) hedge to stabilize drawdown before applying greedy recovery multiplier."
        }
        
        print(f"[ResearchNode] Strategy Shift Concluded: {shift_plan['action']}")
        return shift_plan

if __name__ == "__main__":
    node = ResearchNode()
    result = node.execute_deep_research()
    print("\nFinal Strategy Plan:")
    print(json.dumps(result, indent=2))
