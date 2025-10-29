# strategy/ai_holding_advisor.py
"""
AI Holding Advisor (production-ready).

- Multi-provider AI adapters (OpenAI, OpenRouter, HuggingFace, Ollama).
- Rate-limit aware via provided RateLimitCache (so AI calls respect quotas).
- Heuristic fallback always returned if AI unavailable or rate-limited.
- Safe JSON extraction from model output.
- Use by calling AIHoldingAdvisor.suggest_hold_period(option_data, sentiment_score).

Environment variables you can set:
 - OPENAI_API_KEY
 - HUGGINGFACE_API_KEY
 - OPENROUTER_API_KEY
 - OLLAMA_API_URL
 - AI_MODEL_PROVIDER (optional preferred provider)
 - AI_MODEL_NAME (optional model name override)

Return format:
{
  "RecommendedDays": int,
  "Confidence": float,
  "Rationale": str,
  "source": str,            # "heuristic" or provider name
  "raw_model_text": ...     # debug text / model JSON
}
"""
from __future__ import annotations
import os
import time
import json
import re
import enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
from services.scanner.scanner_utils import wait_rate_limit
import requests

from services.core.cache_manager import RateLimitCache  
from services.logging.logger_singleton import getLogger
from strategy.ai_constants import AI_MODEL,all_ai_models,RateLimitError
from strategy.ai_interface import AIModelInterface

logger = getLogger()

from huggingface_hub import login
import os
login(token=os.getenv("HUGGINGFACE_TOKEN"))
# Logger default level controlled by your singleton configuration


# -------------------------
# Helper: safe JSON extraction from model text
# -------------------------
JSON_RE = re.compile(r"```(?:json)?\s*({.*?})\s*```", re.S)
BRACE_RE = re.compile(r"(\{(?:[^{}]|\{[^}]*\})*\})", re.S)  # safer-ish balanced-ish attempt


def _extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    try:
        # 1) code fence JSON
        m = JSON_RE.search(text)
        if m:
            return json.loads(m.group(1))
        # 2) find first {...} block
        m2 = BRACE_RE.search(text)
        if m2:
            candidate = m2.group(1)
            # remove trailing commas before closing braces/brackets
            candidate = re.sub(r",\s*([\]}])", r"\1", candidate)
            return json.loads(candidate)
    except Exception as e:
        logger.logMessage(f"[extract_json] parse failed: {e}; falling back to heuristic parsing.")
    return None


