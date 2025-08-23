# strategy/sell.py

from strategy.base import SellStrategy

# --- Primary strategies ---

class OptionSellStrategy(SellStrategy):
    name = "Options"
    
    def should_sell(self,position,context):
        if position.Product.securityType != "OPTN":
            return False,"Not an option" 
        if position.totalGain > 20 or position.daysGainPct > 30:
            return True, f"Gain: {position.totalGain} and Pct: {position.totalGainPct}"
        return False,"Insufficient Gain"

class StopLossStrategy(SellStrategy):
    name = "StopLoss"

    def should_sell(self, position, context):
        stop_loss_pct = context.get("stop_loss_pct", -20)
        gain = getattr(position, "totalGainPct", None)

        if gain is not None and gain <= stop_loss_pct:
            return True, ""
        return False, f"Gain {gain:.2f}% above stop-loss threshold"


class TakeProfitStrategy(SellStrategy):
    name = "TakeProfit"

    def should_sell(self, position, context):
        take_profit_pct = context.get("take_profit_pct", 50)
        gain = getattr(position, "totalGainPct", None)

        if gain is not None and gain >= take_profit_pct:
            return True, ""
        return False, f"Gain {gain:.2f}% below take-profit threshold"


# --- Secondary strategies ---
class TimeDecayStrategy(SellStrategy):
    name = "TimeDecay"

    def should_sell(self, position, context):
        days_held = getattr(position, "daysHeld", 0)
        max_days = context.get("max_days", 30)

        if days_held > max_days:
            return False, f"Held {days_held} days (> {max_days})"
        return True, ""
