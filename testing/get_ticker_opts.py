from services.etrade_consumer_lite import EtradeConsumerLite
import json
import os


def load_cache():
    filepath = "cache/tickers.json"
    if not os.path.exists(filepath):
        print("Missing tickers.json from cache folder")
        return {}

    try:
        with open(filepath, "r") as f:
            raw = json.load(f)

        tickers = raw.get("tickers", {}).get("Value", {})
        if not isinstance(tickers, dict):
            print("Tickers cache malformed, expected a dict under tickers->Value")
            return {}

        return tickers

    except json.JSONDecodeError:
        print("Tickers cache file empty or corrupted, starting fresh")
        return {}
    except Exception as e:
        print(f"Failed to load tickers cache: {e}")
        return {}


def prompt_for_ticker():
    """
    Prompt the user for a ticker symbol.
    If valid_tickers is provided, only accept tickers from that list.
    """
    while True:
        ticker = input("Enter a ticker symbol (or 'q' to quit): ").strip().upper()
        
        if ticker.lower() == "q":
            print("Exiting ticker prompt.")
            return None
        
        if not ticker:
            print("Ticker cannot be empty, try again.")
            continue

        valid_tickers = load_cache()
        if valid_tickers is not None and len(valid_tickers) > 0 and ticker not in valid_tickers:
            print(f"Invalid ticker.")
            continue

        return ticker


def get_ticker_opts_entry():
    ticker = prompt_for_ticker()
    consumer = EtradeConsumerLite(sandbox=False, debug=False)
    
    response = consumer.get_option_chain(ticker)
    print(json.dumps(response, indent=2, default=str))
    
    
def get_ticker_expiry_entry():
    ticker = prompt_for_ticker()
    consumer = EtradeConsumerLite(sandbox=False, debug=False)
    response = consumer.get_expiry_dates(ticker)
    print(json.dumps(response, indent=2, default=str))
