from services.core.cache_manager import IgnoreTickerCache
from collections import Counter


def review_ignore():
    ignore_cache = IgnoreTickerCache()
    ignore_cache._load_cache()
    
    # (A) Grouped counts of unique Value types
    value_counts = Counter(entry["Value"] for entry in ignore_cache._cache.values())

    print("Grouped Errors:")
    for value, count in value_counts.items():
        print(f"{value}: {count}")

    # (B) Total number of keys in the cache
    total_keys = len(ignore_cache._cache)
    print("\nTotal number of tickers:", total_keys)