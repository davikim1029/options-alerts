import os
import requests
import json
from datetime import datetime

FINNHUB_TICKER_CACHE = "cache/all_us_tickers.json"

def fetch_us_tickers_from_finnhub(api_key=None, cache_path=FINNHUB_TICKER_CACHE, force_refresh=False):
    if not api_key:
        api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise Exception("FINNHUB_API_KEY not set in environment")

    # Use cached file if available and not forced
    if os.path.exists(cache_path) and not force_refresh:
        with open(cache_path) as f:
            cached = json.load(f)
            return cached.get("tickers", [])

    print("[Tickers] Fetching from Finnhub...")
    url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={api_key}"
    r = requests.get(url)

    if r.status_code != 200:
        raise Exception(f"Finnhub failed: {r.status_code} - {r.text}")

    raw_data = r.json()

    # Filter to get valid, non-penny stock tickers
    tickers = [
        s["symbol"]
        for s in raw_data
        if "." not in s["symbol"] and s.get("type") in ["Common Stock", "ADR"]
    ]

    with open(cache_path, "w") as f:
        json.dump({"timestamp": datetime.utcnow().isoformat(), "tickers": tickers}, f)

    return tickers
