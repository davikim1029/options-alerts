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

import requests

from services.core.cache_manager import RateLimitCache  
from services.logging.logger_singleton import getLogger

class AI_MODEL(enum.Enum):
    OPENAI = "OPENAI"
    OPENROUTER = "OPENROUTER"
    HUGGINGFACE = "HUGGINGFACE"
    OLLAMA = "OLLAMA"

logger = getLogger()
# Logger default level controlled by your singleton configuration

# -------------------------
# AI Model Interface & Adapters
# -------------------------
@dataclass
class AIModelInterface:
    provider: str
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 10
    rate_cache: Optional[RateLimitCache] = None

    @staticmethod
    def create_from_env(preferred: Optional[AI_MODEL] = None, rate_cache: Optional[RateLimitCache] = None) -> Optional["AIModelInterface"]:
        """
        Pick provider from env (preferred first) and return configured interface.
        """
        provider_order = []
        all_ai_models =  [AI_MODEL.OPENAI, AI_MODEL.OPENROUTER, AI_MODEL.HUGGINGFACE, AI_MODEL.OLLAMA]
        if preferred:
            provider_order.append(preferred)
            filtered_list = [item for item in all_ai_models if item != preferred]
        else:
            filtered_list = all_ai_models

        provider_order += filtered_list
        
        seen = set()
        for p in provider_order:
            if not p or p in seen:
                continue
            seen.add(p)
            if p == AI_MODEL.OPENAI and os.getenv("OPENAI_API_KEY") and not rate_cache.is_cached(p):
                return AIModelInterface(
                    provider=p,
                    api_key=os.getenv("OPENAI_API_KEY"),
                    model_name=os.getenv("AI_MODEL_NAME", "gpt-4o-mini"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache
                )
            if p == AI_MODEL.OPENROUTER and os.getenv("OPENROUTER_API_KEY") and not rate_cache.is_cached(p):
                return AIModelInterface(
                    provider=p,
                    api_key=os.getenv("OPENROUTER_API_KEY"),
                    model_name=os.getenv("AI_MODEL_NAME", "mistralai/mistral-7b-instruct:free"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache
                )
            if p == AI_MODEL.HUGGINGFACE and os.getenv("HUGGINGFACE_API_KEY") and not rate_cache.is_cached(p):
                return AIModelInterface(
                    provider=p,
                    api_key=os.getenv("HUGGINGFACE_API_KEY"),
                    model_name=os.getenv("AI_MODEL_NAME", "gpt2"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache
                )
            if p == AI_MODEL.OLLAMA and os.getenv("OLLAMA_API_URL") and not rate_cache.is_cached(p):
                return AIModelInterface(
                    provider=p,
                    base_url=os.getenv("OLLAMA_API_URL"),
                    model_name=os.getenv("AI_MODEL_NAME", "llama2"),
                    timeout=int(os.getenv("AI_TIMEOUT", "30")),
                    rate_cache=rate_cache
                )
        return None

    def _post_with_retries(self, url: str, headers: Dict[str, str], json_payload: Dict[str, Any],
                        retries: int = 2, backoff: float = 1.0):
        """
        Perform POST with limited retries. If we hit 429 (rate limit), mark provider
        as rate-limited in cache and return None immediately (no retry sleep).
        """
        last_exc = None
        for attempt in range(1, retries + 2):
            try:
                resp = requests.post(url, headers=headers, json=json_payload, timeout=self.timeout)

                # --- Handle rate limit immediately ---
                if resp.status_code == 429:
                    logger.logMessage(f"[{self.provider}] rate limited (429). Skipping retries.")
                    if self.rate_cache is not None:
                        try:
                            ttl = int(os.getenv("AI_RATE_LIMIT_TTL", "60"))
                            self.rate_cache.add(self.provider, ttl)
                            logger.logMessage(f"[RateLimitCache] Marked {self.provider} as rate-limited for {ttl}s")
                        except Exception as e:
                            logger.logMessage(f"Failed to add {self.provider} to RateLimitCache: {e}")
                    return None  # no retries, caller will rotate to next provider

                # --- Normal success path ---
                resp.raise_for_status()
                return resp

            except requests.HTTPError as he:
                # Allow caller to handle specific 400/422 errors
                if 'resp' in locals() and resp is not None and resp.status_code in (400, 422):
                    logger.logMessage(f"[{self.provider}] HTTP {resp.status_code}: {resp.text}")
                    return resp
                last_exc = he

            except Exception as e:
                last_exc = e
                logger.logMessage(f"[{self.provider}] request attempt {attempt} failed: {e}")
                time.sleep(backoff * attempt)

        # all attempts failed
        raise last_exc


    def call(self, prompt: str) -> Optional[str]:
        """
        Call the configured provider with the prompt. Returns raw text if successful,
        otherwise None.
        """
        # If rate cache is set and AI is currently marked rate-limited, skip
        try:
            if self.rate_cache is not None and self.rate_cache.is_cached(self.provider):
                logger.logMessage("[AIModelInterface] AI rate-limited by cache; skipping call.")
                return None
        except Exception:
            # defensively continue (don't block AI if cache check errors)
            logger.logMessage("[AIModelInterface] rate cache check failed; proceeding.")

        try:
            if self.provider == AI_MODEL.OPENAI:
                return self._call_openai(prompt)
            if self.provider == AI_MODEL.HUGGINGFACE:
                return self._call_huggingface(prompt)
            if self.provider == AI_MODEL.OPENROUTER:
                return self._call_openrouter(prompt)
            if self.provider == AI_MODEL.OLLAMA:
                return self._call_ollama(prompt)
            logger.logMessage("No AI provider configured")
            return None
        except Exception as e:
            logger.logMessage(f"[AIModelInterface] call failed for {self.provider}: {e}")
            # On failure, mark rate-limited conservatively
            try:
                if self.rate_cache is not None:
                    self.rate_cache.add(self.provider, int(os.getenv("AI_RATE_LIMIT_TTL", "30")))
                    logger.logMessage("[AIModelInterface] Marked AI as temporarily rate-limited after exception.")
            except Exception:
                pass
            return None

    # ---- provider adapters ----
    def _call_openai(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY missing")
        url = "https://api.openai.com/v1/chat/completions"
        model = self.model_name or "gpt-4o-mini"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        messages = [
            {"role": "system", "content": "You are a concise financial analyst producing a short JSON answer."},
            {"role": "user", "content": prompt}
        ]
        payload = {"model": model, "messages": messages, "max_tokens": 400, "temperature": 0.25}
        resp = self._post_with_retries(url, headers, payload)
        if not resp:
            return None
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            return text
        except Exception:
            logger.logMessage(f"[openai] unexpected response shape: {resp.text if resp is not None else 'None'}")
            return None

    def _call_huggingface(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY missing")
        model = self.model_name or "bigscience/bloomz"
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"inputs": prompt, "parameters": {"max_new_tokens": 256, "temperature": 0.2}}
        resp = self._post_with_retries(url, headers, payload)
        if not resp:
            return None
        try:
            out = resp.json()
            if isinstance(out, dict) and "error" in out:
                logger.logMessage(f"[huggingface] error: {out.get('error')}")
                return None
            if isinstance(out, list) and len(out) and isinstance(out[0], dict):
                return out[0].get("generated_text")
            if isinstance(out, str):
                return out
            return json.dumps(out)
        except Exception as e:
            logger.logMessage(f"[huggingface] parse error: {e}")
            return None

    def _call_openrouter(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing")

        model = self.model_name or "mistralai/mistral-7b-instruct:free"
        url = "https://openrouter.ai/api/v1/chat/completions"


        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
        }

        resp = self._post_with_retries(url, headers, payload)
        if not resp:
            return None

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            logger.logMessage(f"[openrouter] unexpected response: {resp.text if resp is not None else 'None'}")
            return None

    def _call_ollama(self, prompt: str) -> Optional[str]:
        base = self.base_url or os.getenv("OLLAMA_API_URL")
        if not base:
            raise RuntimeError("OLLAMA_API_URL missing")
        model = self.model_name or "llama2"
        url = f"{base.rstrip('/')}/api/models/{model}/completions"
        headers = {"Content-Type": "application/json"}
        payload = {"prompt": prompt, "max_tokens": 512, "temperature": 0.2}
        resp = self._post_with_retries(url, headers, payload)
        if not resp:
            return None
        try:
            data = resp.json()
            if isinstance(data, dict) and data.get("choices"):
                return data["choices"][0]["message"]["content"]
            return json.dumps(data)
        except Exception as e:
            logger.logMessage(f"[ollama] parse error: {e}")
            return None


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
    def __init__(self, use_ai_model: bool = True, ai_model_interface: Optional[AIModelInterface] = None,
                 rate_cache: Optional[RateLimitCache] = None):
        """
        If ai_model_interface is None, we will attempt to create one from env.
        Pass rate_cache if you want AI calls to respect/mark rate-limits.
        """
        self.use_ai_model = use_ai_model
        self.rate_cache = rate_cache
        self.ai_interface = ai_model_interface or AIModelInterface.create_from_env(
            preferred=AI_MODEL.OPENROUTER, rate_cache=rate_cache
        )

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
            "You are a concise financial analyst. Given the following structured option metrics and a base heuristic suggestion, "
            "return a JSON object with fields: RecommendedDays (int), Confidence (0.0-1.0 float), Rationale (string). "
            "ONLY return JSON (no extra commentary). If uncertain, return an explanation of why you are uncertain followed up with the heuristic base suggestion.\n\n"
            f"METRICS: {safe_str}\n"
            f"SENTIMENT: {None if sentiment_score is None else float(sentiment_score)}\n\n"
            f"BASE_SUGGESTION: {json.dumps(base)}\n\n"
            "Return JSON now."
        )
        return prompt

    def _call_and_parse(self, prompt: str) -> Optional[Dict[str, Any]]:
        """
        Try calling all available AI providers in order until one succeeds.
        Automatically skips rate-limited providers (as marked in RateLimitCache).
        Returns parsed JSON dict or None if all providers fail.
        """
        if not self.ai_interface:
            logger.logMessage("No AI interface configured.")
            return None

        tried = set()
        result = None

        # Loop until we’ve tried all providers or succeed
        while self.ai_interface and self.ai_interface.provider not in tried:
            provider_name = self.ai_interface.provider
            tried.add(provider_name)

            # Skip if rate-limited
            if self.rate_cache and self.rate_cache.is_cached(provider_name):
                logger.logMessage(f"[AIHoldingAdvisor] Skipping {provider_name} (rate-limited in cache)")
                self.ai_interface = AIModelInterface.create_from_env(rate_cache=self.rate_cache)
                continue

            # Attempt call
            raw = self.ai_interface.call(prompt)

            if not raw:
                logger.logMessage(f"[AIHoldingAdvisor] {provider_name} returned no text or failed.")
                # Rotate to next provider
                self.ai_interface = AIModelInterface.create_from_env(rate_cache=self.rate_cache)
                continue

            # Try parsing output
            parsed = _extract_json_from_text(raw)
            if parsed:
                result = parsed
                break

            # Fallback simple parsing
            try:
                d = {}
                for line in raw.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        k = k.strip().strip('"').strip("'")
                        v = v.strip()
                        if re.match(r"^-?\d+$", v):
                            d[k] = int(v)
                        else:
                            try:
                                d[k] = float(v)
                            except Exception:
                                d[k] = v
                if "RecommendedDays" in d:
                    result = d
                    break
            except Exception:
                pass

            # Last resort — not parseable, move to next provider
            logger.logMessage(f"[AIHoldingAdvisor] {provider_name} output not parseable. Switching provider.")
            self.ai_interface = AIModelInterface.create_from_env(rate_cache=self.rate_cache)

        # Out of providers or succeeded
        if not result:
            logger.logMessage("[AIHoldingAdvisor] All AI providers exhausted or rate-limited.")
            return None

        return result


    def suggest_hold_period(self, option_data: Dict[str, Any], sentiment_score: Optional[float] = None) -> Dict[str, Any]:
        """
        Entry. Returns structured dict. Always returns heuristic fallback if AI unavailable.
        """
        base = self._heuristic_recommendation(option_data, sentiment_score)

        # If AI disabled or no interface, return base heuristic
        if not self.use_ai_model or not self.ai_interface:
            return base

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

            days = max(1, min(30, days))

            result = {
                "RecommendedDays": int(days),
                "Confidence": float(conf),
                "Rationale": rationale,
                "source": getattr(self.ai_interface, "provider", "ai"),
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
