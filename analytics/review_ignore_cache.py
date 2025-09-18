from services.core.cache_manager import IgnoreTickerCache
from collections import Counter, defaultdict
import os
import json
from datetime import datetime


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
    if not ignore_cache:
        print("Failed to load ignore cache, exiting")
        return

    # (A) Grouped counts of unique Value types
    value_counts = Counter(
        entry.get("Value") or "Unknown" for entry in ignore_cache.values()
    )

    print("\n=== Grouped Errors ===")
    for value, count in value_counts.items():
        print(f"{value}: {count}")

    # (B) Total number of keys in the cache
    total_keys = len(ignore_cache)
    print("\nTotal number of tickers:", total_keys)

    # Ask if user wants detailed breakdown
    choice = input("\nWould you like to see tickers for a specific error? (y/n): ").strip().lower()
    if choice != "y":
        return

    # Build mapping from error -> list of tickers
    error_to_tickers = defaultdict(list)
    for ticker, data in ignore_cache.items():
        error = data.get("Value") or "Unknown"
        error_to_tickers[error].append(ticker)

    while True:
        print("\n=== Error Types ===")
        for idx, error in enumerate(error_to_tickers.keys(), start=1):
            print(f"{idx}. {error} ({len(error_to_tickers[error])} tickers)")
        print(f"{len(error_to_tickers) + 1}. Exit")

        sel = input("Select an option: ").strip()
        if not sel.isdigit():
            print("Invalid selection, try again.")
            continue

        sel = int(sel)
        if sel == len(error_to_tickers) + 1:
            print("Exiting detailed breakdown.")
            break
        elif 1 <= sel <= len(error_to_tickers):
            error = list(error_to_tickers.keys())[sel - 1]
            tickers = error_to_tickers[error]
            print(f"\n=== Tickers with error: {error} ===")
            for t in sorted(tickers):
                print(t)
        else:
            print("Invalid selection, try again.")
