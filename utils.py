import json
import csv
import os
from dotenv import load_dotenv
import requests
from datetime import datetime
import yfinance as yf
from cryptography.fernet import Fernet
from scipy.stats import norm
import math


load_dotenv()

CONFIG_KEYS = [
    "MAX_CALL_PRICE", "DELTA_MIN", "DELTA_MAX", "MIN_VOLUME",
    "MIN_OI", "MIN_DTE", "MAX_DTE"
]

def get_config():
    return {k: float(os.getenv(k)) for k in CONFIG_KEYS}

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
    if not os.path.exists("tickers_cache.json"):
        r = requests.get("https://finnhub.io/api/v1/stock/symbol?exchange=US&token=" + os.getenv("FINNHUB_API_KEY"))
        all_tickers = [x['symbol'] for x in r.json() if '.' not in x['symbol']]
        with open("tickers_cache.json", "w") as f:
            json.dump(all_tickers, f)
    else:
        with open("tickers_cache.json") as f:
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