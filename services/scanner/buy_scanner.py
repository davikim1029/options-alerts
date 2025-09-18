# services/scanner/buy_scanner.py
import threading
import queue
from datetime import datetime, timezone
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from services.logging.logger_singleton import getLogger
from services.scanner.scanner_utils import get_active_tickers
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


# ------------------------- Generic parallel runner -------------------------
def run_parallel(fn, items, max_workers=8, stop_event=None, collect_errors=True):
    results, errors = [], []
    lock = threading.Lock()
    logger = getLogger()

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
                logger.logMessage(f"[run_parallel] {e}")
                if collect_errors:
                    errors.append((futures[fut], e))
                else:
                    raise
    return results, errors


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
def analyze_ticker(ticker, options, context, buy_strategies, caches, config, debug=False):
    logger = getLogger()
    eval_result, metadata, buy_alerts = {}, {}, []
            
    last_ticker_cache = getattr(caches, "last_seen", None) or LastTickerCache()
    eval_cache = getattr(caches, "eval", None) or EvalCache()
    ticker_metadata_cache = getattr(caches, "ticker_metadata", None) or TickerMetadata()

    processed_osi_keys = set()
    for opt in options:
        should_buy, osi_key = True, getattr(opt, "osiKey", None)
        processed_osi_keys.add(osi_key)

        # Primary strategies
        for primary in buy_strategies["Primary"]:
            try:
                success, error,score = primary.should_buy(opt, context)
                eval_result[("PrimaryStrategy", primary.name, "Result")] = success
                eval_result[("PrimaryStrategy", primary.name, "Message")] = error
                eval_result[("PrimaryStrategy", primary.name, "Score")] = score
                if not success:
                    should_buy = False
            except Exception as e:
                should_buy = False
                eval_result[(primary.name, primary.name, "Result")] = False
                eval_result[(primary.name, primary.name, "Message")] = str(e)
                eval_result[("PrimaryStrategy", primary.name, "Score")] = "N/A"

        if not should_buy:
            eval_result[("SecondaryStrategy","N/A", "Result")] = False
            eval_result[("SecondaryStrategy","N/A", "Message")] = "Primary Strategy did not pass, secondary not evaluated"
            eval_result[("SecondaryStrategy", "N/A", "Score")] = "N/A"
            continue

        # Secondary strategies
        secondary_failure = ""
        for secondary in buy_strategies["Secondary"]:
            try:
                success, error, score = secondary.should_buy(opt, context)
                eval_result[("SecondaryStrategy", secondary.name, "Result")] = success
                eval_result[("SecondaryStrategy", secondary.name, "Message")] = error if not success else "Passed"
                eval_result[("SecondaryStrategy", secondary.name, "Score")] = score
                if not success:
                    secondary_failure += f" | {error}"
            except Exception as e:
                eval_result[("SecondaryStrategy",secondary.name, "Result")] = False
                eval_result[("SecondaryStrategy",secondary.name, "Message")] = str(e)
                eval_result[("SecondaryStrategy", secondary.name, "Score")] = "N/A"

        if secondary_failure:
            continue

        try:
            msg = f"[Buy Scanner] BUY: {ticker} -> {getattr(opt, 'displaySymbol', '?')}/Ask: {getattr(opt, 'ask', -1) * 100}"
            send_alert(msg)
            buy_alerts.append(msg)
        except Exception as e:
            logger.logMessage(f"[Buy Scanner] send_alert failed: {e}")

    with counter_lock:
        global processed_counter
        processed_counter += 1
        if processed_counter % 5 == 0 and last_ticker_cache:
            last_ticker_cache.add("lastSeen", ticker)
        if processed_counter % 250 == 0 or total_iterated == remaining_ticker_count:
            logger.logMessage(
                f"[Buy Scanner] Thread {threading.current_thread().name} | Processed {processed_counter}. {remaining_ticker_count - total_iterated} Remaining"
            )

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
        "last_checked": datetime.now().astimezone().isoformat(),
    }

    if eval_cache:
        eval_cache.add(ticker, eval_result)
    ticker_metadata_cache.add(ticker, metadata)
    return TickerResult(ticker, eval_result, metadata, buy_alerts)


# ------------------------- Post-processing (stub) -------------------------
def post_process_results(results, caches, stop_event=None):
    getLogger().logMessage("[Buy Scanner] Running post_process_results (stub).")


