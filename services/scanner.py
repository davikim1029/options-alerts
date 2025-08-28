# scanner.py
from services.buy_scanner import run_buy_scan
from services.etrade_consumer import EtradeConsumer
from models.cache_manager import IgnoreTickerCache,BoughtTickerCache,NewsApiCache,RateLimitCache,EvalCache
from services.sell_scanner import run_sell_scan
from services.api_worker import ApiWorker
from threading import Thread
import queue
import time


input_processor_queue = queue.Queue()
user_input_queue = queue.Queue()
error_queue = queue.Queue()


BUY_INTERVAL_SECONDS = 300
SELL_INTERVAL_SECONDS = 300*6 #300 secs is 5 mins


def run_scan(mode:str, consumer:EtradeConsumer,debug:bool = False):
        
    news_cache = NewsApiCache()
    rate_cache = RateLimitCache()
    api_worker = ApiWorker(consumer.session,2)
    consumer.apiWorker = api_worker
    
    # Start worker to listen for input
    Thread(name="Input Listener Thread",target=input_listener, daemon=True).start()

    # Start worker to handle the input
    Thread(name="Input Processor Thread" ,target=input_processor, daemon=True).start()
    
    try:
        buy_thread = _start_buy_loop(mode=mode,consumer=consumer,news_cache=news_cache,rate_cache = rate_cache,debug=debug)
    except Exception as e:
        print(f"[Scanner-buy-error] {e}")

    # SELL check loop
    try:
        sell_thread = _start_sell_loop(mode=mode,consumer=consumer, news_cache=news_cache,rate_cache = rate_cache,debug=debug)
    except Exception as e:
        print(f"[Scanner-sell-error] {e}")
        
    while True:
        try:
            item = input_processor_queue.get(block=False)  # immediately raises queue.Empty if nothing is there
            break
        except queue.Empty:
            if not buy_thread.is_alive():
                print("Buy thread is no longer alive")
            if not sell_thread.is_alive():
                print("Sell thread is no longer alive")
        try:
            msg = error_queue.get(block=False)
            print(msg)
        except queue.Empty:
            pass #move on
        
        time.sleep(10) #Wait 10 seconds before checking again
    




def _start_buy_loop(mode:str,consumer:EtradeConsumer, news_cache: NewsApiCache = None,rate_cache:RateLimitCache = None, debug:bool = False):
    ignore_cache = IgnoreTickerCache()
    bought_cache = BoughtTickerCache()
    eval_cache = EvalCache()
    
    if news_cache is None:
        news_cache = NewsApiCache()
        
    if rate_cache is None:
        rate_cache = RateLimitCache()
        
    def buy_loop():
        while True:
            run_buy_scan(mode=mode,consumer=consumer,ignore_cache=ignore_cache,bought_cache=bought_cache,news_cache=news_cache,rate_cache=rate_cache, eval_cache=eval_cache,messageQueue=error_queue,seconds_to_wait=BUY_INTERVAL_SECONDS, debug=debug)
            time.sleep(BUY_INTERVAL_SECONDS)
    thread = Thread(name="Buy Scanner",target=buy_loop, daemon=True)
    thread.start()
    return thread
    
def _start_sell_loop(mode:str,consumer:EtradeConsumer,news_cache: NewsApiCache = None,rate_cache:RateLimitCache = None, debug:bool = False):
    
    if news_cache is None:
        news_cache = NewsApiCache()
        
    if rate_cache is None:
        rate_cache = RateLimitCache()
    
    def sell_loop():
        while True:
            run_sell_scan(mode=mode,consumer=consumer, news_cache=news_cache,rate_cache=rate_cache, messageQueue=error_queue, seconds_to_wait=SELL_INTERVAL_SECONDS,debug = debug)
            time.sleep(SELL_INTERVAL_SECONDS)
    thread = Thread(name="Sell Scanner",target=sell_loop, daemon=True)
    thread.start()
    return thread
    
    

def input_listener():
    while True:
        cmd = input()
        user_input_queue.put(cmd)

def input_processor():
    while True:
        cmd = user_input_queue.get()   # blocks until something is put
        if cmd.lower() == "exit":
            input_processor_queue.put("exit")
