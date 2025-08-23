# strategy/sector_sentiment.py

from strategy.base import BuyStrategy,SellStrategy
from models.option import OptionContract
import yfinance as yf
import requests
from transformers import pipeline
import os
from typing import Optional


sentiment_pipeline = pipeline("sentiment-analysis")

ETF_LOOKUP = {
    "Technology": "XLK",
    "Health": "XLV",
    "Financial": "XLF",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Industrials": "XLI",
    "Real Estate": "XLRE",
    "Materials": "XLB",
    "Communication": "XLC"
}


class SectorSentimentStrategy(BuyStrategy,SellStrategy):
    """
    Combines buy and sell sentiment logic for options based on sector ETF trend
    and news sentiment for the underlying symbol.
    """

    @property
    def name(self):
        return self.__class__.__name__

    # === BUY LOGIC ===
    def should_buy(self, option: OptionContract, context: dict) -> tuple[bool, str]:
        return self._evaluate(option, side="buy")

    # === SELL LOGIC ===
    def should_sell(self, option: OptionContract, context: dict) -> tuple[bool, str]:
        return self._evaluate(option, side="sell")

    # === INTERNAL COMMON LOGIC ===
    def _evaluate(self, option: OptionContract, side: str) -> tuple[bool, str]:
        symbol = option.underlyingSymbol
        try:
            # 1. Get sector info
            ticker_info = yf.Ticker(symbol).info
            sector = ticker_info.get("sector")
            if not sector:
                error = f"[SectorSentiment:{side}] No sector for {symbol}"
                return False, error

            # 2. Map sector to ETF
            etf_symbol = self.match_sector_to_etf(sector)
            if not etf_symbol:
                error = f"[SectorSentiment:{side}] No ETF match for {sector}"
                return False, error

            # 3. ETF trend evaluation
            if side == "buy" and not self.is_sector_in_uptrend(etf_symbol):
                error = f"[SectorSentiment:{side}] Sector ETF {etf_symbol} is bearish."
                return False, error
            elif side == "sell" and self.is_sector_in_uptrend(etf_symbol):
                # Uptrend suggests hold; bearish suggests sell
                pass  # we’ll interpret in sell logic

            # 4. News sentiment evaluation
            headlines = self.get_news_headlines(symbol)
            avg_sent = self.average_news_sentiment(headlines)
            if avg_sent is not None:
                if side == "buy" and avg_sent < 0:
                    error = f"[SectorSentiment:{side}] Bearish sentiment on {symbol}: {avg_sent}"
                    return False, error
                if side == "sell" and avg_sent < 0:
                    # Bearish sentiment supports selling
                    return True, f"Bearish sentiment on {symbol}: {avg_sent}"

            # Default: no signal
            return True if side == "buy" else False, ""

        except Exception as e:
            error = f"[SectorSentiment:{side} error] {e}"
            return False, error

    # === HELPER METHODS ===
    def match_sector_to_etf(self, sector: str) -> str:
        for key, val in ETF_LOOKUP.items():
            if key.lower() in sector.lower():
                return val
        return None

    def is_sector_in_uptrend(self, etf_symbol: str) -> bool:
        etf = yf.Ticker(etf_symbol)
        hist = etf.history(period="1mo")
        if len(hist) < 20:
            return False
        short_ma = hist["Close"].rolling(5).mean().iloc[-1]
        long_ma = hist["Close"].rolling(20).mean().iloc[-1]
        return short_ma > long_ma

    def get_news_headlines(self, symbol: str) -> list:
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            raise ValueError("NEWSAPI_KEY not set in environment.")

        res = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "q": symbol,
                "sortBy": "publishedAt",
                "pageSize": 5,
                "apiKey": api_key
            }
        )
        data = res.json()
        return [a["title"] for a in data.get("articles", [])]

    def average_news_sentiment(self, headlines: list[str]) -> Optional[float]:
        if not headlines:
            return None
        results = sentiment_pipeline(headlines)
        scores = [r["score"] if r["label"] == "POSITIVE" else -r["score"] for r in results]
        return sum(scores) / len(scores) if scores else None
