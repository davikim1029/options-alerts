# scanner_utils.py

import yfinance as yf
import time
import os
import json
from models.option import OptionContract
from models.tickers import fetch_us_tickers_from_finnhub
from models.cache_manager import TickerCache
from datetime import datetime, timedelta, time



################################ TICKER CACHE ####################################

def get_active_tickers():
    ticker_cache = TickerCache()
    ticker_cache._load_cache()
    if ticker_cache.is_empty():
        tickers = fetch_us_tickers_from_finnhub()
    else:
        tickers = ticker_cache.get("tickers")
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

