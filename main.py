import schedule
import time
from scanner import scan_batch
from utils import rotate_ticker_batch

def job():
    tickers = rotate_ticker_batch()
    scan_batch(tickers)

if __name__ == "__main__":
    job()  # Run once at start
    schedule.every(1).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)