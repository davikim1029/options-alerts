# scanner_utils.py

import yfinance as yf
import time
import os
import json
from models.option import OptionContract
from models.tickers import fetch_us_tickers_from_finnhub
from models.cache_manager import TickerCache

################################ TICKER CACHE ####################################

ticker_cache = TickerCache()

def get_active_tickers():
    ticker_cache._load_cache()
    if ticker_cache.is_empty():
        tickers = fetch_us_tickers_from_finnhub()
    else:
        tickers = ticker_cache.get("tickers")
    return tickers


################################ POSITION CACHE ####################################
