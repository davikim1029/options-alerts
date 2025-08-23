# scanner.py
from services.buy_scanner import run_buy_scan
from services.etrade_consumer import EtradeConsumer
from services.sell_scanner import run_sell_scan
from datetime import datetime,timedelta,timezone
from threading import Thread
import queue
import time

input_processor_queue = queue.Queue()
user_input_queue = queue.Queue()
error_queue = queue.Queue()



BUY_INTERVAL_SECONDS = 300
SELL_INTERVAL_SECONDS = 300


def run_scan(mode:str, consumer:EtradeConsumer,debug:bool = False):
    
    # Start worker to listen for input
    Thread(target=input_listener, daemon=True).start()

    # Start worker to handle the input
    Thread(target=input_processor, daemon=True).start()
    
    try:
        buy_thread = _start_buy_loop(mode=mode,consumer=consumer,debug=debug)
    except Exception as e:
        print(f"[Scanner-buy-error] {e}")

    # SELL check loop
    try:
        sell_thread = _start_sell_loop(mode=mode,consumer=consumer,debug=debug)
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
    




def _start_buy_loop(mode:str,consumer:EtradeConsumer, debug:bool = False):
    def buy_loop():
        while True:
            run_buy_scan(mode=mode,consumer=consumer,messageQueue=error_queue, debug=debug)
            time.sleep(BUY_INTERVAL_SECONDS)
    thread = Thread(target=buy_loop, daemon=True)
    thread.start()
    return thread
    
def _start_sell_loop(mode:str,consumer:EtradeConsumer, debug:bool = False):
    def sell_loop():
        while True:
            run_sell_scan(mode=mode,consumer=consumer, messageQueue=error_queue,debug = debug)
            time.sleep(SELL_INTERVAL_SECONDS)
    thread = Thread(target=sell_loop, daemon=True)
    thread.start()
    return thread
    
    

def input_listener():
    while True:
        cmd = input()
        user_input_queue.put(cmd)

def input_processor():
    while True:
        cmd = user_input_queue.get()   # blocks until something is put
        if cmd != None:
            input_processor_queue.put("exit")