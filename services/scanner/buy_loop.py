# services/scanner/buy_loop.py
import time
from services.utils import logMessage
from services.scanner.buy_scanner import run_buy_scan  # your main buy logic

def buy_loop(stop_event, **kwargs):
    """
    Hot-reload-aware buy loop.
    - stop_event: threading.Event used to gracefully stop the loop
    - kwargs: contains consumer, caches, debug, etc.
    """
    consumer = kwargs.get("consumer")
    caches = kwargs.get("caches")
    debug = kwargs.get("debug", False)

    logMessage("[Buy Scanner] Module loaded/reloaded")
    logMessage("[Buy Scanner] Starting run_buy_scan")

    while not stop_event.is_set():
        try:
            # Your main buy scanning logic goes here
            run_buy_scan(stop_event=stop_event, consumer=consumer, caches=caches, debug=debug)
        except Exception as e:
            logMessage(f"[Buy Scanner Error] {e}")
        time.sleep(1)  # avoid busy-looping