# -------------------------
# AIHoldingAdvisor
# -------------------------
class AIHoldingAdvisor:
    def __init__(self, preferred_model:AI_MODEL = None,
                 rate_cache: Optional[RateLimitCache] = None):
        self.rate_cache = rate_cache
        self.provider_order = []
        if preferred_model:
            self.provider_order.append(preferred_model)
            self.provider_order += [item for item in all_ai_models if item != preferred_model]
        else:
            self.provider_order = all_ai_models
            
        # Use passed interface OR the singleton


    def _heuristic_recommendation(self, option_data: Dict[str, Any], sentiment_score: Optional[float]) -> Dict[str, Any]:
        days = 3
        rationale = []

        cost = option_data.get("Cost", 0) or 0
        if isinstance(cost, str):
            try:
                cost = float(cost)
            except Exception:
                cost = 0.0
        if cost > 1000:
            rationale.append("High cost — short-term monitoring advised.")
            days -= 1

        if sentiment_score is not None:
            if sentiment_score > 0.6:
                rationale.append("Strong sentiment — allow more time for momentum.")
                days += 2
            elif sentiment_score < -0.3:
                rationale.append("Negative sentiment — cut losses quickly.")
                days -= 1

        iv = option_data.get("ImpliedVolatility", 0) or 0.0
        try:
            iv = float(iv)
        except Exception:
            iv = 0.0
        if iv > 0.6:
            rationale.append("High volatility — reduce exposure window.")
            days = min(days, 3)
        elif iv < 0.3:
            rationale.append("Low volatility — slow mover, extend hold.")
            days += 2

        days = max(1, min(days, 14))
        return {
            "ShouldBuy": bool(True),
            "RecommendedDays": int(days),
            "Confidence": 0.6,
            "Rationale": " ".join(rationale) or "Standard holding duration.",
            "source": "heuristic",
            "raw_model_text": None
        }

    def _build_prompt(self, option_data: Dict[str, Any], sentiment_score: Optional[float], base: Dict[str, Any]) -> str:
        safe = {k: option_data.get(k) for k in ("symbol", "Cost", "ImpliedVolatility", "Delta", "Theta", "Vega", "DaysToExpiry", "Score")}
        safe_str = json.dumps(safe, default=str)
        prompt = (
            "You are a concise financial analyst. Given the following structured call option metrics and new sentiment score, "
            "analyze them and propose whether or not the call option should be a buy (ShouldBuy), how long to hold onto it for (RecommendedDays), "
            "your confidence in the suggestion (Confidence), and your rationale behind it (Rationale). "
            "Return the response as a JSON object with fields: ShouldBuy(bool), RecommendedDays (int), Confidence (0.0-1.0 float), Rationale (string). "
            "ONLY return JSON (no extra commentary).\n\n"
            f"METRICS: {safe_str}\n"
            f"SENTIMENT: {None if sentiment_score is None else float(sentiment_score)}\n\n"
            "Return JSON now."
        )
        return prompt

    def _call_and_parse(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Try calling all available AI providers in order until one succeeds.
        Uses preloaded local model for Hugging Face provider (if available),
        otherwise dynamically instantiates provider interface.
        Returns parsed JSON dict or None if all providers fail.
        """

        logger = getLogger()

        attempts: Dict[str, int] = {p.name: 0 for p in self.provider_order}
        provider_index = 0

        while provider_index < len(self.provider_order):
            provider_enum = self.provider_order[provider_index]
            provider_name = provider_enum.name
            attempts[provider_name] += 1

            # Skip exhausted providers
            if attempts[provider_name] > 2:
                logger.logMessage(f"[AIHoldingAdvisor] Skipping {provider_name} (max retries reached)")
                provider_index += 1
                continue

            # Use preloaded local Hugging Face model if available
            ai_iface = AIModelInterface.create_from_env(preferred=provider_enum, rate_cache=self.rate_cache)

            if not ai_iface:
                logger.logMessage(f"[AIHoldingAdvisor] {provider_name} unavailable or rate-limited; rotating...")
                provider_index += 1
                continue

            # Handle rate limits
            if self.rate_cache and self.rate_cache.is_cached(provider_name):
                if attempts[provider_name] == 1:
                    logger.logMessage(f"[AIHoldingAdvisor] {provider_name} rate-limited, waiting for cooldown...")
                    try:
                        wait_rate_limit(self.rate_cache, provider_name)
                    except Exception as e:
                        logger.logMessage(f"[AIHoldingAdvisor] wait_rate_limit error for {provider_name}: {e}")
                    # Retry same provider after waiting
                    continue
                else:
                    logger.logMessage(f"[AIHoldingAdvisor] {provider_name} still rate-limited after wait, rotating...")
                    provider_index += 1
                    continue

            # Attempt model call
            try:
                raw = ai_iface.call(prompt)
                if not raw:
                    logger.logMessage(f"[AIHoldingAdvisor] Empty response from {provider_name}")
                    provider_index += 1
                    continue

                parsed = _extract_json_from_text(raw)
                if parsed:
                    parsed["raw_model_text"] = raw
                    parsed["source"] = provider_name
                    return parsed
                else:
                    logger.logMessage(f"[AIHoldingAdvisor] Failed to parse JSON from {provider_name}, rotating...")

            except RateLimitError:
                if self.rate_cache:
                    self.rate_cache.add(provider_name, int(os.getenv("AI_RATE_LIMIT_TTL", "30")))
                logger.logMessage(f"[AIHoldingAdvisor] Rate limit hit for {provider_name}, rotating...")
                provider_index += 1
                continue

            except Exception as e:
                logger.logMessage(f"[AIHoldingAdvisor] Error with {provider_name}: {e}")
                provider_index += 1
                continue

        logger.logMessage("[AIHoldingAdvisor] All AI providers exhausted or rate-limited.")
        return None


    def suggest_hold_period(self, option_data: Dict[str, Any], sentiment_score: Optional[float] = None) -> Dict[str, Any]:
        """
        Entry. Returns structured dict. Always returns heuristic fallback if AI unavailable.
        """
        base = self._heuristic_recommendation(option_data, sentiment_score)
        # Check rate cache before calling
        try:
            if self.rate_cache is not None and self.rate_cache.is_cached("AIModel"):
                logger.logMessage("[AIHoldingAdvisor] AIModel marked rate-limited in cache; returning heuristic")
                return base
        except Exception:
            logger.logMessage("[AIHoldingAdvisor] rate cache check failed; attempting AI call")

        try:
            prompt = self._build_prompt(option_data, sentiment_score, base)
            model_text = self._call_and_parse(prompt)

            if not model_text:
                logger.logMessage("AI returned nothing usable; falling back to heuristic")
                return base

            if "RecommendedDays" not in model_text:
                # annotate base with raw_model_text for debugging
                base["raw_model_text"] = model_text if isinstance(model_text, (dict, str)) else str(model_text)
                return base

            # sanitize
            try:
                days = int(model_text.get("RecommendedDays"))
            except Exception:
                days = int(base["RecommendedDays"])
            try:
                conf = float(model_text.get("Confidence", base.get("Confidence", 0.6)))
                conf = max(0.0, min(1.0, conf))
            except Exception:
                conf = base.get("Confidence", 0.6)
            rationale = str(model_text.get("Rationale", "")).strip() or base.get("Rationale", "")
            should_buy = bool(model_text.get("ShouldBuy"))
            if should_buy is None:
                base.get("ShouldBuy",True)

            days = max(1, min(30, days))

            result = {
                "ShouldBuy": bool(should_buy),
                "RecommendedDays": int(days),
                "Confidence": float(conf),
                "Rationale": rationale,
                "source": self.ai_interface.provider.name,
                "raw_model_text": model_text
            }
            return result

        except Exception as e:
            logger.logMessage(f"[AIHoldingAdvisor] AI call failed, returning heuristic. error: {e}")
            base["raw_model_text"] = f"ai_error: {e}"
            # mark rate-limit conservatively
            try:
                if self.rate_cache is not None:
                    self.rate_cache.add("AIModel", int(os.getenv("AI_RATE_LIMIT_TTL", "30")))
            except Exception:
                pass
            return base
