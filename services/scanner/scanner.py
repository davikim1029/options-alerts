# scanner.py
from services.scanner.buy_scanner import run_buy_scan
from services.etrade_consumer import EtradeConsumer
from services.core.cache_manager import IgnoreTickerCache,BoughtTickerCache,NewsApiCache,RateLimitCache,EvalCache,TickerCache,LastTickerCache
from services.scanner.sell_scanner import run_sell_scan
from services.threading.api_worker import ApiWorker
from services.utils import logMessage
from services.threading.thread_manager import ThreadManager
from services.core.shutdown_handler import ShutdownManager
from services.utils import logMessage
import queue
import threading
stop_event = threading.Event()


input_processor_queue = queue.Queue()
user_input_queue = queue.Queue()
error_queue = queue.Queue()


BUY_INTERVAL_SECONDS = 300
SELL_INTERVAL_SECONDS = 300*6 #300 secs is 5 mins


def run_scan(mode:str, consumer:EtradeConsumer,debug:bool = False):
    manager = ThreadManager.instance()
    news_cache = NewsApiCache()
    rate_cache = RateLimitCache()
    api_worker = ApiWorker(consumer.session, min_interval=2)
    

    ShutdownManager.init(error_logger=logMessage)

    # Tell shutdown manager to set stop_event
    ShutdownManager.register(lambda reason=None: stop_event.set())    
    
    caches = [news_cache, rate_cache]
    for cache in caches:
        ShutdownManager.register(lambda reason=None, c=cache: c._save_cache())
    
    manager.register(api_worker._worker, "HTTP Worker")
    consumer.apiWorker = api_worker    
    # Register workers instead of starting them
    manager.register(input_listener, "Input Listener Thread")
    manager.register(input_processor, "Input Processor Thread")
    manager.register(news_cache.autosave_loop, "NewsAPI Cache Autosave")
    manager.register(rate_cache.autosave_loop, "RateLimit Cache Autosave")
    _start_buy_loop(mode, consumer, news_cache, rate_cache, debug)
    _start_sell_loop(mode, consumer, news_cache, rate_cache, debug)

    # Manager now handles lifecycle
    manager.manage()




def _start_buy_loop(mode:str, consumer:EtradeConsumer, news_cache: NewsApiCache = None, rate_cache: RateLimitCache = None, debug: bool = False):
    manager = ThreadManager.instance()
    manager.register(
        buy_loop,
        "Buy Scanner",
        mode,
        consumer,
        news_cache,
        rate_cache,
    )    
    
def buy_loop(stop_event, mode, consumer, news_cache, rate_cache):
    ignore_cache = IgnoreTickerCache()
    bought_cache = BoughtTickerCache()
    eval_cache = EvalCache()
    ticker_cache = TickerCache()
    last_ticker_cache = LastTickerCache()
    
    caches = [ignore_cache, bought_cache, eval_cache, ticker_cache, last_ticker_cache]
    for cache in caches:
        ShutdownManager.register(lambda reason=None, c=cache: c._save_cache())
    
    last_seen = None
    last_ticker_cache._load_cache()
    if not last_ticker_cache.is_empty():
        last_seen = last_ticker_cache.get("lastSeen")
    
    # Register their autosave loops
    manager = ThreadManager.instance()
    manager.register(ignore_cache.autosave_loop, "Ignore Cache Autosave")
    manager.register(bought_cache.autosave_loop, "Bought Cache Autosave")
    manager.register(eval_cache.autosave_loop, "Eval Cache Autosave")
    manager.register(ticker_cache.autosave_loop, "Ticker Cache Autosave")
    manager.register(last_ticker_cache.autosave_loop, "Last Ticker Cache Autosave")


    while not stop_event.is_set():
        run_buy_scan(
            stop_event=stop_event,
            consumer=consumer,
            ignore_cache=ignore_cache,
            bought_cache=bought_cache,
            news_cache=news_cache,
            rate_cache=rate_cache,
            eval_cache=eval_cache,
            ticker_cache=ticker_cache,
            last_ticker_cache = last_ticker_cache,
            last_seen = last_seen,
            seconds_to_wait=BUY_INTERVAL_SECONDS,
        )
        
        #If we've completed the loop, clear last_seen
        last_seen = None
        
        stop_event.wait(BUY_INTERVAL_SECONDS)

    
def _start_sell_loop(mode: str,
                     consumer: EtradeConsumer,
                     news_cache: NewsApiCache = None,
                     rate_cache: RateLimitCache = None,
                     debug: bool = False):
    manager = ThreadManager.instance()
    # Register the sell_loop with all required arguments
    manager.register(sell_loop, "Sell Scanner", mode, consumer, news_cache, rate_cache, debug)


def sell_loop(stop_event, mode, consumer, news_cache, rate_cache, debug):
    while not stop_event.is_set():
        run_sell_scan(
            mode=mode,
            consumer=consumer,
            news_cache=news_cache,
            rate_cache=rate_cache,
            seconds_to_wait=SELL_INTERVAL_SECONDS,
            debug=debug
        )
        stop_event.wait(SELL_INTERVAL_SECONDS)  # graceful wait that respects stop_event

    

def input_listener(stop_event):
    while not stop_event.is_set():
        try:
            cmd = input()
            user_input_queue.put(cmd)
        except EOFError:
            break


def input_processor(stop_event):
    while not stop_event.is_set():
        try:
            cmd = user_input_queue.get()   # blocks until something is put
            if cmd.lower() == "exit":
                input_processor_queue.put("exit")
        except EOFError:
            break
