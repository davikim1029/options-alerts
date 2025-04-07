import json
import csv
import os
from dotenv import load_dotenv
import requests
import traceback
from datetime import datetime,timedelta
import yfinance as yf
from cryptography.fernet import Fernet
from scipy.stats import norm
import math


load_dotenv()

NUMERIC_CONFIG_KEYS = [
    "MAX_CALL_PRICE",
    "DELTA_MIN",
    "DELTA_MAX",
    "MIN_VOLUME",
    "MIN_OI",
    "MIN_DTE",
    "MAX_DTE",
    "EMAIL_PORT",
    "OVERPRICE_MULTIPLIER",
    "IGNORE_NON_OPTIONABLE_MINUTES",
    "IGNORE_OVERPRICED_MINUTES",
    "CENTRAL_OFFSET_HOURS"
]
STRING_CONFIG_KEYS = [
    "FINNHUB_API_KEY",
    "OVERPRICE_FILE",
    "TICKER_FILE",
    "MARKET_FILE",
    "NON_OPT_FILE",
    "EMAIL_FROM",
    "EMAIL_TO",
    "SMS_TO",
    "EMAIL_HOST"
]

def get_config():
    config = {}
    for k in NUMERIC_CONFIG_KEYS:
        value = os.getenv(k)
        if value is not None:
            config[k] = float(value)

    for k in STRING_CONFIG_KEYS:
        value = os.getenv(k)
        if value is not None:
            config[k] = value

    return config

from datetime import datetime, timedelta

def get_price_volume(symbol):
    try:
        stock = yf.Ticker(symbol)

        # 1. Get current price (real-time or close fallback)
        price = None
        try:
            price = stock.fast_info["lastPrice"]
        except:
            try:
                price = stock.info["regularMarketPrice"]
            except:
                pass

        # 2. Get historical volume from past 2 daily candles
        hist = stock.history(period="2d")

        volume = None
        if not hist.empty:
            if is_market_open():
                # Use today's volume (can be mid-day)
                volume = hist.iloc[-1]["Volume"]
            else:
                # Use yesterday's volume if today is closed
                volume = hist.iloc[-1]["Volume"]
                if volume == 0 and len(hist) > 1:
                    volume = hist.iloc[-2]["Volume"]

        return price, volume

    except Exception as e:
        print(f"⚠️ Error fetching price/volume for {symbol}: {e}")
        return None, None


def already_alerted(uid):
    if not os.path.exists("alerts_log.csv"):
        return False
    with open("alerts_log.csv", newline='') as csvfile:
        return any(uid in line for line in csvfile)

def log_alert(alert):
    uid = f"{alert['Ticker']}_{alert['Strike']}_{alert['Expiration']}"
    with open("alerts_log.csv", "a", newline='') as f:
        writer = csv.writer(f)
        writer.writerow([uid, alert['Ticker'], alert['Strike'], alert['Price'], alert['Expiration'], alert['Timestamp']])

