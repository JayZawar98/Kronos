import datetime
from database import get_all_trade_history

class StrategyAnalyzer:
    def __init__(self):
        # Baseline rules for each category type
        self.market_profiles = {
            "high_volatility": ["crypto_large", "crypto_mid", "india_small"],
            "low_volatility": ["india_large", "india_mid", "us_large"]
        }
        
        # Default starting values for the dynamic parameters
        self.defaults = {
            "position_mult": 1.0,
            "confidence_floor": 0.60,
            "stop_loss_mult": 1.0  # 1.0 means use 100% of the baseline stop loss from HOLD_RULES
        }

        # Cache of current category insights
        self.insights = {}

    def analyze(self):
        """Analyze trade history to produce dynamic regime-aware parameters for each category."""
        history = get_all_trade_history()
        
        # Group trades by category
        cat_trades = {}
        for t in history:
            cat = t.get("category", "other")
            if cat not in cat_trades:
                cat_trades[cat] = []
            cat_trades[cat].append(t)

        new_insights = {}

        # Default all known categories even if no trades exist yet
        all_known = self.market_profiles["high_volatility"] + self.market_profiles["low_volatility"]
        for cat in all_known:
            trades = cat_trades.get(cat, [])
            
            if len(trades) < 5:
                # Not enough data, return defaults
                new_insights[cat] = {
                    "win_rate": 0.0,
                    "avg_pnl_pct": 0.0,
                    "trade_count": len(trades),
                    "profile": dict(self.defaults)
                }
                continue

            # Calculate metrics on the last 50 trades to stay relevant to current regime
            recent_trades = trades[-50:]
            wins = [t for t in recent_trades if t["pnl"] > 0]
            win_rate = len(wins) / len(recent_trades)
            avg_pnl_pct = sum(t["pnl_percent"] for t in recent_trades) / len(recent_trades)

            # Build dynamic profile
            profile = dict(self.defaults)
            
            is_high_vol = cat in self.market_profiles["high_volatility"]
            
            if win_rate < 0.40:
                # LOSING STREAK
                if is_high_vol:
                    # High Volatility: Avoid whipsaws. Don't tighten stops. Slash position size, demand high confidence.
                    profile["position_mult"] = 0.4
                    profile["confidence_floor"] = 0.75
                    profile["stop_loss_mult"] = 1.0 # Give it room to breathe
                else:
                    # Low Volatility: Mean reverting. Slash position size, tighten stops.
                    profile["position_mult"] = 0.5
                    profile["confidence_floor"] = 0.70
                    profile["stop_loss_mult"] = 0.6 # Tighten stops to cut losses fast
                    
            elif win_rate >= 0.60:
                # WINNING STREAK
                if is_high_vol:
                    # High Volatility: Ride the momentum run hard.
                    profile["position_mult"] = 1.5
                    profile["confidence_floor"] = 0.55
                else:
                    # Low Volatility: Mean reversion risk. Cap scaling.
                    profile["position_mult"] = 1.2
                    profile["confidence_floor"] = 0.55
                    
            else:
                # CHOPPY / NEUTRAL
                pass # Stays at default
                
            new_insights[cat] = {
                "win_rate": round(win_rate * 100, 1),
                "avg_pnl_pct": round(avg_pnl_pct, 2),
                "trade_count": len(recent_trades),
                "profile": profile
            }

        self.insights = new_insights
        print(f"[Strategist] Analyzed {len(history)} trades. Generated profiles for {len(self.insights)} categories.")

    def get_profile(self, category: str) -> dict:
        """Get the current dynamic parameters for a category."""
        return self.insights.get(category, {}).get("profile", dict(self.defaults))

    def get_all_insights(self) -> dict:
        return self.insights

if __name__ == "__main__":
    analyzer = StrategyAnalyzer()
    analyzer.analyze()
    print("Insights:")
    for cat, data in analyzer.get_all_insights().items():
        print(f"[{cat}] Win Rate: {data['win_rate']}% | Profile: {data['profile']}")
