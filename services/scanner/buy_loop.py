#buy_loop.py
from datetime import datetime, timedelta, time as dt_time
from services.logging.logger_singleton import getLogger
from services.scanner.buy_scanner import run_buy_scan
from services.scanner.scanner_utils import wait_interruptible
from services.alerts import send_alert
from services.token_status import TokenStatus
from services.etrade_consumer import TokenExpiredError
import holidays


# Default values for initial load; will be overridden by kwargs if present
DEFAULT_START_TIME = dt_time(0,1)
DEFAULT_END_TIME = dt_time(23,59)
DEFAULT_COOLDOWN_SECONDS = 60  # 60 seconds, give the scanner enoung time to drop and reset caches

token_status = TokenStatus()
us_holidays = holidays.US(subdiv='NYSE')

_running = False 
def buy_loop(**kwargs):
    stop_event = kwargs.get("stop_event")
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
            start_time = kwargs.get("start_time") or DEFAULT_START_TIME
            end_time   = kwargs.get("end_time")   or DEFAULT_END_TIME
            cooldown   = kwargs.get("cooldown_seconds") or DEFAULT_COOLDOWN_SECONDS
            force_first_run = kwargs.get("force_first_run") or False

            now = datetime.now().time()
            if (
                now_dt.weekday() < 5                             # Mon–Fri
                and now_dt.date() not in us_holidays             # Not a holiday
                and (start_time <= now <= end_time or force_first_run)  # During market hours or first run
            ):                
                try:
                    run_buy_scan(stop_event=stop_event, consumer=consumer, caches=caches, debug=debug)
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
                logger.logMessage("[Buy Loop] Waiting")
                wait_interruptible(stop_event, cooldown)
                logger.logMessage("[Buy Loop] Wait interrupted")

            else:
                now_dt = datetime.now()
                today_start = datetime.combine(now_dt.date(), start_time)

                # Figure out next possible start time
                if now_dt.time() < start_time:
                    # Before market opens today — try today
                    next_start = today_start
                else:
                    # After market closes — try tomorrow
                    next_start = today_start + timedelta(days=1)

                # Skip weekends and holidays
                while next_start.weekday() >= 5 or next_start.date() in us_holidays:
                    next_start += timedelta(days=1)

                # Compute wait time
                seconds_until_start = (next_start - now_dt).total_seconds()
                wait_time = max(0.1, int(seconds_until_start))  # safe fallback

                # For logging clarity
                hours, remainder = divmod(wait_time, 3600)
                minutes, seconds = divmod(remainder, 60)

                if hours > 0:
                    wait_str = f"{hours}h {minutes}m"
                elif minutes > 0:
                    wait_str = f"{minutes}m {seconds}s"
                else:
                    wait_str = f"{seconds}s"

                logger.logMessage(
                    f"[Option Loop] Outside of time schedule, waiting {wait_str} until next market open at {next_start.strftime('%Y-%m-%d %H:%M')}"
                )

                wait_interruptible(stop_event, wait_time)
        logger.logMessage("Buy loop interrupted. Exiting")
    finally:
        _running = False
