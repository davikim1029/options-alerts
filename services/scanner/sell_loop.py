from datetime import datetime,timedelta, time as dt_time
from services.logging.logger_singleton import getLogger
from services.scanner.sell_scanner import run_sell_scan
from services.scanner.scanner_utils import wait_interruptible
from services.alerts import send_alert
from services.token_status import TokenStatus
from services.etrade_consumer import TokenExpiredError

# Default values
DEFAULT_START_TIME = dt_time(8,30)
DEFAULT_END_TIME = dt_time(17,30)
DEFAULT_COOLDOWN_SECONDS = 3600

token_status = TokenStatus()

_running = False
def sell_loop(stop_event, **kwargs):
    consumer = kwargs.get("consumer")
    caches = kwargs.get("caches")
    debug = kwargs.get("debug", False)
    logger = getLogger()

    global _running
    if _running:
        logger.logMessage("[Sell Loop] buy_loop already running, skipping")  
        
    _running = True  
    try:
        logger.logMessage("[Sell Loop] Module loaded/reloaded")
        while not stop_event.is_set():
            # Read dynamic values from kwargs
            start_time = kwargs.get("start_time") or DEFAULT_START_TIME
            end_time   = kwargs.get("end_time")   or DEFAULT_END_TIME
            cooldown   = kwargs.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS
            force_first_run = kwargs.get("force_first_run") or False

            now = datetime.now().astimezone().time()
            if start_time <= now <= end_time or force_first_run:
                try:
                    run_sell_scan(stop_event=stop_event, consumer=consumer, caches=caches,seconds_to_wait=cooldown, debug=debug)
                    
                except TokenExpiredError:
                    logger.logMessage("[Sell Loop] Token expired, pausing scanner.")
                    send_alert("E*TRADE token expired. Please re-authenticate.")
                    token_status.wait_until_valid(check_interval=30)
                    consumer.load_tokens(generate_new_token=False)
                    logger.logMessage("[Sell Loop] Token restored, resuming scan.")
                except Exception as e:
                    logger.logMessage(f"[Sell Loop Error] {e}")

                # Reset force_first_run after first execution
                kwargs["force_first_run"] = False

                wait_interruptible(stop_event, cooldown)
            else:
                now_dt = datetime.now().astimezone()
                today_start = datetime.combine(now_dt.date(), start_time)

                if now_dt.time() < start_time:
                    # Next start is today
                    next_start = today_start
                else:
                    # Next start is tomorrow
                    next_start = today_start + timedelta(days=1)

                seconds_until_start = (next_start - now_dt).total_seconds()
                wait_time = max(0.1, int(seconds_until_start))  # safe fallback

                # Format nicely for logging
                hours, remainder = divmod(wait_time, 3600)
                minutes, seconds = divmod(remainder, 60)

                if hours > 0:
                    wait_str = f"{hours}h {minutes}m"
                elif minutes > 0:
                    wait_str = f"{minutes}m {seconds}s"
                else:
                    wait_str = f"{seconds}s"

                logger.logMessage(f"[Sell Loop] Outside of time schedule, waiting {wait_str} until next start")

                wait_interruptible(stop_event, wait_time)
    finally:
        _running = False
