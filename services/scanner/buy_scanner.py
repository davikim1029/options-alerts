# services/scanner/buy_scanner.py
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from services.logging.logger_singleton import logger
from services.scanner.scanner_utils import get_active_tickers, get_next_run_date
from services.alerts import send_alert
from strategy.buy import OptionBuyStrategy
from strategy.sentiment import SectorSentimentStrategy
from services.token_status import TokenStatus
from services.etrade_consumer import TokenExpiredError

# ------------------------- Global counters -------------------------
counter_lock = threading.Lock()
total_tickers = 0
processed_counter = 0

# Global lock for safe ApiWorker access
api_worker_lock = threading.Lock()
print("[Buy Scanner] Module loaded/reloaded")  # Hot reload indicator

def safe_get_option_chain(consumer, ticker):
    """
    Wrap ApiWorker calls to avoid timeouts from concurrent threads.
    """
    with api_worker_lock:
        options, has_options = consumer.get_option_chain(ticker)
    return options, has_options

# ------------------------- Helpers -------------------------

class _DictCacheFallback:
    """Fallback in-memory cache if ticker_metadata cache is missing."""
    def __init__(self):
        self._d = {}
    def get(self, key, default=None):
        return self._d.get(key, default)
    def add(self, key, value):
        self._d[key] = value
    def is_cached(self, key):
        return key in self._d
    def clear(self):
        self._d.clear()
    def _save_cache(self):
        return

def _should_keep_option(opt, underlying_guess, config):
    """Contract-level pruning: volume, ask, strike range."""
    try:
        vol = getattr(opt, "volume", None)
        if vol is None or vol < config.get("min_volume", 50):
            return False

        ask = getattr(opt, "ask", None)
        if ask is None or ask * 100 < config.get("min_ask_cents", 5) or ask * 100 > config.get("max_ask_cents", 50):
            return False

        strike = getattr(opt, "strikePrice", None)
        if strike is None:
            return False
        if underlying_guess is not None and not (underlying_guess * 0.8 <= strike <= underlying_guess * 1.2):
            return False

        return True
    except Exception:
        return False

# ------------------------- Per-ticker worker -------------------------

def _process_ticker_incremental(ticker, context, buy_strategies, caches, config, debug=False):
    ignore_cache = getattr(caches, "ignore", None)
    bought_cache = getattr(caches, "bought", None)
    eval_cache = getattr(caches, "eval", None)
    ticker_metadata_cache = getattr(caches, "ticker_metadata", None)
    if ticker_metadata_cache is None:
        if not hasattr(_process_ticker_incremental, "_fallback_cache"):
            _process_ticker_incremental._fallback_cache = _DictCacheFallback()
        ticker_metadata_cache = _process_ticker_incremental._fallback_cache

    if ignore_cache and ignore_cache.is_cached(ticker):
        return
    if bought_cache and bought_cache.is_cached(ticker):
        return
    if eval_cache and eval_cache.is_cached(ticker):
        return

    # ------------------------- Thread-safe progress tracking -------------------------
    global processed_counter
    with counter_lock:
        processed_counter += 1
        if processed_counter % 200 == 0 or processed_counter == total_tickers:
            logger.logMessage(f"[Buy Scanner] Completed {processed_counter}/{total_tickers} tickers")

    # ----------------------- Cached metadata -----------------------
    meta = ticker_metadata_cache.get(ticker, {})
    min_strike_cached = meta.get("min_strike")
    max_strike_cached = meta.get("max_strike")
    expirations_cached = set(meta.get("expirations", []))
    seen_options = set(meta.get("seen_options", []))

    try:
        options, hasOptions = safe_get_option_chain(config["consumer"], ticker)
        if not hasOptions or not options:
            if ignore_cache:
                ignore_cache.add(ticker, "")
            return
    except Exception as e:
        if debug:
            logger.logMessage(f"[Buy Scanner] Error fetching options for {ticker}: {e}")
        return

    # Estimate ATM
    underlying_guess = None
    sorted_options = sorted(options, key=lambda o: abs((o.lastPrice or 0) - getattr(o, "strikePrice", 0)))
    if sorted_options:
        underlying_guess = sorted_options[0].strikePrice

    # ----------------------- Incremental filtering -----------------------
    new_options = []
    for opt in options:
        strike = getattr(opt, "strikePrice", None)
        expiry = getattr(opt.product, "expiryDay", None)
        osi_key = getattr(opt, "osiKey", None)
        if expiry is None or strike is None or osi_key is None:
            continue

        expiry_str = f"{getattr(opt.product, 'expiryYear')}-{getattr(opt.product, 'expiryMonth')}-{getattr(opt.product, 'expiryDay')}"
        if strike >= (min_strike_cached or 0) and strike <= (max_strike_cached or 0) and expiry_str in expirations_cached and osi_key in seen_options:
            continue

        if _should_keep_option(opt, underlying_guess, config):
            new_options.append(opt)

    if not new_options:
        return

    # ----------------------- Evaluate new options -----------------------
    processed_osi_keys = set()
    for opt in new_options:
        should_buy = True
        eval_result = {}
        osi_key = getattr(opt, "osiKey", None)

        for primary in buy_strategies["Primary"]:
            success, error = primary.should_buy(opt, context)
            key = ("PrimaryStrategy", primary.name)
            eval_result[(key[0], key[1], "Result")] = success
            eval_result[(key[0], key[1], "Message")] = error if not success else "Passed"
            if not success and debug:
                logger.logMessage(f"[Buy Scanner] {getattr(opt, 'displaySymbol', '?')} fails {primary.name}: {error}")
            should_buy = should_buy and success

        if should_buy:
            secondary_failure = ""
            for secondary in buy_strategies["Secondary"]:
                success, error = secondary.should_buy(opt, context)
                key = ("SecondaryStrategy", secondary.name)
                eval_result[(key[0], key[1], "Result")] = success
                eval_result[(key[0], key[1], "Message")] = error if not success else "Passed"
                if not success:
                    secondary_failure = f" | Secondary Failure: {error}"
            if secondary_failure:
                continue

            try:
                if getattr(opt, "ask", 99999) * 100 < 50:
                    msg = f"[Buy Scanner] BUY: {ticker} → {getattr(opt, 'displaySymbol', '?')}/Ask: {opt.ask*100}{secondary_failure}"
                    send_alert(msg)
            except Exception:
                pass
        else:
            eval_result[("SecondaryStrategy", "N/A", "Result")] = False
            eval_result[("SecondaryStrategy", "N/A", "Message")] = "Skipped due to primary failure"

        if eval_cache:
            eval_cache.add(ticker, eval_result)
        processed_osi_keys.add(osi_key)

    # ----------------------- Update ticker metadata -----------------------
    strikes_seen = [getattr(o, "strikePrice", 0) for o in new_options]
    expirations_seen = [f"{getattr(o.product, 'expiryYear')}-{getattr(o.product, 'expiryMonth')}-{getattr(o.product, 'expiryDay')}" for o in new_options]

    ticker_metadata_cache.add(ticker, {
        "min_strike": min(strikes_seen + [min_strike_cached] if min_strike_cached else strikes_seen),
        "max_strike": max(strikes_seen + [max_strike_cached] if max_strike_cached else strikes_seen),
        "expirations": list(set(expirations_cached).union(expirations_seen)),
        "seen_options": list(seen_options.union(processed_osi_keys)),
        "last_checked": datetime.now(timezone.utc).isoformat()
    })

