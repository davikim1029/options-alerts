# strategy/buy.py
from strategy.base import BuyStrategy,SellStrategy
from models.option import OptionContract
from datetime import datetime, timedelta,timezone
import yfinance as yf

class OptionBuyStrategy(BuyStrategy):
    @property
    def name(self):
        return self.__class__.__name__
    
    def should_buy(self, option: OptionContract, context: dict) -> tuple[bool,str]:

        try:

            # 1. Cost < $200
            if option.ask * 100 > 200:
                return False, "Cost > $200"

            # 2. Liquidity
            if option.volume < 50 or option.openInterest < 100:
                return False, "Volume less than 50 or Interest < 100"

            # 3. Expiry ≥ 7 days
            if option.expiryDate:
                now = datetime.now(timezone.utc)
                if option.expiryDate - now < timedelta(days=7):
                    return False, "Expiration within 7 days"

            # 4. Strike within 10% of current price
            if option.nearPrice and abs(option.strikePrice - option.nearPrice) / option.nearPrice > 0.10:
                return False, "Strike Price more than 10% of underlying price"

            # 5. IV < 80%
            if option.OptionGreeks.iv > 0.80:
                return False, "IV > 80"

            # 6. Greeks:
            if not (0.3 <= option.OptionGreeks.delta <= 0.6):
                return False, "Delta outside of .3 to .6"
            if option.OptionGreeks.gamma < 0.02:
                return False, "Gamma < .02"
            if option.OptionGreeks.theta < -0.1:  # negative = losing premium fast
                return False, "Theta < -.1"

            # 7. Market trend confirmation (via yfinance)
            symbol = option.symbol
            if not symbol:
                return False, "No Symbol found"

            yf_data = yf.Ticker(symbol)
            hist = yf_data.history(period="1mo")
            if len(hist) < 10:
                return False, "Missing history"

            short_term = hist["Close"].rolling(window=5).mean().iloc[-1]
            long_term = hist["Close"].rolling(window=20).mean().iloc[-1]

            if short_term < long_term:
                return False, "Bearish"  # trend is bearish

            return True, ""

        except Exception as e:
            error = f"[BuyStrategy error] {e}"
            return False,error
