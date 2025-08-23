import json
import os
from datetime import datetime,timedelta,timezone
from threading import Thread
import time

IGNORE_CACHE_FILE = "cache/ignore_tickers.json"
IGNORE_CACHE_TTL_DAYS = 30
IGNORE_CACHE_SAVE_INTERVAL_SECONDS = 60

class IgnoreTickerCache:
      
    def __init__(self):
        self._cache = {}
        self._load_cache()
        self._start_autosave()
        
        
    def _load_cache(self):
        if os.path.exists(IGNORE_CACHE_FILE):
            try:
                with open(IGNORE_CACHE_FILE, "r") as f:
                    raw = json.load(f)
                    now = datetime.now(timezone.utc)
                    for ticker, timestamp in raw.items():
                        ts = datetime.fromisoformat(timestamp)
                        if now - ts < timedelta(days=IGNORE_CACHE_TTL_DAYS):
                            self._cache[ticker] = ts
            except json.JSONDecodeError:
                raw = {}   # fallback if file is empty or corrupted
            except Exception as e:
                print(f"[IgnoreCache] failed to load cache: {e}")
        else:
            with open(IGNORE_CACHE_FILE, "w") as f:
                json.dump({}, f)  # initialize with empty dict
                
    def _save_cache(self):
        try:
            with open(IGNORE_CACHE_FILE, "w") as f:
                json.dump({k: v.isoformat() for k, v in self._cache.items()}, f, indent=2)
        except Exception as e:
            print(f"[IgnoreCache] failed to save cache: {e}")
    
    def _start_autosave(self):
        def save_loop():
            while True:
                time.sleep(IGNORE_CACHE_SAVE_INTERVAL_SECONDS)
                self._save_cache()
        thread = Thread(target=save_loop, daemon=True)
        thread.start()
        
    def should_ignore(self,ticker:str) -> bool:
        ts = self._cache.get(ticker)
        if ts and datetime.now(timezone.utc) - ts < timedelta(days=IGNORE_CACHE_TTL_DAYS):
            return True
        if ts:
            #expired entry
            del self._cache[ticker]
        return False
    
    def mark(self, ticker:str):
        self._cache[ticker] = datetime.now(timezone.utc)
    
    def clear(self):
        self._cache.clear()
        self._save_cache()
                    
  
BOUGHT_CACHE_FILE = "cache/bought_tickers.json"
class BoughtTickerCache:
    def __init__(self):
        self._cache = set()
        self._load_cache()

    def _load_cache(self):
        # Ensure directory exists
        os.makedirs(os.path.dirname(BOUGHT_CACHE_FILE), exist_ok=True)

        if os.path.exists(BOUGHT_CACHE_FILE):
            try:
                with open(BOUGHT_CACHE_FILE, "r") as f:
                    raw_list = json.load(f)
                    # Convert list to set
                    self._cache = set(raw_list)
            except json.JSONDecodeError:
                # Fallback if file is empty or corrupted
                self._cache = set()
            except Exception as e:
                print(f"[BoughtTicker] failed to load cache: {e}")
        else:
            # Initialize empty file
            with open(BOUGHT_CACHE_FILE, "w") as f:
                json.dump([], f)

    def should_skip(self, ticker: str) -> bool:
        return ticker in self._cache  # O(1) lookup

    def mark(self, ticker: str):
        """Add ticker to cache and persist to disk."""
        self._cache.add(ticker)
        self._save_cache()

    def _save_cache(self):
        try:
            with open(BOUGHT_CACHE_FILE, "w") as f:
                # Convert set to list for JSON serialization
                json.dump(list(self._cache), f, indent=2)
        except Exception as e:
            print(f"[BoughtTicker] failed to save cache: {e}")