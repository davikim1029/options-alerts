from datetime import datetime, time as dt_time
from services.logging.logger_singleton import logger
from services.scanner.sell_scanner import run_sell_scan
from services.scanner.scanner_utils import wait_interruptible

# Default values
DEFAULT_START_TIME = dt_time(9,0)
DEFAULT_END_TIME = dt_time(17,0)
DEFAULT_COOLDOWN_SECONDS = 3600

def sell_loop(stop_event, **kwargs):
    consumer = kwargs.get("consumer")
    caches = kwargs.get("caches")
    debug = kwargs.get("debug", False)

    logger.logMessage("[Sell Scanner] Module loaded/reloaded")

    while not stop_event.is_set():
        # Read dynamic values from kwargs
        start_time = kwargs.get("start_time") or DEFAULT_START_TIME
        end_time   = kwargs.get("end_time")   or DEFAULT_END_TIME
        cooldown   = kwargs.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS
        force_first_run = kwargs.get("force_first_run") or False

        now = datetime.now().time()
        if start_time <= now <= end_time or force_first_run:
            try:
                run_sell_scan(stop_event=stop_event, consumer=consumer, caches=caches,seconds_to_wait=cooldown, debug=debug)
            except Exception as e:
                logger.logMessage(f"[Sell Scanner Error] {e}")

            # Reset force_first_run after first execution
            kwargs["force_first_run"] = False

            wait_interruptible(stop_event, cooldown)
        else:
            wait_interruptible(stop_event, 30)
