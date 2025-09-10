# scanner_utils.py

import yfinance as yf
import time as pyTime
import os
import json
from models.option import OptionContract
from models.tickers import fetch_us_tickers_from_finnhub
from services.core.cache_manager import TickerCache
from datetime import datetime, timedelta, time


def wait_interruptible(stop_event, seconds):
    """Sleep in small chunks so stop_event can interrupt immediately."""
    end_time = pyTime.time() + seconds
    while pyTime.time() < end_time and not stop_event.is_set():
        pyTime.sleep(0.5)



################################ TICKER CACHE ####################################

def get_active_tickers(ticker_cache:TickerCache = None):
    if ticker_cache is not None:
        ticker_cache._load_cache()
        if ticker_cache.is_empty():
            tickers = fetch_us_tickers_from_finnhub(ticker_cache=ticker_cache)
        else:
            tickers = ticker_cache.get("tickers")
    else:
        tickers = fetch_us_tickers_from_finnhub(ticker_cache=ticker_cache)
    return tickers




def get_next_run_date(seconds_to_wait: int) -> str:
    HALF_DAY = 12 * 60 * 60  # 43,200 seconds

    now = datetime.now()

    # seconds into current 12-hour half (treats 12 as 0)
    seconds_in_half = (now.hour % 12) * 3600 + now.minute * 60 + now.second

    # add, don't multiply
    total = seconds_in_half + seconds_to_wait

    # how many half-days do we roll over, and what's the remainder?
    carry_halves, rem = divmod(total, HALF_DAY)

    # 0 = AM, 1 = PM for the current time
    base_half = 0 if now.hour < 12 else 1
    new_half = (base_half + carry_halves) % 2

    # anchor to midnight for AM, noon for PM
    base = datetime.combine(now.date(), time(0, 0)) if new_half == 0 else \
           datetime.combine(now.date(), time(12, 0))

    new_time = base + timedelta(seconds=rem)
    return new_time.strftime("%I:%M %p")

