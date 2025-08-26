from models.option import OptionContract
from models.cache_manager import IgnoreTickerCache,BoughtTickerCache
from strategy.buy import OptionBuyStrategy
from strategy.sentiment import SectorSentimentStrategy
from services.etrade_consumer import EtradeConsumer
from services.alerts import send_alert
from services.scanner_utils import get_active_tickers
from queue import Queue
from services.utils import AddMessage 

buy_strategies = {
    "Primary": [    
        OptionBuyStrategy(),
        ],
    "Secondary": [
        SectorSentimentStrategy(), 
    ]
}

def run_buy_scan(mode:str,consumer: EtradeConsumer,messageQueue: Queue = None, debug:bool = False):
    try:
        ignore_cache = IgnoreTickerCache()
        bought_cache = BoughtTickerCache()
        tickers = get_active_tickers()
        AddMessage(f"Starting Buy Scanner | Tickers: {len(tickers)}",messageQueue)
        
        successCount = 0
        context = {"exposure": consumer.get_open_exposure()}
        for ticker in tickers:
            try:
                if ignore_cache.is_cached(ticker):
                    continue   
                if bought_cache.is_cached(ticker):
                    continue 
                options,hasOptions = consumer.get_option_chain(ticker)
                if not hasOptions:
                    ignore_cache.add(ticker,"")
                    continue
                    
                for opt_obj in options:
                    opt = OptionContract(**opt_obj)
                    should_buy = True
                    FailureReason = ""
                    for primaryStrategy in buy_strategies.get("Primary"):
                        primStrategySuccess,error = primaryStrategy.should_buy(opt, context)
                        if not primStrategySuccess:
                            should_buy = False
                            if debug:
                                AddMessage(f"{opt.display} fails {primaryStrategy.name} for reason: {error}",messageQueue)
                    if should_buy:
                        FailureReason = ""
                        for secondaryStrategy in buy_strategies.get("Secondary"):
                            secStrategySuccess,error = secondaryStrategy.should_buy(opt, context)
                            if not secStrategySuccess:
                                if FailureReason == "":
                                    FailureReason = f" | Secondary Failure Reason(s): {error}"
                                else: 
                                    FailureReason += f", {error}"
                        if FailureReason != "":
                            continue 
                        successCount += 1
                        msg = f"BUY: {ticker} → {opt.display}/Ask: {opt.ask*100}{FailureReason}"
                        
                        #Only send cheap ones to text
                        if (opt.ask * 100 < 50):
                            send_alert(msg)

            except Exception as e:
                AddMessage(f"[Scanner-buy-error] {ticker}: {e}",messageQueue)
        AddMessage("Buy Scanner Completed",messageQueue)
    except Exception as e:
        AddMessage(f"Error in Buy Scanner: {e}", messageQueue)
            