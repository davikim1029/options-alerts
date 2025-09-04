# services/scanner/sell_scanner.py
import time
from typing import Optional, List
from services.logging.logger_singleton import logger
from services.scanner.scanner_utils import get_next_run_date
from services.alerts import send_alert
from models.generated.Position import Position
from strategy.sell import OptionSellStrategy
from strategy.sentiment import SectorSentimentStrategy
from services.etrade_consumer import EtradeConsumer
from services.core.cache_manager import Caches

# Top-level print to confirm hot reload
print(f"[Sell Scanner] Module loaded/reloaded at {time.time()}")

def run_sell_scan(
    stop_event,
    consumer: EtradeConsumer,
    caches: Caches,
    seconds_to_wait: int = 0,
    debug: bool = False
):
    """Hot-reload safe sell scan."""
    ignore_cache = caches.ignore
    bought_cache = caches.bought
    news_cache = caches.news
    rate_cache = caches.rate
    eval_cache = caches.eval
    last_ticker_cache = caches.last_seen

    sell_strategies = {
        "Primary": [OptionSellStrategy()],
        "Secondary": [SectorSentimentStrategy(news_cache=news_cache, rate_cache=rate_cache)]
    }

    try:
        positions: Optional[List[Position]] = consumer.get_positions()

        if not positions:
            logger.logMessage("[Sell Scanner] No positions to evaluate.")
            return

        logger.logMessage(f"[Sell Scanner] Starting | Open Positions: {len(positions)}")

        for pos in positions:
            if stop_event.is_set():
                if last_ticker_cache:
                    last_ticker_cache._save_cache()
                logger.logMessage("[Sell Scanner] Stopping early due to stop_event")
                return

            try:
                should_sell = True
                eval_result = {}

                # Primary strategies
                for primary in sell_strategies["Primary"]:
                    success, error = primary.should_sell(pos)
                    eval_result[(primary.name, "Primary", "Result")] = success
                    eval_result[(primary.name, "Primary", "Message")] = error if not success else "Passed"
                    if not success:
                        should_sell = False
                        if debug:
                            logger.logMessage(f"[Sell Scanner] {pos.Product['symbol']} fails {primary.name}: {error}")

                # Secondary strategies
                if should_sell:
                    secondary_failure = ""
                    for secondary in sell_strategies["Secondary"]:
                        success, error = secondary.should_sell(pos)
                        eval_result[(secondary.name, "Secondary", "Result")] = success
                        eval_result[(secondary.name, "Secondary", "Message")] = error if not success else "Passed"
                        if not success:
                            if secondary_failure:
                                secondary_failure += f", {error}"
                            else:
                                secondary_failure = f" | Secondary Failure Reason(s): {error}"

                    # Build alert message
                    gainPct = pos.totalGainPct
                    gain = pos.totalGain
                    msg = f"SELL: {pos.Product['symbol']} → {pos.symbolDescription} | Gain: {gain}/Gain Pct: {gainPct}{secondary_failure}"

                    # Send alert
                    send_alert(msg)


                # Store evaluation in cache if needed
                #if eval_cache:
                #    eval_cache.add(pos.Product['symbol'], eval_result)

            except Exception as e:
                logger.logMessage(f"[Sell Scanner Error] {pos.Product['symbol']}: {e}")

        logger.logMessage(f"[Sell Scanner] Completed. Next run: {get_next_run_date(seconds_to_wait)}")

    except Exception as e:
        logger.logMessage(f"[Sell Scanner] Fatal error: {e}")
