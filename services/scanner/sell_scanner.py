from services.etrade_consumer import EtradeConsumer
from services.alerts import send_alert
from strategy.sentiment import SectorSentimentStrategy
from strategy.sell import  OptionSellStrategy  # assumes dict with Primary/Secondary
from models.generated.Position import Position
from models.generated.Account import PortfolioAccount
from typing import Optional, List
from services.scanner.scanner_utils import get_next_run_date
from services.core.cache_manager import NewsApiCache,RateLimitCache
from services.utils import logMessage

import queue




def run_sell_scan(mode: str, consumer: EtradeConsumer, news_cache:NewsApiCache = None, rate_cache:RateLimitCache = None,seconds_to_wait: int = 0, debug:bool = False) -> None:
    
    sell_strategies = {
        "Primary": [
            OptionSellStrategy(),
        ],
        "Secondary": [
            SectorSentimentStrategy(news_cache = news_cache,rate_cache = rate_cache), 
        ]
    }
    
    try:

        positions:Optional[List[Position]] = consumer.get_positions()

        if not positions:
            logMessage("[Sell Scan] No positions to evaluate.")
            return

        logMessage(f"Starting Sell Scanner | Open Positions: {len(positions)}")
        for pos in positions: 
            try:
                should_sell = True

                # Primary strategies → block if fail
                for primaryStrategy in sell_strategies.get("Primary", []):
                    success, error = primaryStrategy.should_sell(pos)
                    if not success:
                        should_sell = False
                        #AddMessage(f"{pos.symbolDescription} fails {primaryStrategy.name} for reason: {error}",messageQueue)

                if should_sell:
                    # Secondary strategies → add info only
                    failure_reasons = ""
                    for secondaryStrategy in sell_strategies.get("Secondary", []):
                        success, error = secondaryStrategy.should_sell(pos)
                        if not success:
                            if failure_reasons == "":
                                failure_reasons = f" | Secondary Failure Reason(s): {error}"
                            else:
                                failure_reasons += f", {error}"

                    # Build alert message
                    gainPct = pos.totalGainPct
                    gain = pos.totalGain
                    msg = f"SELL: {pos.Product['symbol']} → {pos.symbolDescription} | Gain: {gain}/Gain Pct:{gainPct}{failure_reasons}"

                    # Send alert
                    send_alert(msg)

                    # Simulate/execute trade depending on mode
                    if mode in ("paper", "live"):
                        logMessage(f"[Trade] Execute SELL for {pos.symbolDescription}")
                        # TODO: hook into trade execution here

            except Exception as e:
                logMessage(f"[Sell-Scan-Error] {pos.Product.symbol}: {e}")
        logMessage(f"Sell Scanner Completed. Will start again at {get_next_run_date(seconds_to_wait)}")
    except Exception as e:
        logMessage(f"Error in Sell Scanner: {e}")
