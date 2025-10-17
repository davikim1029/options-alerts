# strategy/hold_estimator.py
"""
Hold estimator for option recommendations.

Public API:
- estimate_holding_period(option: OptionContract, context: dict) -> dict

Returned dict structure:
{
  "hold_days": int,                # recommended holding days (1..14+)
  "category": "very-short"|"short"|"medium"|"long",
  "rationale": str,                # human-readable explanation of why
  "reevaluate_after_hours": int    # recommended hours to re-evaluate
}

This module is defensive (doesn't throw) and uses fields commonly available
in your OptionContract and OptionGreeks. It also optionally consults the
scanner-provided sentiment signal stored in context["sentiment_signal"].

Tune weights and thresholds to taste.
"""

from datetime import datetime, timezone
import math
from typing import Dict, Any
from services.logging.logger_singleton import getLogger

logger = getLogger()

# Configuration / tuning parameters (adjust to your risk profile)
MAX_HOLD_DAYS = 14
DEFAULT_HOLD_DAYS = 3

# Weights (tuneable)
WEIGHTS = {
    "iv": -2.0,        # higher IV -> shorter hold
    "theta": -1.8,     # faster theta decay -> shorter hold
    "delta": 1.2,      # stronger delta (directional exposure) -> longer hold
    "days_to_expiry": -2.5,  # fewer days left -> shorter hold
    "sentiment": 1.5,  # positive sentiment -> longer hold
    "trend": 1.0,      # positive trend -> longer hold
    "vega": -0.8       # high vega -> shorter hold
}

# thresholds used to translate continuous score -> discrete days
SCORE_TO_DAYS = [
    (2.5, MAX_HOLD_DAYS),   # very bullish / low risk
    (1.5, 10),
    (0.8, 7),
    (0.0, 4),
    (-0.8, 2),
    (-1e9, 1)               # strongly negative -> immediate short hold
]


def _safe_float(x, default=None):
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _normalize_iv(iv: float) -> float:
    """Normalize IV into approx 0..1 scale for weighting (expect decimals like 0.3..1.5)"""
    if iv is None:
        return 0.5
    # typical IV range: 0.05 - 3.0, compress into 0..1
    v = max(0.01, min(3.0, iv))
    return (v - 0.05) / (3.0 - 0.05)


def _normalize_theta(theta: float) -> float:
    """Theta is typically negative; convert to positive magnitude and scale 0..1"""
    if theta is None:
        return 0.0
    return min(1.0, max(0.0, abs(theta) / 5.0))  # very coarse scaling


def _normalize_delta(delta: float) -> float:
    if delta is None:
        return 0.0
    return min(1.0, max(0.0, abs(delta)))  # delta typically between 0 and 1


def _normalize_vega(vega: float) -> float:
    if vega is None:
        return 0.0
    # coarse normalization; vega commonly small decimals
    return min(1.0, max(0.0, abs(vega) / 2.0))


def _days_to_expiry(option) -> int:
    try:
        if not getattr(option, "expiryDate", None):
            return 999
        now = datetime.now().astimezone()
        days = max(0, (option.expiryDate - now).days)
        return days
    except Exception:
        return 999


def _estimate_trend_strength(option) -> float:
    """
    Lightweight trend proxy: expectation that option/context created already computed trend.
    Try to read option.nearPrice & option._trend (if present) otherwise return 0.
    This function intentionally avoids network calls.
    """
    try:
        # if upstream added a precomputed trend metric in option or context, prefer it
        if hasattr(option, "_trend_strength"):
            return float(option._trend_strength)
        # fallback: presence of nearPrice and strike relationship as a weak trend proxy
        if getattr(option, "nearPrice", None):
            diff = abs(getattr(option, "strikePrice", 0) - float(option.nearPrice))
            # smaller diff may indicate in-play; use as tiny positive signal
            return max(0.0, 1.0 - min(1.0, diff / max(1.0, float(option.nearPrice))))
    except Exception:
        pass
    return 0.0


