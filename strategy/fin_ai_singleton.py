# strategy/fin_ai_singleton.py
import threading
import os
from services.core.cache_manager import RateLimitCache
from services.logging.logger_singleton import getLogger

# Import lazily to avoid circular import at module load
_logger = getLogger()
_lock = threading.Lock()
_global_ai_iface = None

def _init_ai_interface(rate_cache: RateLimitCache = None, preferred=None):
    """
    Internal initializer that constructs the AIModelInterface and (optionally)
    preloads a local HF model (FinMA/Mistral). This should block until fully loaded.
    """
    # lazy imports to avoid circular import problems
    from strategy.ai_constants import AI_MODEL,AIModelInterface
    from strategy.FinMA7BLocal import FinMA7BLocal
    import os
    # create interface using environment / preferred
    ai_iface = AIModelInterface.create_from_env(preferred=preferred or AI_MODEL.HUGGINGFACE, rate_cache=rate_cache)

    # If the selected provider is HUGGINGFACE and we want a local model, ensure the local model
    # is *explicitly* created only here (preload) and attached to the interface.
    try:
        if ai_iface.provider == AI_MODEL.HUGGINGFACE and not getattr(ai_iface, "local_hf_model", None):
            model_name = os.getenv("AI_LOCAL_MODEL", "microsoft/Phi-3-mini-4k-instruct")
            _logger.logMessage(f"[fin_ai_singleton] Loading local Hugging Face model: {model_name}")
            ai_iface.local_hf_model = FinMA7BLocal(model_name=model_name, device=None)
            _logger.logMessage("[fin_ai_singleton] ✅ Local model ready")
    except Exception as e:
        _logger.logMessage(f"[fin_ai_singleton] Local model preload failed: {e}")


    _ai_interface = ai_iface
    return _ai_interface

def get_ai_interface(rate_cache: RateLimitCache = None, preferred=None):
    """
    Thread-safe lazy getter for the global AIModelInterface.
    If multiple threads call this while it's uninitialized, they will block on the lock
    until initialization completes. Returns the singleton instance.
    """
    global _global_ai_iface
    if _global_ai_iface is not None:
        return _global_ai_iface

    with _lock:
        if _global_ai_iface is None:
            _global_ai_iface = _init_ai_interface(rate_cache=rate_cache, preferred=preferred)
    return _global_ai_iface

def preload(rate_cache: RateLimitCache = None, preferred=None):
    """
    Explicit synchronous preload helper. Call this in main thread *before* starting any worker threads.
    This will block until model download + initialization completes (or raises).
    """
    return get_ai_interface(rate_cache=rate_cache, preferred=preferred)
