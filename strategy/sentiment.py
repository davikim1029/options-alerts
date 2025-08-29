# strategy/sector_sentiment.py

from strategy.base import BuyStrategy,SellStrategy
from models.option import OptionContract
import yfinance as yf
import requests
from transformers import pipeline
import os
from services.news_aggregator import aggregate_headlines_smart
from models.generated.Position import Position
from services.core.cache_manager import NewsApiCache,RateLimitCache
from typing import Optional,Union

MAX_LEN = 250  # trim text before passing to model
sentiment_pipeline = pipeline("sentiment-analysis", device=-1)

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
    
    def __init__(self, news_cache:NewsApiCache, rate_cache:RateLimitCache ):
        self._news_cache = news_cache
        self._rate_cache = rate_cache
    
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
    def should_sell(self, position: Position) -> tuple[bool, str]:
        return self._evaluate(position, side="sell")

    # === INTERNAL COMMON LOGIC ===
    def _evaluate(self, securityObj: Union[OptionContract,Position], side: str) -> tuple[bool, str]:
        symbol = self.get_symbol(securityObj)
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
            if self._news_cache is not None and self._news_cache.is_cached(symbol):
                headlines,avg_sent = self.get_cached_info(symbol)
            else:
                headlines = aggregate_headlines_smart(symbol,self._rate_cache)
                if headlines == []:
                    error = f"[SectorSentiment:{side}] No Headline data found"
                    return False,error 
                avg_sent = self.average_news_sentiment(headlines)
                self.add_to_cache(symbol,headlines,avg_sent)
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

    def average_news_sentiment(self, headlines: list) -> Optional[float]:
        if not headlines:
            return None

        # Get safe combined text per headline
        combined_headlines = [
            headline.combined_text()[:MAX_LEN]  # safe trim
            for headline in headlines
        ]

        # Run through pipeline (will batch internally)
        results = sentiment_pipeline(combined_headlines, truncation=True)

        # Convert to +/- scores
        scores = []
        for r in results:
            if r["label"] == "POSITIVE":
                scores.append(r["score"])
            elif r["label"] == "NEGATIVE":
                scores.append(-r["score"])
            else:  # some models also return NEUTRAL
                scores.append(0.0)

        return sum(scores) / len(scores) if scores else None
    
    def add_to_cache(self,ticker:str, headlines:list[str], avg_sentiment:str):
        cache_value = {
            "headlines":headlines,
            "avg_sentiment":avg_sentiment,
        }
        if self._news_cache is not None:
            self._news_cache.add(ticker,cache_value)
        return None
    
    def get_cached_info(self,ticker:str):
        if self._newscache.is_cached(ticker):
            cached_value = self._news_cache.get(ticker)
            headlines = cached_value["headlines"]
            avg_sentiment = cached_value["avg_sentiment"]
            return headlines,avg_sentiment
        return None,None


    def get_symbol(self, obj: Union[OptionContract, Position]):
        if isinstance(obj, OptionContract):
            return obj.underlyingSymbol
        elif isinstance(obj, Position):
            return obj.Product.symbol
        else:
            raise TypeError(f"Unexpected type: {type(x)}")