def rotate_ticker_batch(batch_size=50):
    ticker_cache = os.getenv("TICKER_FILE")
    if not os.path.exists(ticker_cache):
        r = requests.get("https://finnhub.io/api/v1/stock/symbol?exchange=US&token=" + os.getenv("FINNHUB_API_KEY"))
        all_tickers = [x['symbol'] for x in r.json() if '.' not in x['symbol']]
        with open(ticker_cache, "w") as f:
            json.dump(all_tickers, f)
    else:
        with open(ticker_cache) as f:
            all_tickers = json.load(f)

    now = int(datetime.now().timestamp())
    offset = (now // 60) % (len(all_tickers) // batch_size)
    return all_tickers[offset * batch_size:(offset + 1) * batch_size]

def load_encrypted_password():
    with open("secret.key", "rb") as key_file:
        key = key_file.read()

    with open("email_password.enc", "rb") as enc_file:
        encrypted = enc_file.read()

    fernet = Fernet(key)
    return fernet.decrypt(encrypted).decode()


def calculate_call_delta(S, K, T, r, sigma):
    """
    S = stock price
    K = strike price
    T = time to expiration in years
    r = risk-free interest rate (e.g. 0.05 = 5%)
    sigma = implied volatility (decimal, not percent)
    """
    if T <= 0 or sigma == 0:
        return 0.0

    d1 = (math.log(S / K) + (r + (sigma ** 2) / 2) * T) / (sigma * math.sqrt(T))
    return norm.cdf(d1)


def load_cache(file):
    if os.path.exists(file):
        with open(file) as f:
            return json.load(f)
    return {}

def save_cache(data, file):
    with open(file, "w") as f:
        json.dump(data, f) 

def should_ignore_ticker(ticker, file, minutes):
    cache = load_cache(file)
    if ticker in cache:
        last_seen = datetime.fromisoformat(cache[ticker])
        if datetime.now() - last_seen < timedelta(minutes=minutes):
            return True
    return False

def mark_ticker(ticker, file,ttl=None):
    cache = load_cache(file)
    timestamp = datetime.now()
    if ttl is not None:
        timestamp += timedelta(minutes=ttl)
    cache[ticker] = timestamp.isoformat()
    save_cache(cache, file)
    
def _get_central_time():
    offset = float(os.getenv("CENTRAL_OFFSET_HOURS", "-5"))  # default to -5
    return datetime.now(datetime.timezone.utc) + timedelta(hours=offset)

def _load_market_cache():
    if os.path.exists(os.getenv("MARKET_FILE")):
        with open(os.getenv("MARKET_FILE")) as f:
            return json.load(f)
    return {}

def _save_market_cache(data):
    os.makedirs(os.path.dirname(os.getenv("MARKET_FILE")), exist_ok=True)
    with open(os.getenv("MARKET_FILE"), "w") as f:
        json.dump(data, f, indent=2)

def _should_refresh_market_status():
    """Return True if it's before 8:30am or after 5:00pm CST/CDT, or if no cache exists."""
    now_central = _get_central_time()
    market_open = now_central.replace(hour=8, minute=30, second=0, microsecond=0)
    market_close = now_central.replace(hour=17, minute=0, second=0, microsecond=0)

    # Outside market hours → refresh is allowed
    if now_central < market_open or now_central >= market_close:
        return True

    # During market hours → only refresh if no valid cache exists
    cache = _load_market_cache()
    if not cache or "timestamp" not in cache:
        return True

    # Cache must be from today
    last_check = datetime.fromisoformat(cache["timestamp"])
    return last_check.date() != datetime.utcnow().date()

def _fetch_market_status_from_finnhub():
    """Calls Finnhub to get the current market status and caches it."""
    token = os.getenv("FINNHUB_API_KEY")
    url = f"https://finnhub.io/api/v1/stock/market-status?token={token}"

    try:
        response = requests.get(url).json()
        is_open = response.get("isOpen", True)
        next_open_unix = response.get("t")

        cache_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "isOpen": is_open,
            "nextOpenUnix": next_open_unix
        }
        _save_market_cache(cache_data)
        return cache_data
    except Exception as e:
        print(f"⚠️ Error fetching market status: {e}")
        return None

def is_market_open():
    if _should_refresh_market_status():
        status = _fetch_market_status_from_finnhub()
    else:
        status = _load_market_cache()

    if not status:
        return True  # fallback: assume open
    return status.get("isOpen", True)

def get_minutes_until_market_open():
    """Returns minutes until the market opens based on cached or fetched data."""
    if _should_refresh_market_status():
        status = _fetch_market_status_from_finnhub()
    else:
        status = _load_market_cache()

    if not status or status.get("isOpen"):
        return 0

    next_open_unix = status.get("nextOpenUnix")
    if not next_open_unix:
        return 60  # fallback

    now = datetime.utcnow()
    next_open_time = datetime.fromtimestamp(next_open_unix)
    delta = next_open_time - now
    return max(1, int(delta.total_seconds() / 60))

def unmark_ticker(ticker, cache_file):
    cache = load_cache(cache_file)
    if ticker in cache:
        del cache[ticker]
        save_cache(cache, cache_file)
        
def log_error(symbol, e):
    today = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("logs/errors", exist_ok=True)
    log_path = f"logs/errors/{today}.log"

    with open(log_path, "a") as f:
        f.write(f"\n[{datetime.now().isoformat()}] Error on {symbol}:\n")
        f.write(f"{str(e)}\n")
        f.write(traceback.format_exc())
