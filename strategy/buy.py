# strategy/buy.py
from strategy.base import BuyStrategy
from models.option import OptionContract
from datetime import datetime
import yfinance as yf
import math
import os
from typing import Optional, List
from services.logging.logger_singleton import getLogger
from strategy.ai_advisor import AIHoldingAdvisor, AIModelInterface
from strategy.ai_constants import AI_MODEL
from services.core.cache_manager import RateLimitCache

logger = getLogger()

# Small keyword list for fallback lexical sentiment (only used if no transformer)
_POS_WORDS = {"up", "gain", "rise", "beat", "beats", "surge", "upgrade", "positive", "growth", "record"}
_NEG_WORDS = {"down", "fall", "drop", "miss", "missed", "decline", "downgrade", "negative", "loss", "lawsuit"}


def realized_volatility_from_prices(prices, window_days=30) -> Optional[float]:
    try:
        import numpy as _np
        p = _np.asarray(prices, dtype=float)
        if p.size < 2:
            return None
        returns = _np.diff(_np.log(p))
        if returns.size < 2:
            return None
        vol = returns.std(ddof=1) * math.sqrt(252)
        return float(vol)
    except Exception:
        return None


class OptionBuyStrategy(BuyStrategy):
    """
    Unified, multi-factor option buy strategy returning (bool, message, score).
    - Expects context may include a precomputed sentiment: context["sentiment_signal"] (float -1..1)
    - Keeps original signature for compatibility with buy_scanner.
    """

    @property
    def name(self):
        return self.__class__.__name__

    def _vix_adjustment(self) -> int:
        """Small dynamic threshold adjustment based on VIX level."""
        try:
            v = yf.Ticker("^VIX").history(period="7d")["Close"].iloc[-1]
            if v is None:
                return 0
            if v > 25: return 2
            if v > 20: return 1
            if v < 15: return -1
        except Exception:
            return 0
        return 0

    def should_buy(self, option: OptionContract,caches, context: dict) -> tuple[bool, str, str]:
        try:
            now = datetime.now().astimezone()

            # ---------------------------
            # Hard Filters
            # ---------------------------
            try:
                cost = float(option.ask) * 100
            except Exception:
                return False, "Hard fail: invalid ask price", "N/A"
            cost_threshold = 50
            if cost > cost_threshold:
                return False, f"Hard fail: cost too high (${cost:.2f}). Threshold: ${cost_threshold}", "N/A"

            if not getattr(option, "expiryDate", None):
                return False, "Hard fail: no expiry", "N/A"
            days_to_expiry = max(0, (option.expiryDate - now).days)
            if days_to_expiry < 5:
                return False, f"Hard fail: Too close to expiration ({days_to_expiry}d)", "N/A"

            if not getattr(option, "OptionGreeks", None) or getattr(option.OptionGreeks, "delta", None) is None:
                return False, "Hard fail: missing Greeks", "N/A"

            if not getattr(option, "symbol", None):
                return False, "Hard fail: missing symbol", "N/A"

            # ---------------------------
            # Multi-factor scoring
            # ---------------------------
            score = 0.0
            breakdown: List[str] = []

            # Liquidity
            vol = getattr(option, "volume", 0) or 0
            oi = getattr(option, "openInterest", 0) or 0
            if vol >= 50 and oi >= 100:
                score += 2; breakdown.append(f"Liquidity V={vol},OI={oi} [Good] (+2)")
            elif vol >= 10 and oi >= 50:
                score += 1; breakdown.append(f"Liquidity V={vol},OI={oi} [Neutral] (+1)")
            else:
                score -= 2; breakdown.append(f"Liquidity V={vol},OI={oi} [Bad] (-2)")

            # Expiry preference
            if days_to_expiry is not None:
                if 5 <= days_to_expiry <= 30:
                    score += 2; breakdown.append(f"Expiry {days_to_expiry}d [Good] (+2)")
                elif 3 <= days_to_expiry < 5:
                    score += 1; breakdown.append(f"Expiry {days_to_expiry}d [Neutral] (+1)")
                else:
                    score -= 1; breakdown.append(f"Expiry {days_to_expiry}d [Bad] (-1)")

            # Strike proximity
            if getattr(option, "nearPrice", None):
                try:
                    spot = float(option.nearPrice)
                    strike = float(option.strikePrice)
                    pct_otm = abs(strike - spot) / spot if spot > 0 else 1.0
                    if pct_otm <= 0.10:
                        score += 2; breakdown.append(f"Strike {pct_otm:.1%} from spot [Good] (+2)")
                    elif pct_otm <= 0.20:
                        score += 1; breakdown.append(f"Strike {pct_otm:.1%} from spot [Neutral] (+1)")
                    else:
                        score -= 2; breakdown.append(f"Strike {pct_otm:.1%} [Bad] (-2)")
                except Exception:
                    breakdown.append("Strike proximity calc error [Neutral]")
            else:
                breakdown.append("No spot price available [Neutral]")

            # IV (relative)
            iv = getattr(option.OptionGreeks, "iv", None)
            iv_msg = "IV unknown"
            try:
                iv_score_bonus = 0
                if iv is not None:
                    iv_hist = getattr(option.OptionGreeks, "iv_history", None)
                    if iv_hist and len(iv_hist) >= 10:
                        recent = iv_hist[-30:]
                        pct = sum(1 for v in recent if v < iv) / len(recent)
                        if pct <= 0.3:
                            iv_score_bonus = 2; iv_msg = f"IV cheap pct={pct:.2f} (+2)"
                        elif pct <= 0.7:
                            iv_score_bonus = 1; iv_msg = f"IV neutral pct={pct:.2f} (+1)"
                        else:
                            iv_score_bonus = -2; iv_msg = f"IV rich pct={pct:.2f} (-2)"
                    else:
                        # fallback to realized volatility
                        try:
                            ticker = option.symbol
                            yf_t = yf.Ticker(ticker)
                            ph = yf_t.history(period="60d")["Close"].dropna()
                            if len(ph) >= 10:
                                rv = realized_volatility_from_prices(ph.values[-30:])
                                if rv is not None:
                                    if iv < rv:
                                        iv_score_bonus = 2; iv_msg = f"IV < realized ({iv:.2f} < {rv:.2f}) (+2)"
                                    else:
                                        iv_score_bonus = 0; iv_msg = f"IV >= realized ({iv:.2f} >= {rv:.2f}) (0)"
                                else:
                                    iv_score_bonus = 0; iv_msg = "IV fallback realized vol unavailable (0)"
                            else:
                                iv_score_bonus = 0; iv_msg = "IV fallback insufficient data (0)"
                        except Exception:
                            iv_score_bonus = 0; iv_msg = "IV fallback error (0)"
                else:
                    iv_score_bonus = 0; iv_msg = "IV missing [Neutral]"
                score += iv_score_bonus
                breakdown.append(iv_msg)
            except Exception as e:
                breakdown.append(f"IV calc error: {e}")

            # Greeks
            try:
                delta = getattr(option.OptionGreeks, "delta", None)
                gamma = getattr(option.OptionGreeks, "gamma", None)
                theta = getattr(option.OptionGreeks, "theta", None)
                greeks_msg = []

                # delta
                if delta is None:
                    greeks_msg.append("Delta missing")
                else:
                    if 0.3 <= delta <= 0.6:
                        score += 2; greeks_msg.append(f"Delta {delta:.2f} [Good] (+2)")
                    elif 0.2 <= delta < 0.3 or 0.6 < delta <= 0.7:
                        score += 1; greeks_msg.append(f"Delta {delta:.2f} [Neutral] (+1)")
                    else:
                        score -= 1; greeks_msg.append(f"Delta {delta:.2f} [Bad] (-1)")

                # gamma (scale down if near expiry)
                gamma_scale = 1.0
                if days_to_expiry is not None and days_to_expiry <= 7:
                    gamma_scale = 0.5
                if gamma is None:
                    greeks_msg.append("Gamma missing")
                else:
                    if gamma >= 0.02:
                        score += 1 * gamma_scale; greeks_msg.append(f"Gamma {gamma:.3f} [Good] (+{1*gamma_scale:.1f})")
                    elif gamma >= 0.01:
                        greeks_msg.append(f"Gamma {gamma:.3f} [Neutral] (0)")
                    else:
                        score -= 1 * gamma_scale; greeks_msg.append(f"Gamma {gamma:.3f} [Bad] (-{1*gamma_scale:.1f})")

                # theta (penalize near expiry)
                if theta is None:
                    greeks_msg.append("Theta missing")
                else:
                    if days_to_expiry is not None and days_to_expiry <= 7:
                        if theta > -0.08:
                            score += 1; greeks_msg.append(f"Theta {theta:.3f} [Good near expiry] (+1)")
                        else:
                            score -= 2; greeks_msg.append(f"Theta {theta:.3f} [Bad near expiry] (-2)")
                    else:
                        if theta > -0.20:
                            score += 1; greeks_msg.append(f"Theta {theta:.3f} [Good] (+1)")
                        else:
                            score -= 1; greeks_msg.append(f"Theta {theta:.3f} [Bad] (-1)")

                breakdown.append(" | ".join(greeks_msg))
            except Exception as e:
                breakdown.append(f"Greeks calc error: {e}")

            # Expected move vs strike
            try:
                if getattr(option, "nearPrice", None) and getattr(option.OptionGreeks, "iv", None) is not None and getattr(option, "expiryDate", None):
                    spot = float(option.nearPrice)
                    iv_cur = float(option.OptionGreeks.iv)
                    days = max(1, (option.expiryDate - now).days)
                    year_frac = days / 365.0
                    exp_move = spot * iv_cur * math.sqrt(year_frac)
                    dist = abs(option.strikePrice - spot)
                    if dist <= exp_move:
                        score += 2; breakdown.append(f"Strike within 1σ (dist {dist:.2f} <= {exp_move:.2f}) (+2)")
                    elif dist <= 1.5 * exp_move:
                        score += 1; breakdown.append("Strike within 1.5σ (+1)")
                    else:
                        score -= 2; breakdown.append("Strike outside expected move (-2)")
                else:
                    breakdown.append("Expected move: insufficient data [Neutral]")
            except Exception:
                breakdown.append("Expected move calc error [Neutral]")

            # Trend (EMA 8/21) + RSI
            try:
                hist = None
                if option.symbol:
                    yf_t = yf.Ticker(option.symbol)
                    hist = yf_t.history(period="2mo")
                if hist is not None and len(hist) >= 20:
                    short_ema = hist["Close"].ewm(span=8).mean().iloc[-1]
                    long_ema = hist["Close"].ewm(span=21).mean().iloc[-1]
                    if short_ema > long_ema * 1.01:
                        score += 2; breakdown.append("EMA trend strong bullish (+2)")
                    elif short_ema > long_ema * 0.995:
                        score += 1; breakdown.append("EMA trend mild bullish (+1)")
                    else:
                        score -= 2; breakdown.append("EMA trend bearish (-2)")

                    # RSI
                    try:
                        close = hist["Close"]
                        delta_s = close.diff().dropna()
                        up = delta_s.clip(lower=0).ewm(com=13, adjust=False).mean()
                        down = (-delta_s.clip(upper=0)).ewm(com=13, adjust=False).mean()
                        rs = up / down
                        rsi = 100 - (100 / (1 + rs)).iloc[-1]
                        if rsi < 30:
                            score += 1; breakdown.append(f"RSI {rsi:.1f} oversold (+1)")
                        elif rsi > 70:
                            score -= 1; breakdown.append(f"RSI {rsi:.1f} overbought (-1)")
                        else:
                            breakdown.append(f"RSI {rsi:.1f} neutral (0)")
                    except Exception:
                        breakdown.append("RSI calc failed [Neutral]")
                else:
                    breakdown.append("Trend data insufficient [Neutral]")
            except Exception as e:
                breakdown.append(f"Trend fetch error: {e}")

            # Sentiment (provided by scanner via context to avoid thrashing)
            try:
                sent = None
                if context and context.get("sentiment_signal") is not None:
                    sent = context.get("sentiment_signal")
                # if not present, we avoid fetching headlines here (do not call network from inner loop)
                if sent is not None:
                    # sentiment is -1..1; use thresholds
                    if sent > 0.15:
                        score += 2; breakdown.append(f"News sentiment {sent:.2f} [Bullish] (+2)")
                    elif sent < -0.15:
                        score -= 2; breakdown.append(f"News sentiment {sent:.2f} [Bearish] (-2)")
                    else:
                        breakdown.append(f"News sentiment {sent:.2f} [Neutral] (0)")
                else:
                    breakdown.append("Sentiment not provided [Neutral]")
            except Exception as e:
                breakdown.append(f"Sentiment error: {e}")

            # Final dynamic thresholding
            vix_adj = self._vix_adjustment()
            base_threshold = 14
            threshold = base_threshold + vix_adj

            summary = f"[BUY SIGNAL] {option.symbol} | Score={score:.2f} | Factors: " + " | ".join(breakdown)

            if score >= threshold:
                # --- optional: estimate holding period and append to summary ---
                try:

                    rate_cache = getattr(caches, "rate", None)  # your scanner already provides this
                    # create model interface automatically from env (preferred)
                    advisor = AIHoldingAdvisor(rate_cache=rate_cache)

                    option_data = {
                        "symbol": option.symbol,
                        "Cost": float(getattr(option, "ask", 0)) * 100,
                        "ImpliedVolatility": getattr(option.OptionGreeks, "iv", None),
                        "Delta": getattr(option.OptionGreeks, "delta", None),
                        "Theta": getattr(option.OptionGreeks, "theta", None),
                        "Vega": getattr(option.OptionGreeks, "vega", None),
                        "DaysToExpiry": (option.expiryDate - datetime.now().astimezone()).days if option.expiryDate else None,
                        "Score": score
                    }
                    sent = context.get("sentiment_signal") if context else None
                    hold_rec = advisor.suggest_hold_period(option_data, sent)
                    # Append hold_rec summary to your summary string for alerts/logging
                        

                    hold_msg = f" | HoldDays={hold_rec.get('RecommendedDays')}"
                    # include rationale if you want more verbosity (comment/uncomment)
                    hold_rationale = hold_rec.get("Rationale")
                    hold_source = hold_rec.get("source")
                    if hold_rationale:
                        hold_msg += f" | Rationale: {hold_rationale} | Source: {hold_source}"
                    summary = summary + hold_msg
                except Exception as e:
                    # do not change buy result if estimator fails
                    try:
                        logger.logMessage(f"[BuyStrategy] hold estimator failed: {e}")
                    except Exception:
                        pass
                return hold_rec.get("ShouldBuy",True) , summary, score
            else:
                return False, summary, score

        except Exception as e:
            logger.logMessage(f"[BuyStrategy error] {e}")
            return False, f"[BuyStrategy error] {e}", "N/A"
