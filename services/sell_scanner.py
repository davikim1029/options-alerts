from services.etrade_consumer import EtradeConsumer
from services.alerts import send_alert
from strategy.sentiment import SectorSentimentStrategy
from strategy.sell import StopLossStrategy,TakeProfitStrategy,TimeDecayStrategy, OptionSellStrategy  # assumes dict with Primary/Secondary
from models.option import OptionContract  # or HeldOption depending on your structure
from models.generated.Position import Position
from typing import Optional, List
from services.utils import AddMessage 
import queue


sell_strategies = {
    "Primary": [
        OptionSellStrategy(),
        #StopLossStrategy(),
        #TakeProfitStrategy(),
        #TimeDecayStrategy(),
    ],
    "Secondary": [
        SectorSentimentStrategy(), 
    ]
}


def run_sell_scan(mode: str, consumer: EtradeConsumer, messageQueue:queue, debug:bool = False) -> None:
    try:
        """
        Scan current positions and send sell alerts if conditions are met.

        Tiered strategy logic:
        - Primary strategies: block the alert if any fail
        - Secondary strategies: add informational reasons but do not block
        """

        positions:Optional[List[Position]] = consumer.get_positions()

        if not positions:
            AddMessage("[Sell Scan] No positions to evaluate.",messageQueue)
            return

        AddMessage(f"Starting Sell Scanner | Open Positions: {len(positions)}", messageQueue)
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
                    gainPct = pos["totalGainPct"]
                    gain = pos["totalGain"]
                    msg = f"SELL: {pos["Product"]["symbol"]} → {pos["symbolDescription"]} | Gain: {gain}/Gain Pct:{gainPct}{failure_reasons}"

                    # Send alert
                    send_alert(msg)

                    # Simulate/execute trade depending on mode
                    if mode in ("paper", "live"):
                        messageQueue(f"[Trade] Execute SELL for {pos["symbolDescription"]}",messageQueue)
                        # TODO: hook into trade execution here

            except Exception as e:
                AddMessage(f"[Sell-Scan-Error] {pos.Product.symbol}: {e}",messageQueue)
        AddMessage("Sell Scanner Completed",messageQueue)
    except Exception as e:
        AddMessage(f"Error in Sell Scanner: {e}", messageQueue)
