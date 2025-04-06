import json
import csv
import os
from dotenv import load_dotenv
import requests
import traceback
from datetime import datetime
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
    "IGNORE_OVERPRICED_MINUTES"
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

def get_price_volume(symbol):
    try:
        stock = yf.Ticker(symbol)
        hist = stock.history(period="2d")

        if hist.empty or hist.shape[0] < 1:
            return None, None

        volume = hist.iloc[-1]["Volume"]
        if volume == 0 and len(hist) > 1:
            volume = hist.iloc[-2]["Volume"]

        price = hist.iloc[-1]["Close"]
        return price, volume

    except Exception as e:
        print(f"Skipping {symbol} due to error in price/volume lookup: {e}")
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
    
def is_market_open():
    url = f"https://finnhub.io/api/v1/stock/market-status?token={os.getenv('FINNHUB_API_KEY')}"
    r = requests.get(url).json()
    return r.get("isOpen", True)

def get_minutes_until_market_open():
    token = os.getenv("FINNHUB_API_KEY")
    url = f"https://finnhub.io/api/v1/stock/market-status?token={token}"
    r = requests.get(url).json()

    # Case 1: Market is already open
    if r.get("isOpen"):
        return 0

    # Case 2: Market is closed — check when it reopens
    next_open_unix = r.get("t")  # Unix timestamp of next open
    if not next_open_unix:
        return 60  # fallback: wait 60 minutes

    next_open_time = datetime.fromtimestamp(next_open_unix)
    now = datetime.now()
    delta = next_open_time - now

    # Convert to minutes and return
    return max(1, int(delta.total_seconds() // 60))

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
