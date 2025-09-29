# strategy/sector_sentiment.py

from strategy.base import BuyStrategy,SellStrategy
#import traceback
from models.option import OptionContract
import yfinance as yf
import requests
import os
import re
from services.scanner.scanner_utils import wait_rate_limit
from services.news_aggregator import aggregate_headlines_smart
from models.generated.Position import Position
from services.core.cache_manager import NewsApiCache,RateLimitCache,YFinanceTickerCache
from typing import Optional,Union
from services.logging.logger_singleton import getLogger
from services.scanner.YFinanceFetcher import YFinanceFetcher, YFTooManyAttempts
import transformers
import threading


#### Intentionally not having as a scoring system like with buy.py
#These are more like binary gates (bullish/bearish, positive/negative). It’s not as natural to assign weights or a score, because:
#You don’t really want “+1” for bullish ETF and “–1” for bearish; if sector is bearish, you probably just don’t buy.
#Same with sentiment — a single strong negative headline outweighs three mildly positive ones.

MAX_LEN = 250  # trim text before passing to model

_sentiment_pipeline = None
_pipeline_lock = threading.Lock()
_pipeline_ready = threading.Event()  # threads wait on this

def getSentimentPipeline():
    global _sentiment_pipeline

    # Fast path: already loaded
    if _sentiment_pipeline is not None:
        return _sentiment_pipeline

    # Only one thread should load
    with _pipeline_lock:
        # Double-check in case another thread finished while we waited
        if _sentiment_pipeline is None:
            # Load the pipeline
            logger = getLogger()
            logger.logMessage("Loading Pipeline")
            model_name = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
            tokenizer = transformers.AutoTokenizer.from_pretrained(model_name)
            model = transformers.AutoModelForSequenceClassification.from_pretrained(
                model_name,
                device_map=None,
                torch_dtype="float32"
            )

            _sentiment_pipeline = transformers.pipeline(
                "sentiment-analysis",
                model=model,
                tokenizer=tokenizer,
                device=-1
            )

            # Signal all waiting threads
            logger.logMessage("Pipeline loaded")
            _pipeline_ready.set()

    # Wait for pipeline to be ready (for threads that reached here before first thread finished)
    _pipeline_ready.wait()
    return _sentiment_pipeline




ETF_LOOKUP = {
    # Technology
    "technology": "XLK",
    "information technology": "XLK",
    "tech": "XLK",

    # Health
    "health": "XLV",
    "healthcare": "XLV",
    "pharmaceuticals": "XLV",
    "biotech": "XLV",

    # Financials
    "financial": "XLF",
    "banks": "XLF",
    "insurance": "XLF",

    # Energy
    "energy": "XLE",
    "oil": "XLE",
    "gas": "XLE",

    # Consumer Discretionary
    "consumer discretionary": "XLY",
    "consumer cyclical": "XLY",
    "consumer defensive": "XLY",
    "automobiles": "XLY",
    "automobile manufacturers": "XLY",
    "retail": "XLY",
    "luxury": "XLY",

    # Consumer Staples
    "consumer staples": "XLP",
    "food": "XLP",
    "beverage": "XLP",
    "household products": "XLP",

    # Utilities
    "utilities": "XLU",
    "power": "XLU",
    "electric": "XLU",
    "gas distribution": "XLU",

    # Industrials
    "industrials": "XLI",
    "manufacturing": "XLI",
    "aerospace": "XLI",
    "transportation": "XLI",
    "construction": "XLI",

    # Real Estate
    "real estate": "XLRE",
    "reit": "XLRE",
    "property": "XLRE",

    # Materials
    "materials": "XLB",
    "metals": "XLB",
    "chemicals": "XLB",
    "mining": "XLB",

    # Communication
    "communication": "XLC",
    "telecom": "XLC",
    "media": "XLC",
    "entertainment": "XLC"
}



