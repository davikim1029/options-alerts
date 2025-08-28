import json
import os
from datetime import datetime,timedelta,timezone
from threading import Thread, Lock
from services.shutdown_handler import ShutdownManager
from services.utils import logMessage
import time


class CacheManager:
    def __init__(self,
                 CACHE_DISPLAY_NAME:str,
                 CACHE_FILE:str,
                 CACHE_TTL_DAYS:float = None, 
                 CACHE_TTL_HOURS:float = None,
                 CACHE_TTL_MINS:float = None,
                 INTERIM_SAVE_SECONDS:int = 60, 
                 AUTO_SAVE:bool = True):
        self._cache = {}
        
        # Initialize shutdown manager once
        ShutdownManager.init()
        # Register this cache's save method to run on shutdown
        
        ShutdownManager.register(self._save_cache)
        self._display_name:str = CACHE_DISPLAY_NAME
        self._cache_file:str = CACHE_FILE
        self._cache_ttl_days:int = CACHE_TTL_DAYS
        self._cache_ttl_hours:float = CACHE_TTL_HOURS
        self._cache_ttl_mins:float = CACHE_TTL_MINS
        self._interim_save_seconds:int = INTERIM_SAVE_SECONDS
        self._lock = Lock()  # thread-safety lock
        self._load_cache()
        
        if (AUTO_SAVE):
            self._start_autosave()
        
    def _load_cache(self):
        if os.path.exists(self._cache_file):
            try:
                with open(self._cache_file, "r") as f:
                    raw = json.load(f)
                with self._lock:
                    for key, cacheValue in raw.items():
                        ts_str = cacheValue.get("Timestamp")
                        value = cacheValue.get("Value")
                        if ts_str is None:
                            continue
                        ts = datetime.fromisoformat(ts_str)
                        if not self.is_expired(ts):  # ✅ use is_expired instead
                            self._cache[key] = {"Value": value, "Timestamp": ts}
            except json.JSONDecodeError:
                logMessage(f"[{self._display_name}] cache file empty or corrupted, initializing empty cache")
                self._cache = {}
            except Exception as e:
                logMessage(f"[{self._display_name}] failed to load cache: {e}")
        else:
            with open(self._cache_file, "w") as f:
                json.dump({}, f)


    def _save_cache(self):
        try:
            with self._lock:
                # convert timestamps to isoformat for JSON serialization
                serializable_cache = {
                    k: {"Value": v["Value"], "Timestamp": v["Timestamp"].isoformat()}
                    for k, v in self._cache.items()
                }
            # use default=str to handle non-serializable objects
            with open(self._cache_file, "w") as f:
                json.dump(serializable_cache, f, indent=2, default=str)
        except Exception as e:
            logMessage(f"[{self._display_name}] failed to save cache: {e}")

    
    def _start_autosave(self):
        def save_loop():
            while True:
                time.sleep(self._interim_save_seconds)
                self._save_cache()
        thread = Thread(name=f"{self._display_name}_AutoSave", target=save_loop, daemon=True)
        thread.start()
        
    def is_empty(self) -> bool:
        return not bool(self._cache)


        
    def is_cached(self,key:str) -> bool:
        with self._lock:
            cacheValue = self._cache.get(key)
            if cacheValue is not None:
                stale = self.is_expired(cacheValue["Timestamp"])
                if stale:
                    del self._cache[key]
                else:
                    return True
            return False
        
    
    def is_expired(self, timestamp):
        # Default handling
        days = self._cache_ttl_days
        hours = self._cache_ttl_hours
        mins = self._cache_ttl_mins

        if days is None and hours is None and mins is None:
            # Case: no values provided → default to 30 days
            days, hours, mins = 30, 0, 0
        elif (days is not None or hours is not None):
            # Case: days/hours provided
            if days is None:
                days = 0
            if hours is None:
                hours = 0
            if mins is None:
                mins = 0
        else:
            # Case: only mins provided
            days = 0
            hours = 0
            mins = mins if mins is not None else 0

        # Compute TTL as timedelta
        ttl = timedelta(days=days, hours=hours, minutes=mins)

        # Compare current time to timestamp
        now = datetime.now(timezone.utc)
        return now - timestamp > ttl

    
    def add(self, key: str, value):
        with self._lock:
            nested_value = {
                "Value": self.tuples_to_nested_dict(value),
                "Timestamp": datetime.now(timezone.utc)
            }
            self._cache[key] = nested_value
            
    def get(self, key: str):
        if self.is_cached(key):
            return self._cache[key]["Value"]
        return None

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._save_cache()
            
    def tuples_to_nested_dict(self,d):
        if not isinstance(d, dict):
            return d  # not a dict, just return it as-is

        nested = {}
        for key, value in d.items():
            if not isinstance(key, tuple):
                nested[key] = value
                continue

            current = nested
            for k in key[:-1]:
                current = current.setdefault(k, {})
            current[key[-1]] = value
        return nested

            
    def maybe_convert_tuples(self,value):
        if isinstance(value, dict) and any(isinstance(k, tuple) for k in value.keys()):
            return self.tuples_to_nested_dict(value)
        return value


        