# ------------------------- Main scanner -------------------------

def run_buy_scan(stop_event, consumer=None, caches=None, seconds_to_wait=0, debug=False):
    logger.logMessage("[Buy Scanner] Starting run_buy_scan")
    token_status = TokenStatus()

    ignore_cache = getattr(caches, "ignore", None)
    bought_cache = getattr(caches, "bought", None)
    news_cache = getattr(caches, "news", None)
    rate_cache = getattr(caches, "rate", None)
    eval_cache = getattr(caches, "eval", None)
    ticker_cache = getattr(caches, "ticker", None)
    last_ticker_cache = getattr(caches, "last_seen", None)

    buy_strategies = {
        "Primary": [OptionBuyStrategy()],
        "Secondary": [SectorSentimentStrategy(news_cache=news_cache, rate_cache=rate_cache)]
    }

    tickers = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers.keys())
    global total_tickers
    total_tickers = len(ticker_keys)
    start_index = 0
    last_seen = last_ticker_cache.get("lastSeen") if last_ticker_cache else None
    if last_seen and last_seen in ticker_keys:
        start_index = ticker_keys.index(last_seen) + 1

    logger.logMessage(f"[Buy Scanner] Processing tickers {start_index} to {len(ticker_keys)}")

    context = {"exposure": consumer.get_open_exposure(), "consumer": consumer}
    scanner_config = getattr(caches, "scanner_config", {}) or {}
    config = {
        "min_volume": scanner_config.get("min_volume", 50),
        "min_ask_cents": scanner_config.get("min_ask_cents", 5),
        "max_ask_cents": scanner_config.get("max_ask_cents", 50),
        "consumer":consumer
    }

    counter = 0
    parallel = scanner_config.get("parallel", True)
    max_workers = scanner_config.get("max_workers", 8)

    try:
        if parallel:
            futures = {}
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for idx, ticker in enumerate(ticker_keys[start_index:], start=start_index):
                    if stop_event.is_set():
                        break
                    counter += 1
                    if counter % 5 == 0 and last_ticker_cache:
                        last_ticker_cache.add("lastSeen", ticker)
                    futures[executor.submit(_process_ticker_incremental, ticker, context, buy_strategies, caches, config, debug)] = ticker
                for fut in as_completed(futures):
                    if stop_event.is_set():
                        break
                    try:
                        fut.result()
                    except TokenExpiredError:
                        logger.logMessage("[Buy Scanner] Token expired → pausing scanner.")
                        send_alert("⚠️ E*TRADE token expired. Please re-authenticate.")
                        token_status.wait_until_valid(check_interval=30)
                        consumer.load_tokens(generate_new_token=False)
                        logger.logMessage("[Buy Scanner] Token restored → resuming scan.")
                    except Exception as e:
                        t = futures.get(fut, "?")
                        logger.logMessage(f"[Buy Scanner Error] {t}: {e}")
        else:
            for idx, ticker in enumerate(ticker_keys[start_index:], start=start_index):
                if stop_event.is_set():
                    if last_ticker_cache:
                        last_ticker_cache._save_cache()
                    logger.logMessage("[Buy Scanner] Stopped early due to stop_event")
                    return

                if last_ticker_cache and idx % 5 == 0:
                    last_ticker_cache.add("lastSeen", ticker)

                _process_ticker_incremental(ticker, context, buy_strategies, caches, config, debug)

    except Exception as e:
        logger.logMessage(f"[Buy Scanner] Unexpected error in run loop: {e}")

    logger.logMessage(f"[Buy Scanner] Completed run. Next run: {get_next_run_date(seconds_to_wait)}")
    if last_ticker_cache:
        last_ticker_cache.clear()
        last_ticker_cache._save_cache()
