#buy_loop.py
from datetime import datetime, time as dt_time
from services.logging.logger_singleton import getLogger
from services.scanner.buy_scanner import run_buy_scan
from services.scanner.scanner_utils import wait_interruptible
from services.alerts import send_alert
from services.token_status import TokenStatus
from services.etrade_consumer import TokenExpiredError


# Default values for initial load; will be overridden by kwargs if present
START_TIME = dt_time(8,30)
END_TIME = dt_time(17,30)
COOLDOWN_SECONDS = 300  # 5 minutes

token_status = TokenStatus()

_running = False 
def buy_loop(stop_event, **kwargs):
    consumer = kwargs.get("consumer")
    caches = kwargs.get("caches")
    debug = kwargs.get("debug", False)
    logger = getLogger()
    
    global _running
    if _running:
        logger.logMessage("[Buy Loop] buy_loop already running, skipping")  
        
    _running = True  
    
    try:
        logger.logMessage("[Buy Loop] Module loaded/reloaded")

        while not stop_event.is_set():
            # Read dynamic values from kwargs
            start_time = kwargs.get("start_time") or START_TIME
            end_time   = kwargs.get("end_time")   or END_TIME
            cooldown   = kwargs.get("cooldown_seconds") or COOLDOWN_SECONDS
            force_first_run = kwargs.get("force_first_run") or False

            now = datetime.now().time()
            if start_time <= now <= end_time or force_first_run:
                try:
                    run_buy_scan(stop_event=stop_event, consumer=consumer,seconds_to_wait=cooldown, caches=caches, debug=debug)
                except TokenExpiredError:
                    logger.logMessage("[Buy Loop] Token expired, pausing scanner.")
                    send_alert("E*TRADE token expired. Please re-authenticate.")
                    token_status.wait_until_valid(check_interval=30)
                    consumer.load_tokens(generate_new_token=False)
                    logger.logMessage("[Buy Loop] Token restored, resuming scan.")
                except Exception as e:
                    logger.logMessage(f"[Buy Loop Error] {e}")

                # Reset force_first_run after first execution
                kwargs["force_first_run"] = False

                wait_interruptible(stop_event, cooldown)
            else:
                logger.logMessage("[Buy Loop] Outside of time schedule, waiting")
                wait_interruptible(stop_event, 30)
    finally:
        _running = False