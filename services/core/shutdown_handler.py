# shutdown_manager.py
import atexit
import signal
import sys
from threading import Lock

class ShutdownManager:
    _callbacks = []
    _lock = Lock()
    _initialized = False
    _exit_reason = "normal"
    _error_logger = None  # function to call on callback errors

    @classmethod
    def init(cls,error_logger=None):
        if cls._initialized:
            return
        cls._initialized = True
        cls._error_logger = error_logger
        atexit.register(cls._run_callbacks)
        signal.signal(signal.SIGINT, cls._handle_signal)
        signal.signal(signal.SIGTERM, cls._handle_signal)

    @classmethod
    def register(cls, callback):
        with cls._lock:
            cls._callbacks.append(callback)

    @classmethod
    def _run_callbacks(cls):
        with cls._lock:
            for cb in cls._callbacks:
                try:
                    cb(cls._exit_reason)
                except Exception as e:
                    if cls._error_logger:
                        cls._error_logger(f"[ShutdownManager] Error running callback {cb}: {e}")
                    else:
                        print(f"[ShutdownManager] Error running callback {cb}: {e}")

    @classmethod
    def _handle_signal(cls, signum, frame):
        signal_names = {signal.SIGINT: "SIGINT (Ctrl+C)", signal.SIGTERM: "SIGTERM"}
        cls._exit_reason = signal_names.get(signum, f"Signal {signum}")
        cls._run_callbacks()
        sys.exit(0)
