from enum import Enum

class DriveState(Enum):
    STARVING = "STARVING"
    HUNGRY = "HUNGRY"
    NEUTRAL = "NEUTRAL"
    SATIATED = "SATIATED"
    RESEARCH_MODE = "RESEARCH_MODE"

class ObjectiveTracker:
    def __init__(self, start_of_week_val: float, start_of_month_val: float, current_val: float,
                 weekly_target_pct: float = 0.015, monthly_target_pct: float = 0.06):
        """
        Layered Goal Architecture.
        Checks current pacing against Weekly (1.5%) and Monthly (6.0%) goals.
        """
        self.start_of_week = start_of_week_val
        self.start_of_month = start_of_month_val
        self.current = current_val
        self.weekly_target = weekly_target_pct
        self.monthly_target = monthly_target_pct

    def evaluate(self) -> dict:
        """
        Returns a dictionary containing the bot's intrinsic state, 
        confidence modifier, and position multiplier based on Value-Difference Based Exploration.
        """
        weekly_yield = (self.current - self.start_of_week) / max(self.start_of_week, 1.0)
        monthly_yield = (self.current - self.start_of_month) / max(self.start_of_month, 1.0)

        weekly_miss = self.weekly_target - weekly_yield
        monthly_miss = self.monthly_target - monthly_yield

        # 1. Fear Threshold: Severe Drawdown
        if monthly_yield <= -0.05:
            return {
                "state": DriveState.RESEARCH_MODE.value,
                "confidence_modifier": 0.0,
                "position_multiplier": 0.0,
                "weekly_yield": round(weekly_yield, 4),
                "monthly_yield": round(monthly_yield, 4),
                "reason": "Severe Drawdown (-5%). Triggering Research Mode Strategy Shift."
            }

        # 2. VDBE Aggression Caps
        if weekly_miss > 0 and monthly_miss > 0:
            state = DriveState.STARVING
            # VDBE: drop confidence requirement based on total error, capped at 15% drop
            total_error = weekly_miss + monthly_miss
            conf_drop = min(total_error * 2.0, 0.15)
            pos_mult = 1.25  # Get aggressive with sizing
            reason = "Missed Weekly and Monthly Pacing. Starving."
            
        elif weekly_miss > 0 and monthly_miss <= 0:
            state = DriveState.HUNGRY
            # VDBE: small drop in confidence to slightly boost exploration
            conf_drop = min(weekly_miss, 0.05)
            pos_mult = 1.10
            reason = "Missed Weekly Pacing but Monthly is OK. Hungry."

        elif monthly_miss <= 0 and weekly_miss <= 0:
            state = DriveState.SATIATED
            # Satiated: Increase confidence requirement (play it extremely safe)
            conf_drop = -0.05  
            pos_mult = 0.8  # Defensive sizing
            reason = "Ahead of targets. Satiated. Defending capital."
            
        else:
            state = DriveState.NEUTRAL
            conf_drop = 0.0
            pos_mult = 1.0
            reason = "On Pace."

        return {
            "state": state.value,
            "confidence_modifier": -conf_drop, # If drop is positive, we lower the threshold (e.g. -0.15).
            "position_multiplier": pos_mult,
            "weekly_yield": round(weekly_yield, 4),
            "monthly_yield": round(monthly_yield, 4),
            "reason": reason
        }

# For testing
if __name__ == "__main__":
    # Test Starving
    tracker = ObjectiveTracker(10000.0, 10000.0, 9900.0)
    print("Test 1 (Starving):", tracker.evaluate())
    
    # Test Satiated
    tracker = ObjectiveTracker(10000.0, 10000.0, 10800.0)
    print("Test 2 (Satiated):", tracker.evaluate())
    
    # Test Fear
    tracker = ObjectiveTracker(10000.0, 10000.0, 9400.0)
    print("Test 3 (Fear):", tracker.evaluate())
