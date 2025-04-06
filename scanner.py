import yfinance as yf
from datetime import datetime
from alerts import send_alert
from utils import log_alert, already_alerted, get_config, get_price_volume,calculate_call_delta

CONFIG = get_config()

def scan_batch(tickers):
    today = datetime.now()
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
            symbol="AAPL"
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
                
                exp_date = datetime.strptime(exp, "%Y-%m-%d")
                days_to_exp = (exp_date - today).days
                T = days_to_exp / 365  # convert to years
                calls = stock.option_chain(exp).calls
                for row in calls.itertuples(index=True, name='Pandas'):
                    delta = calculate_call_delta(
                        S=price,
                        K=row.strike,
                        T=T,
                        r=0.01,  # ~1% risk-free rate
                        sigma=row.impliedVolatility
                    )
                    if (
                        row.lastPrice <= CONFIG["MAX_CALL_PRICE"] and
                        CONFIG["DELTA_MIN"] <= delta <= CONFIG["DELTA_MAX"] and
                        row.openInterest >= CONFIG["MIN_OI"] and
                        row.volume >= CONFIG["MIN_VOLUME"]
                    ):
                        unique_id = f"{symbol}_{row.strike}_{exp}"
                        if already_alerted(unique_id):
                            continue

                        alert = {
                            "Ticker": symbol,
                            "Strike": row.strike,
                            "Price": row.lastPrice,
                            "Delta": delta,
                            "Volume": row.volume,
                            "OI": row.openInterest,
                            "Expiration": exp,
                            "Timestamp": datetime.now().isoformat()
                        }

                        send_alert(alert)
                        log_alert(alert)
                        break
        except Exception as e:
            print(f"Error on {symbol}: {e}")