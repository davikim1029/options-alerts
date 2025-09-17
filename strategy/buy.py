# strategy/buy.py
from strategy.base import BuyStrategy
from models.option import OptionContract
from datetime import datetime, timedelta, timezone
import yfinance as yf

class OptionBuyStrategy(BuyStrategy):
    @property
    def name(self):
        return self.__class__.__name__

    def should_buy(self, option: OptionContract, context: dict) -> tuple[bool, str]:
        try:
            now = datetime.now(timezone.utc)
            score = 0
            reasons = []

            # 1. Cost (prefer < $200, allow up to $350)
            cost = option.ask * 100
            if cost <= 200:
                score += 2
            elif cost <= 350:
                score += 1
            else:
                score -= 2
                reasons.append("Cost > $350")

            # 2. Liquidity (prefer higher volume & OI)
            if option.volume >= 50 and option.openInterest >= 100:
                score += 2
            elif option.volume >= 10 and option.openInterest >= 50:
                score += 1
            else:
                score -= 2
                reasons.append("Low liquidity")

            # 3. Expiry (prefer 5–30 days, penalize ultra-short)
            if option.expiryDate:
                days_to_expiry = (option.expiryDate - now).days
                if 5 <= days_to_expiry <= 30:
                    score += 2
                elif 3 <= days_to_expiry < 5:
                    score += 1
                else:
                    score -= 2
                    reasons.append("Bad expiry window")

            # 4. Strike proximity (prefer near ATM, allow up to 20% OTM)
            if option.nearPrice:
                pct_otm = abs(option.strikePrice - option.nearPrice) / option.nearPrice
                if pct_otm <= 0.10:
                    score += 2
                elif pct_otm <= 0.20:
                    score += 1
                else:
                    score -= 2
                    reasons.append("Strike too far OTM")

            # 5. Implied Volatility (prefer < 80%, allow up to 120%)
            if option.OptionGreeks.iv <= 0.80:
                score += 2
            elif option.OptionGreeks.iv <= 1.20:
                score += 1
            else:
                score -= 2
                reasons.append("IV too high")

            # 6. Greeks
            delta = option.OptionGreeks.delta
            gamma = option.OptionGreeks.gamma
            theta = option.OptionGreeks.theta

            if 0.3 <= delta <= 0.6:
                score += 2
            elif 0.2 <= delta < 0.3 or 0.6 < delta <= 0.7:
                score += 1
            else:
                score -= 1
                reasons.append("Delta weak")

            if gamma >= 0.02:
                score += 1
            elif gamma >= 0.01:
                score += 0  # neutral
            else:
                score -= 1
                reasons.append("Gamma too low")

            if theta > -0.20:
                score += 1
            else:
                score -= 1
                reasons.append("Theta decay too high")

            # 7. Trend check
            symbol = option.symbol
            if symbol:
                yf_data = yf.Ticker(symbol)
                hist = yf_data.history(period="1mo")
                if len(hist) >= 20:
                    short_term = hist["Close"].rolling(window=5).mean().iloc[-1]
                    long_term = hist["Close"].rolling(window=20).mean().iloc[-1]
                    if short_term > long_term * 0.98:
                        score += 2
                    else:
                        score -= 2
                        reasons.append("Bearish trend")
                else:
                    reasons.append("Insufficient history")
            else:
                reasons.append("Missing symbol")
                score -= 2

            # Decision threshold
            threshold = 5  # tune this: higher = stricter
            if score >= threshold:
                return True, ""
            else:
                return False, "; ".join(reasons[:2]) or "Score below threshold"

        except Exception as e:
            return False, f"[BuyStrategy error] {e}"
