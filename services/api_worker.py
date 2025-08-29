# api_worker.py
import queue
import time
from requests import Session
import enum
from dataclasses import dataclass
from typing import Optional, Any
import requests

class HttpMethod(enum.Enum):
    GET = "GET"
    PUT = "PUT"
    POST = "POST"
    DELETE = "DELETE"

@dataclass
class HttpResult:
    ok: bool
    status_code: Optional[int] = None
    data: Optional[Any] = None
    error: Optional[str] = None
    response: Optional[requests.Response] = None

class ApiWorker:
    def __init__(self, session: Session, min_interval: float = 1.0):
        self.session = session
        self._queue = queue.Queue()
        self._min_interval = min_interval
        self._last_call = 0

    def _worker(self, stop_event):
        """Worker loop to process HTTP requests from the queue."""
        while not stop_event.is_set():
            try:
                method, url, kwargs, result = self._queue.get(timeout=1)
            except queue.Empty:
                continue  # periodically check stop_event

            # Throttle requests
            now = time.time()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                stop_event.wait(self._min_interval - elapsed)
            self._last_call = time.time()

            try:
                if method == HttpMethod.GET:
                    r = self.session.get(url, **kwargs)
                elif method == HttpMethod.PUT:
                    r = self.session.put(url, **kwargs)
                elif method == HttpMethod.POST:
                    r = self.session.post(url, **kwargs)
                elif method == HttpMethod.DELETE:
                    r = self.session.delete(url, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                r.raise_for_status()
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

            self._queue.task_done()

    def call_api(self, method: HttpMethod, url: str, **kwargs) -> HttpResult:
        """Queue an API call and wait for result synchronously."""
        result = []
        self._queue.put((method, url, kwargs, result))
        self._queue.join()
        res = result[0]
        if isinstance(res, Exception):
            raise res
        return res
