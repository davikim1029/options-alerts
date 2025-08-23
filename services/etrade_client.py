# api_worker.py
import queue, threading, time

class ApiWorker:
    def __init__(self, min_interval=1.0):
        self._queue = queue.Queue()
        self._min_interval = min_interval
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        while True:
            func, args, kwargs, result = self._queue.get()
            # throttle
            now = time.time()
            elapsed = now - getattr(self, "_last_call", 0)
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.time()

            try:
                result.append(func(*args, **kwargs))
            except Exception as e:
                result.append(e)
            self._queue.task_done()

    def call_api(self, func, *args, **kwargs):
        result = []
        self._queue.put((func, args, kwargs, result))
        self._queue.join()
        res = result[0]
        if isinstance(res, Exception):
            raise res
        return res
