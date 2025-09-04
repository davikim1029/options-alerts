# services/scanner/buy_scanner.py
import time
from services.utils import logMessage
from services.scanner.scanner_utils import get_active_tickers, get_next_run_date
from services.alerts import send_alert
from models.generated.Position import Position
from strategy.buy import OptionBuyStrategy
from strategy.sentiment import SectorSentimentStrategy

print("[Buy Scanner] Module loaded/reloaded")  # Hot reload indicator

def run_buy_scan(stop_event, consumer=None, caches=None, seconds_to_wait=0, debug=False):
    """Hot-reloadable buy scan loop."""
    logMessage("[Buy Scanner] Starting run_buy_scan")

    ignore_cache = caches.ignore
    bought_cache = caches.bought
    news_cache = caches.news
    rate_cache = caches.rate
    eval_cache = caches.eval
    ticker_cache = caches.ticker
    last_ticker_cache = caches.last_seen

    buy_strategies = {
        "Primary": [OptionBuyStrategy()],
        "Secondary": [SectorSentimentStrategy(news_cache=news_cache, rate_cache=rate_cache)]
    }

    tickers = get_active_tickers(ticker_cache=ticker_cache)
    ticker_keys = list(tickers.keys())
    start_index = 0
    last_seen = last_ticker_cache.get("lastSeen")
    if last_seen and last_seen in ticker_keys:
        start_index = ticker_keys.index(last_seen) + 1

    logMessage(f"[Buy Scanner] Processing tickers {start_index} to {len(ticker_keys)}")
    context = {"exposure": consumer.get_open_exposure()}

    for idx, ticker in enumerate(ticker_keys[start_index:], start=start_index):
        if stop_event.is_set():
            if last_ticker_cache:
                last_ticker_cache._save_cache()
            logMessage("[Buy Scanner] Stopped early due to stop_event")
            return

        if ignore_cache and ignore_cache.is_cached(ticker):
            continue
        if bought_cache and bought_cache.is_cached(ticker):
            continue
        if eval_cache and eval_cache.is_cached(ticker):
            continue

        try:
            options, hasOptions = consumer.get_option_chain(ticker)
            if not hasOptions:
                if ignore_cache:
                    ignore_cache.add(ticker, "")
                continue

            for opt in options:
                if not isinstance(opt, dict):
                    opt = vars(opt)

                should_buy = True
                eval_result = {}

                # Primary strategy
                for primary in buy_strategies["Primary"]:
                    success, error = primary.should_buy(opt, context)
                    key = ("PrimaryStrategy", primary.name)
                    eval_result[(key[0], key[1], "Result")] = success
                    eval_result[(key[0], key[1], "Message")] = error if not success else "Passed"
                    if not success:
                        should_buy = False
                        if debug:
                            logMessage(f"[Buy Scanner] {opt.display} fails {primary.name}: {error}")

                # Secondary strategies
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

                    if opt.ask * 100 < 50:
                        msg = f"[Buy Scanner] BUY: {ticker} → {opt.display}/Ask: {opt.ask*100}{secondary_failure}"
                        send_alert(msg)

                else:
                    eval_result[("SecondaryStrategy", "N/A", "Result")] = False
                    eval_result[("SecondaryStrategy", "N/A", "Message")] = "Skipped due to primary failure"

                if eval_cache:
                    eval_cache.add(ticker, eval_result)

        except Exception as e:
            logMessage(f"[Buy Scanner Error] {ticker}: {e}")

    logMessage(f"[Buy Scanner] Completed run. Next run: {get_next_run_date(seconds_to_wait)}")
    if last_ticker_cache:
        last_ticker_cache.clear()
        last_ticker_cache._save_cache()
