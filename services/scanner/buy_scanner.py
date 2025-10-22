# services/scanner/buy_scanner.py
import threading
import queue
from datetime import datetime, timezone
from dataclasses import dataclass
from services.logging.logger_singleton import getLogger
from services.scanner.scanner_utils import get_active_tickers
from services.alerts import send_alert
from strategy.buy import OptionBuyStrategy
from services.token_status import TokenStatus
from services.scanner.YFinanceFetcher import YFTooManyAttempts
from services.etrade_consumer import TokenExpiredError, NoOptionsError, NoExpiryError, InvalidSymbolError
from services.core.cache_manager import (
    LastTickerCache,
    IgnoreTickerCache,
    BoughtTickerCache,
    EvalCache,
    TickerMetadata,
    TickerCache,
    RateLimitCache
)
from services.utils import is_json, write_scratch, get_job_count
import json
import re

# new: sentiment aggregator import
from services.news_aggregator import get_sentiment_signal
from strategy.FinMA7BLocal import FinMA7BLocal,get_finma_model

print("[Main] Preloading FinMA model before threads start...")
logger = getLogger()

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
processed_counter_opts = 0
total_iterated = 0

token_status = TokenStatus()
print("[Buy Scanner] Module loaded/reloaded")  # hot reload indicator


def _reset_globals():
    global counter_lock, api_worker_lock
    global total_tickers, remaining_ticker_count, processed_counter, processed_counter_opts, total_iterated
    counter_lock = threading.Lock()
    api_worker_lock = threading.Lock()
    total_tickers = 0
    remaining_ticker_count = 0
    processed_counter = 0
    processed_counter_opts = 0
    total_iterated = 0


_reset_globals()