def estimate_holding_period(option: Any, context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Main entrypoint. Takes an OptionContract-like object and optional context dict.
    Returns recommendation dict (see module docstring).
    This function is defensive and will never raise.
    """
    try:
        context = context or {}
        # read greeks and metrics safely
        greeks = getattr(option, "OptionGreeks", None) or {}
        iv = _safe_float(getattr(greeks, "iv", None), None)
        theta = _safe_float(getattr(greeks, "theta", None), None)
        delta = _safe_float(getattr(greeks, "delta", None), None)
        vega = _safe_float(getattr(greeks, "vega", None), None)

        days = _days_to_expiry(option)
        sentiment_signal = None
        if isinstance(context.get("sentiment_signal", None), (int, float)):
            sentiment_signal = float(context.get("sentiment_signal"))
        # if option object has sentiment stored, prefer that
        if sentiment_signal is None and hasattr(option, "sentiment_signal"):
            try:
                sentiment_signal = float(option.sentiment_signal)
            except Exception:
                sentiment_signal = None

        # normalize inputs
        n_iv = _normalize_iv(iv)
        n_theta = _normalize_theta(theta)
        n_delta = _normalize_delta(delta)
        n_vega = _normalize_vega(vega)
        n_sent = 0.0
        if sentiment_signal is not None:
            # sentiment expected in [-1,1], map to -1..1
            n_sent = max(-1.0, min(1.0, sentiment_signal))

        trend = _estimate_trend_strength(option)

        # compute a composite score
        # positive score -> allow longer hold; negative -> shorten
        score = 0.0
        score += WEIGHTS["iv"] * (0.5 - n_iv)       # lower IV increases score
        score += WEIGHTS["theta"] * (0.5 - n_theta) # lower theta magnitude increases score
        score += WEIGHTS["delta"] * n_delta
        score += WEIGHTS["vega"] * (0.5 - n_vega)
        # days to expiry: more days -> more runway (positive), but huge days shouldn't over-inflate
        days_factor = 0.0
        if days <= 0:
            days_factor = -1.5
        elif days < 7:
            days_factor = -1.0
        elif days < 21:
            days_factor = 0.25
        else:
            days_factor = 0.6
        score += WEIGHTS["days_to_expiry"] * days_factor

        score += WEIGHTS["sentiment"] * n_sent
        score += WEIGHTS["trend"] * trend

        # small bounding to avoid extreme values
        score = max(-5.0, min(5.0, score))

        # map score to days via thresholds
        hold_days = DEFAULT_HOLD_DAYS
        category = "medium"
        for threshold, days_map in SCORE_TO_DAYS:
            if score >= threshold:
                hold_days = days_map
                break

        # ensure hold_days does not exceed days to expiry (leave 1-day buffer)
        if days < hold_days:
            hold_days = max(1, days - 0)  # don't subtract too aggressively

        # Build rationale lines
        rationale_parts = []
        rationale_parts.append(f"Score {score:.2f}")
        if iv is not None:
            rationale_parts.append(f"IV={iv:.2f}")
        if theta is not None:
            rationale_parts.append(f"Theta={theta:.3f}")
        if delta is not None:
            rationale_parts.append(f"Delta={delta:.2f}")
        rationale_parts.append(f"DaysToExpiry={days}")
        if sentiment_signal is not None:
            rationale_parts.append(f"Sentiment={sentiment_signal:.2f}")
        if trend:
            rationale_parts.append(f"Trend={trend:.2f}")

        rationale = "; ".join(rationale_parts)

        # map hold_days to category
        if hold_days <= 1:
            category = "very-short"
        elif hold_days <= 2:
            category = "short"
        elif hold_days <= 6:
            category = "medium"
        else:
            category = "long"

        # recommended re-eval cadence: shorter for riskier trades
        # use inverse of absolute score magnitude for re-eval (more extreme -> re-eval less frequently)
        reeval_hours = int(max(2, min(48, 12 - math.copysign(1, score) * score * 2)))
        # clamp
        reeval_hours = max(1, min(48, reeval_hours))

        return {
            "hold_days": int(hold_days),
            "category": category,
            "rationale": rationale,
            "reevaluate_after_hours": int(reeval_hours),
            "internal_score": float(score)
        }

    except Exception as e:
        # fail-safe: return conservative short-hold recommendation
        try:
            logger.logMessage(f"[HoldEstimator] error: {e}")
        except Exception:
            pass
        return {
            "hold_days": DEFAULT_HOLD_DAYS,
            "category": "medium",
            "rationale": f"estimator_error: {e}",
            "reevaluate_after_hours": 12,
            "internal_score": 0.0
        }
