# buy_scanner.py
import time
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from services.logging.logger_singleton import getLogger
from services.scanner.scanner_utils import get_active_tickers, get_next_run_date
from services.alerts import send_alert
from strategy.buy import OptionBuyStrategy
from strategy.sentiment import SectorSentimentStrategy
from services.token_status import TokenStatus
from services.etrade_consumer import TokenExpiredError
from services.core.cache_manager import (
    LastTickerCache,
    IgnoreTickerCache,
    BoughtTickerCache,
    EvalCache,
    TickerMetadata,
)

# ------------------------- Generic parallel runner -------------------------
def run_parallel(fn, items, max_workers=8, stop_event=None, collect_errors=True):
    results = []
    errors = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fn, item): item for item in items}

        for fut in as_completed(futures):
            if stop_event and stop_event.is_set():
                break
            try:
                res = fut.result()
                if res is not None:
                    with lock:
                        results.append(res)
            except Exception as e:
                logger = getLogger()
                logger.logMessage(e)
                if collect_errors:
                    errors.append((futures[fut], e))
                else:
                    raise

    return results, errors


# ------------------------- Result container -------------------------
@dataclass
class TickerResult:
    ticker: str
    eval_result: dict
    metadata: dict
    buy_alerts: list


# ------------------------- Globals -------------------------
counter_lock = threading.Lock()
api_worker_lock = threading.Lock()
total_tickers = 0
remaining_ticker_count = 0
processed_counter = 0
total_iterated = 0

token_status = TokenStatus()
print("[Buy Scanner] Module loaded/reloaded")  # hot reload indicator


def _reset_globals():
    global counter_lock, api_worker_lock
    global total_tickers, remaining_ticker_count, processed_counter, total_iterated

    counter_lock = threading.Lock()
    api_worker_lock = threading.Lock()
    total_tickers = 0
    remaining_ticker_count = 0
    processed_counter = 0
    total_iterated = 0


_reset_globals()


# ------------------------- Safe option chain wrapper -------------------------
def safe_get_option_chain(consumer, ticker):
    logger = getLogger()
    try:
        with api_worker_lock:
            options, has_options = consumer.get_option_chain(ticker)
        return options, has_options
    except TokenExpiredError:
        logger.logMessage("[Buy Scanner] Token expired, pausing scanner.")
        send_alert("E*TRADE token expired. Please re-authenticate.")
        token_status.wait_until_valid(check_interval=30)
        consumer.load_tokens(generate_new_token=False)
        logger.logMessage("[Buy Scanner] Token restored, resuming scan.")


