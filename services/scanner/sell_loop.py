# services/scanner/sell_loop.py
import time
from services.utils import logMessage
from services.scanner.sell_scanner import run_sell_scan  # your main sell logic

seconds_to_wait=600

def sell_loop(stop_event, **kwargs):
    """
    Hot-reload-aware sell loop.
    - stop_event: threading.Event used to gracefully stop the loop
    - kwargs: contains consumer, caches, debug, etc.
    """
    consumer = kwargs.get("consumer")
    caches = kwargs.get("caches")
    debug = kwargs.get("debug", False)

    logMessage("[Sell Scanner] Module loaded/reloaded")

    while not stop_event.is_set():
        try:
            # Your main sell scanning logic goes here
            run_sell_scan(stop_event=stop_event, consumer=consumer, caches=caches,seconds_to_wait=seconds_to_wait, debug=debug)
            time.sleep(seconds_to_wait)
        except Exception as e:
            logMessage(f"[Sell Scanner Error] {e}")
        time.sleep(1)  # avoid busy-looping