class IgnoreTickerCache(CacheManager):
    def __init__(self):
        IGNORE_CACHE_FILE = "cache/ignore_tickers.json"
        IGNORE_CACHE_TTL_DAYS = 30
        IGNORE_CACHE_SAVE_INTERVAL_SECONDS = 60
        super().__init__(
            CACHE_DISPLAY_NAME="IgnoreTicker Cache",
            CACHE_FILE=IGNORE_CACHE_FILE,
            CACHE_TTL_DAYS=IGNORE_CACHE_TTL_DAYS,
            INTERIM_SAVE_SECONDS=IGNORE_CACHE_SAVE_INTERVAL_SECONDS
        )      

class BoughtTickerCache(CacheManager):
    def __init__(self):
        BOUGHT_CACHE_FILE = "cache/bought_tickers.json"
        BOUGHT_CACHE_TTL_DAYS = 30
        BOUGHT_CACHE_SAVE_INTERVAL_SECONDS = 60
        super().__init__(
            CACHE_DISPLAY_NAME="BoughtTicker Cache",
            CACHE_FILE=BOUGHT_CACHE_FILE,
            CACHE_TTL_DAYS=BOUGHT_CACHE_TTL_DAYS,
            INTERIM_SAVE_SECONDS=BOUGHT_CACHE_SAVE_INTERVAL_SECONDS
        )               
        
class NewsApiCache(CacheManager):
    def __init__(self):
        NEWSAPI_CACHE_FILE = "cache/newsapi_sentiment.json"
        NEWSAPI_CACHE_TTL_HOURS = 6
        NEWSAPI_CACHE_SAVE_INTERVAL_SECONDS = 60
        super().__init__(
            CACHE_DISPLAY_NAME="NewsApi Cache",
            CACHE_FILE=NEWSAPI_CACHE_FILE,
            CACHE_TTL_HOURS= NEWSAPI_CACHE_TTL_HOURS,
            INTERIM_SAVE_SECONDS=NEWSAPI_CACHE_SAVE_INTERVAL_SECONDS
        )               
        
class RateLimitCache(CacheManager):
    def __init__(self):
        RATELIMIT_CACHE_FILE = "cache/ratelimit_sentiment.json"
        RATELIMIT_CACHE_TTL_DAYS = 30
        RATELIMIT_CACHE_SAVE_INTERVAL_SECONDS = 60
        super().__init__(
            CACHE_DISPLAY_NAME="Rate Limit Cache",
            CACHE_FILE=RATELIMIT_CACHE_FILE,
            CACHE_TTL_DAYS=RATELIMIT_CACHE_TTL_DAYS,
            INTERIM_SAVE_SECONDS=RATELIMIT_CACHE_SAVE_INTERVAL_SECONDS
        )
        
class TickerCache(CacheManager):
    def __init__(self):
        TICKER_CACHE_FILE = "cache/tickers.json"
        TICKER_CACHE_TTL_DAYS = 30
        super().__init__(
            CACHE_DISPLAY_NAME="Ticker Cache",
            CACHE_FILE=TICKER_CACHE_FILE,
            CACHE_TTL_DAYS=TICKER_CACHE_TTL_DAYS,
            AUTO_SAVE=False
        )
        
class EvalCache(CacheManager):
    def __init__(self):
        EVAL_CACHE_FILE = "cache/evaluated.json"
        #EVAL_CACHE_TTL_HOURS = 4
        EVAL_CACHE_TTL_MINS = 5
        super().__init__(
            CACHE_DISPLAY_NAME="Evaluated Cache",
            CACHE_FILE=EVAL_CACHE_FILE,
            #CACHE_TTL_HOURS=EVAL_CACHE_TTL_HOURS,
            CACHE_TTL_MINS=EVAL_CACHE_TTL_MINS
        )
