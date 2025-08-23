from strategy.base import BuyStrategy

class LowRiskBuyStrategy(BuyStrategy):
    def should_buy(self, option, context):
        return (
            option.ask * 100 <= 200 and
            option.volume > 100 and
            0.3 <= option.delta <= 0.6 and
            context["exposure"] < 1000
        )
