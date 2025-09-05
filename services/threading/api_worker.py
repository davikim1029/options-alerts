# services/threading/api_worker.py
import queue
import time
import threading
from requests import Session
import enum
from dataclasses import dataclass
from typing import Optional, Any
import requests

# ---------------------------
# HTTP method enum
# ---------------------------
class HttpMethod(enum.Enum):
    GET = "GET"
    PUT = "PUT"
    POST = "POST"
    DELETE = "DELETE"

# ---------------------------
# HTTP result container
# ---------------------------
@dataclass
class HttpResult:
    ok: bool
    status_code: Optional[int] = None
    data: Optional[Any] = None
    error: Optional[str] = None
    response: Optional[requests.Response] = None

# ---------------------------
# ApiWorker class
# ---------------------------
class ApiWorker:
    def __init__(self, session: Session, min_interval: float = 1.0, default_timeout: float = 30.0):
        self.session = session
        self._queue = queue.Queue()
        self._min_interval = min_interval
        self._last_call = 0.0
        self._lock = threading.Lock()
        self._default_timeout = default_timeout
        self._stop_event = threading.Event()

    def _worker(self, stop_event):
        stop_event = stop_event or self._stop_event
        while not stop_event.is_set() or not self._queue.empty():
            try:
                method, url, kwargs, result = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                stop_event.wait(self._min_interval - elapsed)
            self._last_call = time.time()

            try:
                timeout = kwargs.pop("timeout", self._default_timeout)
                r = None
                if method == HttpMethod.GET:
                    r = self.session.get(url, timeout=timeout, **kwargs)
                elif method == HttpMethod.PUT:
                    r = self.session.put(url, timeout=timeout, **kwargs)
                elif method == HttpMethod.POST:
                    r = self.session.post(url, timeout=timeout, **kwargs)
                elif method == HttpMethod.DELETE:
                    r = self.session.delete(url, timeout=timeout, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                r.raise_for_status()
                # Automatically parse JSON if applicable
                result.append(HttpResult(ok=True, status_code=r.status_code, data=r, response=r))

            except requests.exceptions.HTTPError as e:
                result.append(HttpResult(
                    ok=False,
                    status_code=e.response.status_code if e.response else None,
                    error=f"HTTPError: {str(e)}",
                    response=e.response
                ))
            except Exception as e:
                result.append(HttpResult(ok=False, error=f"Error: {str(e)}"))
            finally:
                self._queue.task_done()


    def call_api(self, method: HttpMethod, url: str, timeout: float = 10.0, **kwargs) -> HttpResult:
        """
        Queue an API call and wait for result, but return early if the ApiWorker
        is stopped or the timeout is reached.
        """
        result = []
        self._queue.put((method, url, kwargs, result))

        start_time = time.time()
        while not result:
            # Check if the worker is shutting down
            if self._stop_event.is_set():
                return HttpResult(ok=False, error="ApiWorker stopped before request completed")
            
            # Check if we exceeded the timeout
            if timeout is not None and (time.time() - start_time) > timeout:
                return HttpResult(ok=False, error="Timeout waiting for ApiWorker")
            
            time.sleep(0.05)

        # Worker returned a result
        res = result[0]
        if isinstance(res, Exception):
            raise res
        return res

    
    
    

# ---------------------------
# Module-level singleton
# ---------------------------
_worker_instance: Optional[ApiWorker] = None

def init_worker(session: Session, min_interval: float = 1.0):
    """Initialize the module-level ApiWorker singleton."""
    global _worker_instance
    _worker_instance = ApiWorker(session, min_interval=min_interval)

def get_worker() -> ApiWorker:
    """Get the module-level ApiWorker singleton."""
    if _worker_instance is None:
        raise RuntimeError("ApiWorker not initialized. Call init_worker() first.")
    return _worker_instance