# ------------------------- Main scanner entrypoint -------------------------
def run_buy_scan(stop_event, consumer=None, caches=None, debug=False):
    logger = getLogger()
    logger.logMessage("[Buy Scanner] Starting run_buy_scan")
    _reset_globals()

    # Config
    news_cache = getattr(caches, "news", None)
    rate_cache = getattr(caches, "rate", None)
    ticker_cache = getattr(caches, "ticker", None)
    ignore_cache = getattr(caches, "ignore", None) or IgnoreTickerCache()
    bought_cache = getattr(caches, "bought", None) or BoughtTickerCache()
    eval_cache = getattr(caches, "eval", None) or EvalCache()
    last_ticker_cache = getattr(caches, "last_seen", None)

    buy_strategies = {
        "Primary": [OptionBuyStrategy()],
        "Secondary": [SectorSentimentStrategy(news_cache=news_cache, rate_cache=rate_cache)],
    }

    tickers_map = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers_map.keys())
    if not ticker_keys:
        logger.logMessage("[Buy Scanner] No tickers to process.")
        return

    start_index = 0
    last_seen = last_ticker_cache.get("lastSeen") if last_ticker_cache else None
    if last_seen and last_seen in ticker_keys:
        start_index = ticker_keys.index(last_seen) + 1
    if start_index >= len(ticker_keys) - 1:
        start_index = 0

    remaining_tickers = ticker_keys[start_index:]
    filtered_tickers = []
    ignore_skipped = bought_skipped = eval_skipped = 0

    for ticker in remaining_tickers:
        if ignore_cache.is_cached(ticker):
            ignore_skipped+=1
            continue
        if bought_cache.is_cached(ticker):
            bought_skipped+=1
            continue
        if eval_cache.is_cached(ticker):
            eval_skipped+=1
            continue
        filtered_tickers.append(ticker)
        
    logger.logMessage(f"{ignore_skipped} tickers skipped based on Ignore Cache")
    logger.logMessage(f"{bought_skipped} tickers skipped based on Bought Cache")
    logger.logMessage(f"{eval_skipped} tickers skipped based on Evaluation Cache")
        
    global total_tickers, remaining_ticker_count
    total_tickers = remaining_ticker_count = len(filtered_tickers)

    logger.logMessage(f"[Buy Scanner] {start_index} tickers processed earlier. {remaining_ticker_count} remaining.")

    context = {"consumer": consumer}
    try:
        context["exposure"] = consumer.get_open_exposure()
    except TokenExpiredError:
        logger.logMessage("[Buy Scanner] Token expired gathering exposure, pausing scanner.")
        send_alert("E*TRADE token expired. Please re-authenticate.")
        token_status.wait_until_valid(check_interval=30)
        consumer.load_tokens(generate_new_token=False)
        context["exposure"] = consumer.get_open_exposure()
    except Exception as e:
        logger.logMessage(f"[Buy Scanner] Error getting open exposure: {e}")

    # Threading config
    scanner_cfg = getattr(caches, "scanner_config", {}) or {}
    num_api_threads = int(scanner_cfg.get("api_threads", 4))
    num_analysis_threads = int(scanner_cfg.get("analysis_threads", max(2, num_api_threads)))
    api_semaphore_limit = int(scanner_cfg.get("api_semaphore", 4))

    fetch_q, result_q = queue.Queue(), queue.Queue()
    api_semaphore = threading.Semaphore(api_semaphore_limit)

    def api_worker(stop_evt):
        logger.logMessage(f"[Buy Scanner] API worker {threading.current_thread().name} started")
        while not stop_evt.is_set():
            try:
                ticker = fetch_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if ticker is None:
                fetch_q.task_done()
                break
            with api_semaphore:
                try:
                    options, has_options,error = consumer.get_option_chain(ticker)
                    result_q.put((ticker, options, bool(has_options),error))
                except TokenExpiredError:
                    logger.logMessage("[Buy Scanner] TokenExpiredError in api_worker.")
                    send_alert("E*TRADE token expired. Please re-authenticate.")
                    token_status.wait_until_valid(check_interval=30)
                    consumer.load_tokens(generate_new_token=False)
                    fetch_q.put(ticker)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] Error fetching {ticker}: {e}")
                    result_q.put((ticker, None, False, e))
                finally:
                    fetch_q.task_done()
        logger.logMessage(f"[Buy Scanner] API worker {threading.current_thread().name} exiting")

    def analysis_worker(stop_evt):
        logger.logMessage(f"[Buy Scanner] Analysis worker {threading.current_thread().name} started")
        while not stop_evt.is_set():
            try:
                item = result_q.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                result_q.task_done()
                break
            ticker, options, has_options,error = item
            global total_iterated
            total_iterated += 1
            if has_options and options:
                try:
                    analyze_ticker(ticker, options, context, buy_strategies, caches, {}, debug)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] analyze_ticker {ticker} error: {e}")
            else:
                (getattr(caches, "ignore", None) or IgnoreTickerCache()).add(ticker, error)
            result_q.task_done()
        logger.logMessage(f"[Buy Scanner] Analysis worker {threading.current_thread().name} exiting")

    # Start workers
    api_threads = [threading.Thread(target=api_worker, args=(stop_event,), name=f"Buy Fetch Thread {i}", daemon=True) for i in range(num_api_threads)]
    for t in api_threads: t.start()
    analysis_threads = [threading.Thread(target=analysis_worker, args=(stop_event,), name=f"Buy Analysis Thread {i}", daemon=True) for i in range(num_analysis_threads)]
    for t in analysis_threads: t.start()

    # Feed tickers
    for t in filtered_tickers:
        fetch_q.put(t)

    # Instead of blocking forever on join, poll with stop_event
    
    while not stop_event.is_set():
        if fetch_q.unfinished_tasks == 0 and result_q.unfinished_tasks == 0:
            break
        try:
            # short sleep lets workers process without busy-waiting
            stop_event.wait(0.5)
        except KeyboardInterrupt:
            stop_event.set()
            break

    # If stop_event was triggered, flush queues to let workers exit
    if stop_event.is_set():
        while not fetch_q.empty():
            try: fetch_q.get_nowait(); fetch_q.task_done()
            except queue.Empty: break
        while not result_q.empty():
            try: result_q.get_nowait(); result_q.task_done()
            except queue.Empty: break

    # Stop workers gracefully
    for _ in api_threads: fetch_q.put(None)
    for _ in analysis_threads: result_q.put(None)

    for t in api_threads + analysis_threads:
        t.join(timeout=2)

    try:
        post_process_results([], caches, stop_event)
    except Exception as e:
        logger.logMessage(f"[Buy Scanner] post_process_results error: {e}")

    #If we've iterated over every ticker,  clear the last_ticker cache 
    if total_iterated == remaining_ticker_count:
        last_ticker_cache.clear()
    
    #Save off cache for future analysis
    eval_cache = getattr(caches, "eval", None)
    if eval_cache is not None:
        eval_cache.copy_cache_to_file()
        
    logger.logMessage("[Buy Scanner] Run complete")
