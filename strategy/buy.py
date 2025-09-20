# strategy/buy.py
from strategy.base import BuyStrategy
from models.option import OptionContract
from datetime import datetime, timedelta, timezone
import yfinance as yf

class OptionBuyStrategy(BuyStrategy):
    @property
    def name(self):
        return self.__class__.__name__

    def should_buy(self, option: OptionContract, context: dict) -> tuple[bool, str,str]:
        try:
            now = datetime.now().astimezone()

            # ========================
            # Phase 1: Hard Filters
            # ========================
            cost = option.ask * 100
            cost_threshold = 100
            if cost > cost_threshold: 
                return False, f"Hard fail: cost too high (${cost:.2f}). Threshold: ${cost_threshold}", "N/A"
            
            min_expiry = 5
            if option.expiryDate:
                days_to_expiry = (option.expiryDate - now).days
                if days_to_expiry < min_expiry:
                    return False, f"Hard fail: Too close to expiration. Min Expiry days: {min_expiry}","N/A"

            if not option.OptionGreeks or option.OptionGreeks.delta is None:
                return False, "Hard fail: missing Greeks","N/A"

            if not option.symbol:
                return False, "Hard fail: missing symbol","N/A"

            # ========================
            # Phase 2: Scoring System
            # ========================
            score = 0
            breakdown = []

            # --- Liquidity ---
            if option.volume >= 50 and option.openInterest >= 100:
                score += 2; breakdown.append(f"Liquidity V={option.volume},OI={option.openInterest} [Good] (+2)")
            elif option.volume >= 10 and option.openInterest >= 50:
                score += 1; breakdown.append(f"Liquidity V={option.volume},OI={option.openInterest} [Neutral] (+1)")
            else:
                score -= 2; breakdown.append(f"Liquidity V={option.volume},OI={option.openInterest} [Bad] (-2)")

            # --- Expiry ---
            if option.expiryDate:
                days_to_expiry = (option.expiryDate - now).days
                if 5 <= days_to_expiry <= 30:
                    score += 2; breakdown.append(f"Expiry {days_to_expiry}d [Good] (+2)")
                elif 3 <= days_to_expiry < 5:
                    score += 1; breakdown.append(f"Expiry {days_to_expiry}d [Neutral] (+1)")
                else:
                    score -= 2; breakdown.append(f"Expiry {days_to_expiry}d [Bad] (-2)")

            # --- Strike proximity ---
            if option.nearPrice:
                pct_otm = abs(option.strikePrice - option.nearPrice) / option.nearPrice
                if pct_otm <= 0.10:
                    score += 2; breakdown.append(f"Strike {pct_otm:.1%} from spot [Good] (+2)")
                elif pct_otm <= 0.20:
                    score += 1; breakdown.append(f"Strike {pct_otm:.1%} from spot [Neutral] (+1)")
                else:
                    score -= 2; breakdown.append(f"Strike {pct_otm:.1%} [Bad] (-2)")

            # --- IV ---
            iv = option.OptionGreeks.iv
            if iv <= 0.80:
                score += 2; breakdown.append(f"IV {iv:.0%} [Good] (+2)")
            elif iv <= 1.20:
                score += 1; breakdown.append(f"IV {iv:.0%} [Neutral] (+1)")
            else:
                score -= 2; breakdown.append(f"IV {iv:.0%} [Bad] (-2)")

            # --- Greeks ---
            delta = option.OptionGreeks.delta
            gamma = option.OptionGreeks.gamma
            theta = option.OptionGreeks.theta

            if 0.3 <= delta <= 0.6:
                score += 2; breakdown.append(f"Delta {delta:.2f} [Good] (+2)")
            elif 0.2 <= delta < 0.3 or 0.6 < delta <= 0.7:
                score += 1; breakdown.append(f"Delta {delta:.2f} [Neutral] (+1)")
            else:
                score -= 1; breakdown.append(f"Delta {delta:.2f} [Bad] (-1)")

            if gamma >= 0.02:
                score += 1; breakdown.append(f"Gamma {gamma:.3f} [Good] (+1)")
            elif gamma >= 0.01:
                breakdown.append(f"Gamma {gamma:.3f} [Neutral] (0)")
            else:
                score -= 1; breakdown.append(f"Gamma {gamma:.3f} [Bad] (-1)")

            if theta > -0.20:
                score += 1; breakdown.append(f"Theta {theta:.3f} [Good] (+1)")
            else:
                score -= 1; breakdown.append(f"Theta {theta:.3f} [Bad] (-1)")

            # --- Trend check ---
            yf_data = yf.Ticker(option.symbol)
            hist = yf_data.history(period="1mo")
            if len(hist) >= 20:
                short_term = hist["Close"].rolling(window=5).mean().iloc[-1]
                long_term = hist["Close"].rolling(window=20).mean().iloc[-1]
                if short_term > long_term * 0.98:
                    score += 2; breakdown.append("Trend bullish [Good] (+2)")
                else:
                    score -= 2; breakdown.append("Trend bearish [Bad] (-2)")
            else:
                breakdown.append("Trend data insufficient [Neutral] (0)")

            # ========================
            # Final Decision
            # ========================
            threshold = 5  # tune as needed, higher is more strict
            summary = f"Score={score}, Threshold={threshold} | " + " | ".join(breakdown)

            if score >= threshold:
                return True, summary, score
            else:
                return False, summary, score

        except Exception as e:
            return False, f"[BuyStrategy error] {e}"
