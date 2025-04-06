import yfinance as yf
import traceback
import os
from datetime import datetime
from alerts import send_alert
from utils import (log_alert, 
                   already_alerted, 
                   get_config, 
                   get_price_volume,
                   calculate_call_delta, 
                   should_ignore_ticker,
                   mark_ticker,
                   is_market_open,
                   get_minutes_until_market_open,
                   unmark_ticker,
                   log_error
                   )

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
            stock = yf.Ticker(symbol)
            if not stock.options:
                mark_ticker(symbol, CONFIG["NON_OPT_FILE"])
                continue
            market_open = is_market_open()

            if not market_open:
                # If the ticker has already been processed during this market-closed period, skip it
                if should_ignore_ticker(symbol, CONFIG["MARKET_FILE"], get_minutes_until_market_open()):
                    continue

                # Otherwise, mark it so we skip it next time while market is closed
                mark_ticker(symbol, CONFIG["MARKET_FILE"], get_minutes_until_market_open())
                print(f"📉 Market closed — checking {symbol} once, then skipping until open")
            else:
                # If the market is open, make sure this ticker is cleared from market_closed.json
                unmark_ticker(symbol, CONFIG["MARKET_FILE"])
            
            price, volume = get_price_volume(symbol)
            if price is None or volume is None:
                print(f"Skipping {symbol} due to missing price or volume. Price: {price}, Volume: {volume}")
                continue
            if price > 50 or volume < 1_000_000:
                continue
            
            if should_ignore_ticker(symbol, CONFIG["NON_OPT_FILE"], int(os.getenv("IGNORE_NON_OPTIONABLE_MINUTES"))):
                continue
            if should_ignore_ticker(symbol, CONFIG["OVERPRICE_FILE"], int(os.getenv("IGNORE_OVERPRICED_MINUTES"))):
                continue
            if not is_market_open():
                minutes = get_minutes_until_market_open()
                mark_ticker(symbol, CONFIG["MARKET_FILE"],minutes)
                continue
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
                    
                    overpriced = True
                    for _, row in calls.iterrows():
                        if row.lastPrice <= CONFIG["MAX_CALL_PRICE"] * CONFIG["OVERPRICE_MULTIPLIER"]:
                            overpriced = False
                            break
                        if overpriced:
                            mark_ticker(symbol, CONFIG["OVERPRICE_FILE"])
                            continue

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
            log_error(symbol, e)
            traceback.print_exc()  # Full stack trace