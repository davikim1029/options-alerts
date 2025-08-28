import json
import os
from datetime import datetime,timedelta,timezone
from threading import Thread, Lock
import time


class CacheManager:
    def __init__(self,CACHE_DISPLAY_NAME:str,CACHE_FILE:str,CACHE_TTL_DAYS:float = 30, CACHE_TTL_HOURS:float = None,INTERIM_SAVE_SECONDS:int = 60, AUTO_SAVE:bool = True):
        self._cache = {}
        self._display_name:str = CACHE_DISPLAY_NAME
        self._cache_file:str = CACHE_FILE
        self._cache_ttl_days:int = CACHE_TTL_DAYS
        self._cache_ttl_hours:float = CACHE_TTL_HOURS
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
                now = datetime.now(timezone.utc)
                with self._lock:
                    for key, cacheValue in raw.items():
                        ts_str = cacheValue.get("Timestamp")
                        value = cacheValue.get("Value")
                        if ts_str is None:
                            continue
                        ts = datetime.fromisoformat(ts_str)
                        if now - ts < timedelta(days=self._cache_ttl_days):
                            self._cache[key] = {"Value": value, "Timestamp": ts}
            except json.JSONDecodeError:
                print(f"[{self._display_name}] cache file empty or corrupted, initializing empty cache")
                self._cache = {}
            except Exception as e:
                print(f"[{self._display_name}] failed to load cache: {e}")
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
            print(f"[{self._display_name}] failed to save cache: {e}")

    
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
                stale = not(datetime.now(timezone.utc) - cacheValue["Timestamp"] < timedelta(days=self._cache_ttl_days))
                if self._cache_ttl_hours:
                    stale = not(datetime.now(timezone.utc) - cacheValue["Timestamp"] < timedelta(hours=self._cache_ttl_hours))
                if stale:
                    del self._cache[key]
                else:
                    return True
            return False
    
    def add(self, key:str, value):
        with self._lock:
            self._cache[key] = {"Value": value, "Timestamp": datetime.now(timezone.utc)}
            
    def get(self, key: str):
        """Return the cached value if fresh, else None."""
        if self.is_cached(key):
            return self._cache[key]["Value"]
        return None

    def clear(self):
        with self._lock:
            self._cache.clear()
            self._save_cache()
        

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
        NEWSAPI_CACHE_TTL_DAYS = 30
        NEWSAPI_CACHE_TTL_HOURS = 6
        NEWSAPI_CACHE_SAVE_INTERVAL_SECONDS = 60
        super().__init__(
            CACHE_DISPLAY_NAME="NewsApi Cache",
            CACHE_FILE=NEWSAPI_CACHE_FILE,
            CACHE_TTL_DAYS=NEWSAPI_CACHE_TTL_DAYS,
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
        EVAL_CACHE_TTL_HOURS = 4
        super().__init__(
            CACHE_DISPLAY_NAME="Evaluated Cache",
            CACHE_FILE=EVAL_CACHE_FILE,
            CACHE_TTL_DAYS=EVAL_CACHE_TTL_HOURS,
        )
