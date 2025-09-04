# services/scanner/buy_loop.py
from services.logging.logger_singleton import logger
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
    logger.logMessage("[Buy Scanner] Starting run_buy_scan")

    try:
        # Your main buy scanning logic goes here
        run_buy_scan(stop_event=stop_event, consumer=consumer, caches=caches, debug=debug)
    except Exception as e:
        logger.logMessage(f"[Buy Scanner Error] {e}")
