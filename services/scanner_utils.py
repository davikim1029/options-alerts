# scanner_utils.py

import yfinance as yf
import time
import os
import json
from models.option import OptionContract
from models.tickers import fetch_us_tickers_from_finnhub


#Ensure Cache exists
CACHE_DIR = "data/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

################################ TICKER CACHE ####################################

def get_active_tickers():
    cache = load_cache("tickers.json")
    if cache and time.time() - cache.get("timestamp", 0) < 86400:
        return cache["tickers"]
    
    tickers = []
    tickers = fetch_us_tickers_from_finnhub()
    save_cache("tickers.json", {"timestamp": time.time(), "tickers": tickers})
    return tickers

def load_cache(name):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    else:
        with open(path, "w") as f:
            json.dump({}, f)  # initialize with empty dict
    return {}

def save_cache(name, data):
    path = os.path.join(CACHE_DIR, name)
    with open(path, "w") as f:
        json.dump(data, f)


################################ POSITION CACHE ####################################

def add_to_positions(ticker,opt,position_dictionary):
    position_dictionary[ticker] = opt
    return 
    
def load_positions(name):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                rawData = json.load(f)
            return {k: OptionContract.from_dict(v) for k, v in rawData.items()}
        except:
            with open(path, "w") as f:
                json.dump({}, f)  # initialize with empty dict
            
    else:
        with open(path, "w") as f:
            json.dump({}, f)  # initialize with empty dict
        
    return {}

def save_positions(name,data):
    path = os.path.join(CACHE_DIR, name)
    try:
        with open(path, "w") as f:
            json.dump({k: v.to_dict() for k, v in data.items()}, f, indent=2)
    except Exception as e:
        print(f"[Positions Cache] failed to save positions: {e}")

        
def get_positions():
    positions = load_positions("activePositions.json")
    return positions