# ------------------------- Analysis logic -------------------------
def analyze_ticker(ticker, context, buy_strategies, caches, config, debug=False):
    logger = getLogger()
    eval_result = {}
    metadata = {}
    buy_alerts = []
    
    global total_iterated, processed_counter
    total_iterated += 1
    
    with counter_lock:
        if (total_iterated % 5):
            logger.flush()
    ignore_cache = getattr(caches, "ignore", None) or IgnoreTickerCache()
    bought_cache = getattr(caches, "bought", None) or BoughtTickerCache()
    last_ticker_cache = getattr(caches, "last_seen", None) or LastTickerCache()
    
    eval_cache = getattr(caches, "eval", None) or EvalCache()
    ticker_metadata_cache = getattr(caches, "ticker_metadata",None) or TickerMetadata()

    if ignore_cache and ignore_cache.is_cached(ticker):
        return
    if bought_cache and bought_cache.is_cached(ticker):
        return
    if eval_cache and eval_cache.is_cached(ticker):
        return

    try:
        options, hasOptions = safe_get_option_chain(config["consumer"], ticker)
        if not hasOptions or not options:
            ignore_cache.add(ticker, "")
            return None
    except Exception as e:
        if debug:
            logger.logMessage(f"[Buy Scanner] Error fetching options for {ticker}: {e}")
        return None

    processed_osi_keys = set()
    for opt in options:
        should_buy = True
        osi_key = getattr(opt, "osiKey", None)
        processed_osi_keys.add(osi_key)
        # Primary strategies
        for primary in buy_strategies["Primary"]:
            try:
                success, error = primary.should_buy(opt, context) 
                key = ("PrimaryStrategy", primary.name) 
                eval_result[(key[0], key[1], "Result")] = success 
                eval_result[(key[0], key[1], "Message")] = error if not success else "Passed" 
                if not success and debug: 
                    logger.logMessage(f"[Buy Scanner] {getattr(opt, 'displaySymbol', '?')} fails {primary.name}: {error}") 
                    should_buy = False 
            except Exception as e: 
                should_buy = False 
                success = False 
                eval_result[(key[0], key[1], "Result")] = False 
                eval_result[(key[0], key[1], "Message")] = e 
                logger.logMessage(f"[Buy Scanner] - Failed to evaluate primary buy strategy(s) for reason: {e}")

        # Secondary strategies
        if should_buy:
            secondary_failure = ""
            for secondary in buy_strategies["Secondary"]:
                try: 
                    success, error = secondary.should_buy(opt, context) 
                    key = ("SecondaryStrategy", secondary.name) 
                    eval_result[(key[0], key[1], "Result")] = success 
                    eval_result[(key[0], key[1], "Message")] = error if not success else "Passed" 
                    if not success: 
                        if secondary_failure == "":
                            secondary_failure = f" | Secondary Failure: {error}" 
                        else:
                            secondary_failure = f"{secondary_failure} / {error}"
                except Exception as e: 
                    should_buy = False 
                    success = False 
                    eval_result[(key[0], key[1], "Result")] = False 
                    eval_result[(key[0], key[1], "Message")] = e 
                    logger.logMessage(f"[Buy Scanner] - Failed to evaluate secondary buy strategy(s) for reason: {e}") 
        
        if secondary_failure != "": 
            continue
        
        msg = f"[Buy Scanner] BUY: {ticker} -> {getattr(opt, 'displaySymbol', '?')}/Ask: {opt.ask*100}"
        send_alert(msg)
        buy_alerts.append(msg)
        
    with counter_lock:
        processed_counter += 1
        if processed_counter % 5 == 0 and last_ticker_cache: 
            last_ticker_cache.add("lastSeen", ticker)
        
        if processed_counter % 250 == 0 or processed_counter == remaining_ticker_count:
            thread_name = threading.current_thread().name.split("_")[1]
            logger.logMessage(
                f"[Buy Scanner] Thread {thread_name} | "
                f"Processed {processed_counter}. "
                f"{remaining_ticker_count - total_iterated} tickers remaining"
                )

    # Build metadata
    strikes_seen = [getattr(o, "strikePrice", 0) for o in options]
    expirations_seen = [
        f"{getattr(o.product, 'expiryYear')}-{getattr(o.product, 'expiryMonth')}-{getattr(o.product, 'expiryDay')}"
        for o in options
    ]

    metadata = {
        "min_strike": min(strikes_seen, default=None),
        "max_strike": max(strikes_seen, default=None),
        "expirations": expirations_seen,
        "seen_options": list(processed_osi_keys),
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    if eval_cache:
        eval_cache.add(ticker, eval_result)
    ticker_metadata_cache.add(ticker, metadata)

    return TickerResult(ticker, eval_result, metadata, buy_alerts)


# ------------------------- Thread worker wrapper -------------------------
def _process_ticker_incremental(ticker, context, buy_strategies, caches, config, stop_event=None, debug=False):
    if stop_event and stop_event.is_set():
        return None

    return analyze_ticker(ticker, context, buy_strategies, caches, config, debug)


# ------------------------- Post-processing -------------------------
def post_process_results(results, caches, stop_event=None):
    logger = getLogger()
    logger.logMessage("We've hit post processing")


# ------------------------- Main scanner -------------------------
def run_buy_scan(stop_event, consumer=None, caches=None, seconds_to_wait=0, debug=False):
    logger = getLogger()
    logger.logMessage("[Buy Scanner] Starting run_buy_scan")
    _reset_globals()
    
    news_cache = getattr(caches, "news", None)
    rate_cache = getattr(caches, "rate", None)
    ticker_cache = getattr(caches, "ticker", None)
    last_ticker_cache = getattr(caches, "last_seen", None)

    buy_strategies = {
        "Primary": [OptionBuyStrategy()],
        "Secondary": [
            SectorSentimentStrategy(
                news_cache=getattr(caches, "news", None),
                rate_cache=getattr(caches, "rate", None),
            )
        ],
    }

    tickers = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers.keys())
    global total_tickers
    total_tickers = len(ticker_keys)
    start_index = 0
    last_seen = last_ticker_cache.get("lastSeen") if last_ticker_cache else None
    if last_seen and last_seen in ticker_keys:
        start_index = ticker_keys.index(last_seen) + 1
    if start_index >= len(ticker_keys)-1:
        start_index = 0

    global remaining_ticker_count
    remaining_ticker_count = total_tickers - (start_index)
    remaining_tickers = ticker_keys[start_index:]
    
    logger.logMessage(f"[Buy Scanner] {start_index+1} tickers processed. {total_tickers - start_index} remaining.")

    context = {"exposure": consumer.get_open_exposure(), "consumer": consumer}
    config = {
        "consumer": consumer,
        "min_volume": getattr(caches, "scanner_config", {}).get("min_volume", 50),
    }

    process_fn = lambda t: _process_ticker_incremental(t, context, buy_strategies, caches, config, stop_event, debug)

    parallel = getattr(caches, "scanner_config", {}).get("parallel", True)
    max_workers = getattr(caches, "scanner_config", {}).get("max_workers", 8)

    results, errors = ([], [])
    try:
        if parallel:
            results, errors = run_parallel(process_fn, remaining_tickers, max_workers=max_workers, stop_event=stop_event)
        else:
            for t in tickers:
                if stop_event.is_set():
                    break
                r = process_fn(t)
                if r:
                    results.append(r)

        post_process_results(results, caches, stop_event)

    except Exception as e:
        logger.logMessage(f"[Buy Scanner] Unexpected error in run loop: {e}")

    if stop_event.is_set():
        logger.logMessage(f"[Buy Scanner] Run stopped due to stop flag")
    else:
        logger.logMessage(f"[Buy Scanner] Completed run. Next run: {get_next_run_date(seconds_to_wait)}")
