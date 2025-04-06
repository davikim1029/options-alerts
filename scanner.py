import yfinance as yf
from datetime import datetime
from alerts import send_alert
from utils import log_alert, already_alerted, get_config, get_price_volume

CONFIG = get_config()

def scan_batch(tickers):
    for symbol in tickers:
        if (
            "." in symbol or
            "-" in symbol or
            symbol.startswith("$") or
            len(symbol) > 6 or
            not symbol.isupper()
        ):
            continue
        try:
            price, volume = get_price_volume(symbol)
            if price is None or volume is None:
                print(f"Skipping {symbol} due to missing price or volume. Price: {price}, Volume: {volume}")
                continue
            if price > 50 or volume < 1_000_000:
                continue
            stock = yf.Ticker(symbol)
            expirations = stock.options
            for exp in expirations:
                dte = (datetime.strptime(exp, "%Y-%m-%d") - datetime.now()).days
                if not CONFIG["MIN_DTE"] <= dte <= CONFIG["MAX_DTE"]:
                    continue

                calls = stock.option_chain(exp).calls
                for row in calls.itertuples(index=True, name='Pandas'):
                    if (
                        row["lastPrice"] <= CONFIG["MAX_CALL_PRICE"] and
                        CONFIG["DELTA_MIN"] <= row.get("delta", 0) <= CONFIG["DELTA_MAX"] and
                        row["openInterest"] >= CONFIG["MIN_OI"] and
                        row["volume"] >= CONFIG["MIN_VOLUME"]
                    ):
                        unique_id = f"{symbol}_{row['strike']}_{exp}"
                        if already_alerted(unique_id):
                            continue

                        alert = {
                            "Ticker": symbol,
                            "Strike": row["strike"],
                            "Price": row["lastPrice"],
                            "Delta": row["delta"],
                            "Volume": row["volume"],
                            "OI": row["openInterest"],
                            "Expiration": exp,
                            "Timestamp": datetime.now().isoformat()
                        }

                        send_alert(alert)
                        log_alert(alert)
                        break
        except Exception as e:
            print(f"Error on {symbol}: {e}")