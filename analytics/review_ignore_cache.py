from services.core.cache_manager import IgnoreTickerCache
from collections import Counter
import os
import json
from datetime import datetime, timedelta, timezone

def load_cache():
    cache = {}
    filepath = "cache/ignore_tickers.json"
    if not os.path.exists(filepath):
        print("Missing ignore_cache.json from cache folder")
        return {}

    try:
        with open(filepath, "r") as f:
            raw = json.load(f)
        for key, data in raw.items():
            ts_str = data.get("Timestamp")
            value = data.get("Value")
            if ts_str is None:
                continue
            ts = datetime.fromisoformat(ts_str)
            cache[key] = {"Value": value, "Timestamp": ts}
        return cache
    except json.JSONDecodeError:
        print("Ignore Cache file empty or corrupted, starting fresh")
    except Exception as e:
        print(f"Failed to load ignore cache: {e}")


def review_ignore():
    ignore_cache = load_cache()
    
    if ignore_cache is None:
        print("Failed to load ignore cache, exiting")
        return
    # (A) Grouped counts of unique Value types
    value_counts = Counter(
        entry.get("Value") or "Unknown" for entry in ignore_cache.values()
    )

    print("Grouped Errors:")
    for value, count in value_counts.items():
        print(f"{value}: {count}")

    # (B) Total number of keys in the cache
    total_keys = len(ignore_cache)
    print("Total number of tickers:", total_keys)