class SectorSentimentStrategy(BuyStrategy,SellStrategy):
    
    def __init__(self, caches):
        self._news_cache = getattr(caches, "news", None)
        self._rate_cache = getattr(caches, "rate", None)
        self._yfin_cache = getattr(caches, "yfin", None)
        self.sentiment_pipeline = getSentimentPipeline()
    
    """
    Combines buy and sell sentiment logic for options based on sector ETF trend
    and news sentiment for the underlying symbol.
    """

    @property
    def name(self):
        return self.__class__.__name__

    # === BUY LOGIC ===
    def should_buy(self, option: OptionContract,name: str, context: dict) -> tuple[bool, str,str]:
        return self._evaluate(option,name, side="buy")

    # === SELL LOGIC ===
    def should_sell(self, position: Position) -> tuple[bool, str,str]:
        return self._evaluate(position,"", side="sell")

    # === INTERNAL COMMON LOGIC ===
    def _evaluate(self, securityObj: Union[OptionContract,Position],name, side: str) -> tuple[bool, str,str]:
        symbol = self.get_symbol(securityObj)
        try:
            # 1. Get sector info
            if self._yfin_cache.is_cached(symbol):
                ticker_info = self._yfin_cache.get(symbol)
            else: 
                try: 
                    fetcher = YFinanceFetcher(self._rate_cache)
                    ticker_info = fetcher.fetch_ticker(symbol)
                    self._yfin_cache.add(symbol,ticker_info)
                except YFTooManyAttempts as e:
                    self._rate_cache.add("YFinance", 10 * 60) #10 mins
                    raise e
                except Exception as e:
                        #traceback.print_exc()  # prints full call stack
                        error_pre = "Error with YFin handling: " 
                        error = str(e)
                        if hasattr(e,"args") and len(e.args) > 0:
                            e_data = e.args[0]
                            if is_json(e_data):
                                e_data = json.loads(e_data)
                                if hasattr(e_data,"Error"):
                                    error = str(e_data["Error"])
                                else:
                                    error = str(e_data)
                        error_str = error_pre + error
                        logger = getLogger()
                        logger.logMessage(error_str)

                        
            sector = ticker_info.get("sector")
            if not sector:
                error = f"[SectorSentiment:{side}] No sector found"
                return False, error,"N/A"

            # 2. Map sector to ETF
            etf_symbol = self.match_sector_to_etf(sector)
            if not etf_symbol:
                error = f"[SectorSentiment:{side}] No ETF match found"
                return False, error,"N/A"

            # 3. ETF trend evaluation
            if side == "buy" and not self.is_sector_in_uptrend(etf_symbol):
                error = f"[SectorSentiment:{side}] Sector ETF {etf_symbol} is bearish."
                return False, error,"N/A"
            elif side == "sell" and self.is_sector_in_uptrend(etf_symbol):
                # Uptrend suggests hold; bearish suggests sell
                error = f"[SectorSentiment:{side}] Sector ETF {etf_symbol} is bearish."
                return False, error,"N/A"

            # 4. News sentiment evaluation

            headlines,avg_sent = self.get_cached_info(symbol)
            if headlines is None or avg_sent is None:
                if headlines is None:
                    headlines = aggregate_headlines_smart(ticker=symbol,ticker_name=name,rate_cache=self._rate_cache)                
            
                if headlines == []:
                    error = f"[SectorSentiment:{side}] No Headline data found"
                    return False,error,"N/A"
                
                if avg_sent is None:
                    avg_sent = self.average_news_sentiment(headlines)
                
                self.add_to_cache(symbol,headlines,avg_sent)
            
            if avg_sent is not None:
                if avg_sent < -0.1:
                    return False, f"SectorSentiment:{side}] Bearish sentiment","N/A"
                elif avg_sent > 0.1:
                    return True, f"SectorSentiment:{side}] Bullish sentiment","N/A"
                else:
                    return False, f"SectorSentiment:{side}] Neutral sentiment","N/A"


            # Default: no signal
            return True,"No Signaling","N/A" if side == "buy" else False, "No Signaling","N/A"

        except Exception as e:
            error = f"[SectorSentiment:{side} error] {e}"
            return False, error,"N/A"

    # === HELPER METHODS ===
    def normalize_sector(self,sector: str) -> str:
        """Normalize string for matching (lowercase, strip non-alpha)."""
        return re.sub(r'[^a-z]', '', sector.lower())


    def match_sector_to_etf(self, sector: str) -> str:
        """Return ETF symbol for a given sector, fallback to SPY if no match."""
        sector_norm = self.normalize_sector(sector)
        for key, val in ETF_LOOKUP.items():
            if self.normalize_sector(key) in sector_norm:
                return val

        # Fallback if no match
        logger = getLogger()
        logger.logMessage(f"[WARN] No ETF match found for sector: '{sector}', defaulting to SPY")
        return "SPY"
    
    
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
        results = self.sentiment_pipeline(combined_headlines, truncation=True)

        # Convert to +/- scores
        scores = []
        for r in results:
            score = float(r["score"])
            if r["label"] == "POSITIVE":
                scores.append(score)
            elif r["label"] == "NEGATIVE":
                scores.append(-score)
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
        if self._news_cache.is_cached(ticker):
            cached_value = self._news_cache.get(ticker)
            headlines = cached_value["headlines"]
            avg_sentiment = cached_value["avg_sentiment"]
            return headlines,avg_sentiment
        return None,None


    def get_symbol(self, obj: Union[OptionContract, Position]):
        if isinstance(obj, OptionContract):
            return obj.symbol
        elif isinstance(obj, Position):
            return obj.Product.get("symbol")
        else:
            raise TypeError(f"Unexpected type: {type(x)}")