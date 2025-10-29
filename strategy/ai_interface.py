import enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
from services.core.cache_manager import RateLimitCache 
from services.logging.logger_singleton import getLogger 
import requests
import os
import time
from datetime import datetime
from models.option_features import OptionFeatures
from strategy.ai_constants import AI_MODEL,all_ai_models,RateLimitError
logger = getLogger()

# -------------------------
# AI Model Interface & Adapters
# -------------------------
@dataclass
class AIModelInterface:
    provider: str
    provider_order: Optional[str] = None
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
        if preferred:
            provider_order.append(preferred)
            provider_order += [item for item in all_ai_models if item != preferred]
        else:
            provider_order = all_ai_models
        
        seen = set()
        for p in provider_order:
            if not p or p in seen:
                continue
            seen.add(p)
            if p == AI_MODEL.OPENAI and os.getenv("OPENAI_API_KEY") and not rate_cache.is_cached(p.name):
                return AIModelInterface(
                    provider=p,
                    provider_order=provider_order,
                    api_key=os.getenv("OPENAI_API_KEY"),
                    model_name=os.getenv("AI_MODEL_NAME", "gpt-4o-mini"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache
                )
            if p == AI_MODEL.OPENROUTER and os.getenv("OPENROUTER_API_KEY") and not rate_cache.is_cached(p.name):
                return AIModelInterface(
                    provider=p,
                    provider_order=provider_order,
                    api_key=os.getenv("OPENROUTER_API_KEY"),
                    model_name=os.getenv("AI_MODEL_NAME", "mistralai/mistral-7b-instruct:free"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache
                )
            if p == AI_MODEL.HUGGINGFACE and not rate_cache.is_cached(p.name):
                return AIModelInterface(
                    provider=p,
                    provider_order=provider_order,
                    api_key=os.getenv("HUGGINGFACE_TOKEN"),  # keep key for potential cloud fallback
                    model_name=os.getenv("AI_MODEL_NAME", "microsoft/Phi-3-mini-4k-instruct"),
                    timeout=int(os.getenv("AI_TIMEOUT", "20")),
                    rate_cache=rate_cache,
                )
            if p == AI_MODEL.OLLAMA and os.getenv("OLLAMA_API_URL") and not rate_cache.is_cached(p.name):
                return AIModelInterface(
                    provider=p,
                    provider_order=provider_order,
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
                    logger.logMessage(f"[{self.provider.name}] rate limited (429). Skipping retries.")
                    if self.rate_cache is not None:
                        try:
                            ttl = int(os.getenv("AI_RATE_LIMIT_TTL", "60"))
                            self.rate_cache.add(self.provider.name, ttl)
                            logger.logMessage(f"[RateLimitCache] Marked {self.provider.name} as rate-limited for {ttl}s")
                        except Exception as e:
                            logger.logMessage(f"Failed to add {self.provider.name} to RateLimitCache: {e}")
                    raise RateLimitError

                # --- Normal success path ---
                resp.raise_for_status()
                return resp

            except requests.HTTPError as he:
                # Allow caller to handle specific 400/422 errors
                if 'resp' in locals() and resp is not None and resp.status_code in (400, 422):
                    logger.logMessage(f"[{self.provider.name}] HTTP {resp.status_code}: {resp.text}")
                    return resp
                last_exc = he

            except Exception as e:
                last_exc = e
                logger.logMessage(f"[{self.provider.name}] request attempt {attempt} failed: {e}")
                time.sleep(backoff * attempt)

        # all attempts failed
        raise last_exc


    def call(self, prompt: str) -> Optional[str]:
        """
        Call the configured provider with the prompt. Returns raw text if successful,
        otherwise None.
        """

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
        except RateLimitError:
            raise
        except Exception as e:
            logger.logMessage(f"[AIModelInterface] call failed for {self.provider.name}: {e}")
            # On failure, mark rate-limited conservatively
            try:
                if self.rate_cache is not None:
                    self.rate_cache.add(self.provider.name, int(os.getenv("AI_RATE_LIMIT_TTL", "30")))
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
        # fallback: original Hugging Face API call
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY missing")
        model = self.model_name or "microsoft/Phi-3-mini-4k-instruct"
        url = f"https://api-inference.huggingface.co/models/{model}"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"inputs": prompt, "parameters": {"max_new_tokens": 256, "temperature": 0.2}}
        resp = self._post_with_retries(url, headers, payload)
        if not resp:
            return None
        try:
            out = resp.json()
            if isinstance(out, dict) and "error" in out:
                logger.logMessage(f"[huggingface-api] error: {out.get('error')}")
                return None
            if isinstance(out, list) and len(out) and isinstance(out[0], dict):
                return out[0].get("generated_text")
            if isinstance(out, str):
                return out
            return json.dumps(out)
        except Exception as e:
            logger.logMessage(f"[huggingface-api] parse error: {e}")
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


def option_to_features(opt, sentiment_score: float = 0.0) -> OptionFeatures:
    expiry = opt.expiryDate
    days_to_exp = (expiry - datetime.now(expiry.tzinfo)).days

    bid = opt.bid if opt.bid is not None else None
    ask = opt.ask if opt.ask is not None else None

    spread = (ask - bid) if (ask is not None and bid is not None) else None
    mid = ((ask + bid) / 2) if (ask is not None and bid is not None) else None
    moneyness = ((opt.nearPrice - opt.strikePrice) / opt.nearPrice) if opt.nearPrice else None

    return OptionFeatures(
        symbol=opt.symbol,
        optionType=1 if opt.optionType.upper() == "CALL" else 0,
        strikePrice=opt.strikePrice,
        lastPrice=opt.lastPrice,
        bid=bid,
        ask=ask,
        bidSize=opt.bidSize,
        askSize=opt.askSize,
        openInterest=opt.openInterest,
        volume=opt.volume,
        inTheMoney=1 if opt.inTheMoney.lower() == 'y' else 0,
        nearPrice=opt.nearPrice,
        delta=opt.OptionGreeks.delta,
        gamma=opt.OptionGreeks.gamma,
        theta=opt.OptionGreeks.theta,
        vega=opt.OptionGreeks.vega,
        rho=opt.OptionGreeks.rho,
        iv=opt.OptionGreeks.iv,
        daysToExpiration=days_to_exp,
        spread=spread,
        midPrice=mid,
        moneyness=moneyness,
        sentiment=sentiment_score,
        timestamp=datetime.now(timezone.utc)
    )