# ------------------------- Analysis logic -------------------------
def analyze_ticker(ticker, options, context, buy_strategy, caches, config, debug=False):
    logger = getLogger()
    eval_result, metadata, buy_alerts = {}, {}, []

    last_ticker_cache = getattr(caches, "last_seen", None) or LastTickerCache()
    eval_cache = getattr(caches, "eval", None) or EvalCache()
    ticker_cache = getattr(caches, "ticker", None) or TickerCache()
    ticker_metadata_cache = getattr(caches, "ticker_metadata", None) or TickerMetadata()
    rate_cache = getattr(caches, "rate", None)

    ticker_name = ticker_cache.get(ticker) or ""

    # -------------------------
    # Precompute sentiment (once per ticker) and stash in context
    # -------------------------
    sentiment_signal = None
    try:
        # If news cache exists and has cached sentiment, prefer it
        news_cache = getattr(caches, "news", None)
        headline_cache = getattr(caches, "headlines", None)
        if news_cache is not None:
            try:
                if news_cache.is_cached(ticker):
                    cached = news_cache.get(ticker)
                    if isinstance(cached, dict) and "avg_sentiment" in cached:
                        sentiment_signal = cached.get("avg_sentiment")
            except Exception:
                sentiment_signal = None

        # If not found in cache, call aggregator
        if sentiment_signal is None:
            sentiment_signal = get_sentiment_signal(ticker, ticker_name, rate_cache=rate_cache,headline_cache=headline_cache)

            # if aggregator returned None -> upstream rate-limited; set to None to indicate backoff
            if sentiment_signal is None:
                logger.logMessage(f"[Buy Scanner] Sentiment upstream rate-limited for {ticker}; will skip live sentiment")
            else:
                # store in news cache for reuse (best-effort)
                try:
                    if news_cache is not None:
                        news_cache.add(ticker, {"avg_sentiment": sentiment_signal, "fetched_at": datetime.now().timestamp()})
                except Exception:
                    pass
    except Exception as e:
        logger.logMessage(f"[Buy Scanner] Sentiment precompute failed for {ticker}: {e}")
        sentiment_signal = None

    # use a copy of context so we don't mutate caller context
    local_context = context.copy() if context else {}
    local_context["sentiment_signal"] = sentiment_signal

    processed_osi_keys = set()
    eval_keys = []

    for opt in options:
        should_buy, osi_key = True, getattr(opt, "osiKey", None)
        processed_osi_keys.add(osi_key)
        disp = getattr(opt, "displaySymbol", "").split(" ")
        eval_key = f"{disp[0]} - {' '.join(disp[1:])}" if disp else str(getattr(opt, "displaySymbol", opt))
        eval_keys.append(eval_key)

        # Don't reprocess if we've already processed this recently
        try:
            if eval_cache.is_cached(eval_key):
                continue
        except Exception:
            # if cache errors, proceed to evaluate anyway
            pass

        eval_result = {}
        primary_score = 0

        # Single unified primary strategy evaluation
        try:
            success, message, score = buy_strategy.should_buy(opt,caches, local_context)
            eval_result[("PrimaryStrategy", buy_strategy.name, "Result")] = success
            eval_result[("PrimaryStrategy", buy_strategy.name, "Message")] = message
            eval_result[("PrimaryStrategy", buy_strategy.name, "Score")] = score
            if not success:
                should_buy = False
            else:
                try:
                    if score != "N/A":
                        primary_score += float(score)
                except Exception:
                    pass
        except Exception as e:
            should_buy = False
            eval_result[(buy_strategy.name, buy_strategy.name, "Result")] = False
            eval_result[(buy_strategy.name, buy_strategy.name, "Message")] = str(e)
            eval_result[("PrimaryStrategy", buy_strategy.name, "Score")] = "N/A"

        with counter_lock:
            global processed_counter_opts
            processed_counter_opts += 1
            if processed_counter_opts % 2000 == 0:
                logger.logMessage(
                    f"[Buy Scanner] Thread {threading.current_thread().name} | Processed {processed_counter_opts} options."
                )

        if not should_buy:
            # Save result and continue
            if eval_cache:
                try:
                    eval_cache.add(eval_key, eval_result)
                except Exception:
                    pass
            continue

        # If strategy passed (True), create alert and store result
        if should_buy:
            try:
                # Regex patterns for the three fields
                score_match = re.search(r'Score=\d+(?:\.\d+)?', message)
                hold_match = re.search(r'(HoldDays=\d+)', message)
                rationale_match = re.search(r'(Rationale:\s*[^|]+)', message)
                source_match = re.search(r'(Source:\s*[^|]+)', message)

                # Combine found fields
                parts = [m.group(0) for m in [score_match, hold_match, rationale_match, source_match] if m]
                parsed = " | ".join(parts)
                msg = f"Buy: {getattr(opt, 'displaySymbol', '?')}/Ask: {getattr(opt, 'ask', -1) * 100} | {parsed}"
                send_alert(msg)
                buy_alerts.append(msg)
            except Exception as e:
                logger.logMessage(f"[Buy Scanner] send_alert failed: {e}")

        if eval_cache:
            try:
                eval_cache.add(eval_key, eval_result)
            except Exception:
                pass

    with counter_lock:
        global processed_counter
        processed_counter += 1
        if processed_counter % 5 == 0 and last_ticker_cache:
            last_ticker_cache.add("lastSeen", ticker)
        if processed_counter % 250 == 0 or total_iterated == remaining_ticker_count:
            logger.logMessage(
                f"[Buy Scanner] Thread {threading.current_thread().name} | Processed {processed_counter} tickers. {remaining_ticker_count - total_iterated} Remaining"
            )

    strikes_seen = [getattr(o, "strikePrice", 0) for o in options]
    expirations_seen = [
        f"{getattr(o.product, 'expiryYear')}-{getattr(o.product, 'expiryMonth')}-{getattr(o.product, 'expiryDay')}"
        for o in options
    ]

    metadata = {
        "eval_keys": eval_keys,
        "min_strike": min(strikes_seen, default=None),
        "max_strike": max(strikes_seen, default=None),
        "expirations": expirations_seen,
        "seen_options": list(processed_osi_keys),
        "last_checked": datetime.now().astimezone().isoformat(),
    }

    try:
        ticker_metadata_cache.add(ticker, metadata)
    except Exception:
        pass

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

    # Build single primary strategy instance (unified)
    buy_strategy = OptionBuyStrategy()

    tickers_map = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers_map)
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
    ignore_skipped = bankrupt_skipped = bought_skipped = eval_skipped = 0

    for ticker in remaining_tickers:
        if ticker.upper().endswith("Q"):   # Q Suffix means bankrupt
            bankrupt_skipped += 1
            continue
        if ignore_cache.is_cached(ticker):
            ignore_skipped += 1
            continue
        if bought_cache.is_cached(ticker):
            bought_skipped += 1
            continue
        filtered_tickers.append(ticker)

    logger.logMessage(f"{bankrupt_skipped} tickers skipped due to bankruptcy")
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
    num_api_threads = int(max(4, get_job_count()))
    num_analysis_threads = int(max(1, get_job_count()))
    api_semaphore_limit = int(scanner_cfg.get("api_semaphore", 8))

    fetch_q, result_q = queue.Queue(), queue.Queue()
    api_semaphore = threading.Semaphore(api_semaphore_limit)

    def api_worker(stop_evt, ignore_cache=None):
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
                    options = consumer.get_option_chain(ticker)
                    result_q.put((ticker, options))
                except TimeoutError as e:
                    fetch_q.put(ticker)
                except NoExpiryError as e:
                    error = "No expiry found"
                    if hasattr(e, "args") and len(e.args) > 0:
                        e_data = e.args[0]
                        if is_json(e_data):
                            e_data = json.loads(e_data)
                            if hasattr(e_data, "Error"):
                                error = str(e_data["Error"])
                            else:
                                error = str(e_data)
                        else:
                            error = str(e_data)
                    else:
                        error = str(e)
                    if ignore_cache is not None:
                        ignore_cache.add(ticker, error)
                except InvalidSymbolError as e:
                    error = "Invalid Symbol found"
                    if hasattr(e, "args") and len(e.args) > 0:
                        e_data = e.args[0]
                        if is_json(e_data):
                            e_data = json.loads(e_data)
                            if hasattr(e_data, "Error"):
                                error = str(e_data["Error"])
                            else:
                                error_obj = e_data.get("Error")
                                if error_obj is not None:
                                    code = error_obj.get("code")
                                    message = error_obj.get("message")
                                    error = f"Code {code}: {message}"
                                else:
                                    error = str(e_data)
                        else:
                            error = str(e_data)
                    else:
                        error = str(e)
                    if ignore_cache is not None:
                        ignore_cache.add(ticker, error)
                except NoOptionsError as e:
                    error = "No options found"
                    if hasattr(e, "args") and len(e.args) > 0:
                        e_data = e.args[0]
                        if is_json(e_data):
                            e_data = json.loads(e_data)
                            if hasattr(e_data, "Error"):
                                error = str(e_data["Error"])
                            else:
                                error_obj = e_data.get("Error")
                                if error_obj is not None:
                                    code = error_obj.get("code")
                                    message = error_obj.get("message")
                                    error = f"Code {code}: {message}"
                                else:
                                    error = str(e_data)
                        else:
                            error = str(e_data)
                    else:
                        error = str(e)
                    if ignore_cache is not None:
                        ignore_cache.add(ticker, error)
                except TokenExpiredError as e:
                    logger.logMessage("[Buy Scanner] TokenExpiredError in api_worker.")
                    send_alert("E*TRADE token expired. Please re-authenticate.")
                    token_status.wait_until_valid(check_interval=30)
                    consumer.load_tokens(generate_new_token=False)
                    fetch_q.put(ticker)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] Error fetching options for {ticker}: {e}")
                    result_q.put((ticker, None))
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
            ticker, options = item
            global total_iterated
            total_iterated += 1
            if options is not None:
                try:
                    analyze_ticker(ticker, options, context, buy_strategy, caches, {}, debug)
                except YFTooManyAttempts as e:
                    fetch_q.put(ticker)
                except Exception as e:
                    logger.logMessage(f"[Buy Scanner] analyze_ticker {ticker} error: {e}")
            else:
                logger.logMessage(f"Ticker {ticker} has no options found but was not caught as an exception")
                write_scratch(f"Ticker {ticker} has no options found but was not caught as an exception")
            result_q.task_done()
        logger.logMessage(f"[Buy Scanner] Analysis worker {threading.current_thread().name} exiting")

    # Start workers
    api_threads = [threading.Thread(target=api_worker, args=(stop_event, None), name=f"Buy Fetch Thread {i}", daemon=True) for i in range(num_api_threads)]
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
            try:
                fetch_q.get_nowait(); fetch_q.task_done()
            except queue.Empty:
                break
        while not result_q.empty():
            try:
                result_q.get_nowait(); result_q.task_done()
            except queue.Empty:
                break

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
        try:
            last_ticker_cache.clear()
        except Exception:
            pass

    #Save off cache for future analysis
    eval_cache = getattr(caches, "eval", None)
    if eval_cache is not None:
        try:
            eval_cache.copy_cache_to_file()
        except Exception:
            pass

    logger.logMessage("[Buy Scanner] Run complete")
