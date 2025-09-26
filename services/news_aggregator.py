import os
import requests
import feedparser
from services.core.cache_manager import RateLimitCache,NewsApiCache
from typing import List, Dict, Optional
from services.logging.logger_singleton import getLogger
from dataclasses import dataclass
from abc import ABC, abstractmethod
from services.scanner.scanner_utils import is_rate_limited


# --------------------------
# Models
# --------------------------
@dataclass
class Headline:
    source: str
    title: str
    description: Optional[str] = None
    url: Optional[str] = None

    def combined_text(self) -> str:
        """Return a normalized text for sentiment analysis."""
        if self.description:
            return f"{self.title}. {self.description}"
        return self.title


# --------------------------
# Clients
# --------------------------

class NewsClient:
    @abstractmethod
    def fetch(self, ticker: str):
        pass
    

class NewsAPIClient(NewsClient):
    def __init__(self,rate_cache,news_cache,logger):
        self.rate_cache = rate_cache
        self.news_cache = news_cache
        self.logger = logger
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            raise ValueError("NEWSAPI_KEY not set in environment.")
        self.api_key = api_key

    def fetch(self, ticker: str,ticker_name:str) -> Optional[List[Dict]]:
        
        cache_key = f"NewsAPI:{ticker}"
        if self.news_cache is not None and self.news_cache.is_cached(cache_key):
            return self.news_cache.get(cache_key)
        
        if self.rate_cache is not None and is_rate_limited(self.rate_cache,"NewsAPI"):
            return []
        
        news_sources_str = "bloomberg,reuters,the-wall-street-journal,cnbc,marketwatch,the-new-york-times,financial-times,forbes,business-insider,yahoo-news"

        url = "https://newsapi.org/v2/everything"        
        
        keyword = ticker_name
        if ticker_name == "" or ticker_name is None:
            keyword = ticker
            

        params = {
            "q": f'"{keyword}"',          # wraps in quotes for exact matching
            "language": "en",
            "sources": news_sources_str,
            "apiKey": self.api_key        # note: NewsAPI expects `apiKey` not `apikey`
        }
        resp = requests.get(url,params=params)
        if resp.status_code == 429:
            self.logger.logMessage("[NewsAPI] Rate limit hit")
            if self.rate_cache is not None:
                self.rate_cache.add("NewsAPI", 24*3600)  # reset daily
                self.rate_cache._save_cache()
            return None
        if resp.status_code != 200:
            if hasattr(resp.content):
                raise Exception(str(resp.content))
            else:
                raise Exception(str(resp))
        
        results = resp.json().get("articles", [])
        headlines = []
        for r in results:
            headlines.append(
                Headline(
                    source="NewsAPI",
                    title=r.get("title", ""),
                    description=r.get("description"),
                    url=r.get("url")
                )
            )
        if len(headlines) > 0:
            self.news_cache.add(cache_key,headlines)
        return headlines  


class NewsDataClient(NewsClient):
    def __init__(self,rate_cache:RateLimitCache,news_cache:NewsApiCache,logger):
        self.logger = logger
        self.rate_cache = rate_cache
        self.news_cache = news_cache
        self.api_key = os.getenv("NEWSDATA_KEY")

    def fetch(self, ticker: str,ticker_name:str) -> Optional[List[Dict]]:
        cache_key = f"NewsData:{ticker}"
        if self.news_cache is not None and self.news_cache.is_cached(cache_key):
            return self.news_cache.get(cache_key)
        
        if self.rate_cache is not None and is_rate_limited(self.rate_cache,"NewsData"):
            return []
        
        categories = [
            "business",
            "technology",
        ]
        categories_str = ",".join(categories)

        url = "https://newsdata.io/api/1/news"
        keyword = ticker_name
        if ticker_name == "" or ticker_name is None:
            keyword = ticker
            
        params = {
            "apikey": self.api_key,
            "q": f'"{keyword}"',  # safely quoted
            "language": "en",
            "category": categories_str,
        }
        resp = requests.get(url,params=params)
        if resp.status_code == 429:
            self.logger.logMessage("[NewsData] Rate limit hit")
            if self.rate_cache is not None:
                self.rate_cache.add(f"NewsData", 3600)  # assume hourly reset
                self.rate_cache._save_cache()
                
            return None
        if resp.status_code != 200:
            if hasattr(resp.content):
                raise Exception(str(resp.content))
            else:
                raise Exception(str(resp))
        
        results = resp.json().get("results", [])
        headlines = []
        for r in results:
            headlines.append(
                Headline(
                    source="NewsData",
                    title=r.get("title", ""),
                    description=r.get("description"),
                    url=r.get("link")
                )
            )
        if len(headlines) > 0:
            self.news_cache.add(cache_key,headlines)
        return headlines    

class GoogleNewsClient(NewsClient):
    def __init__(self,rate_cache,news_cache,logger):
        self.logger=logger
        self.rate_cache = rate_cache
        self.news_cache = news_cache
        
    def _build_query_url(self, keywords: list[str]) -> str:
        """
        Build the Google News RSS URL based on a list of keywords.
        Keywords are combined using OR and spaces are encoded as '+'.
        """
        if not keywords:
            raise ValueError("Keywords list cannot be empty.")

        # encode keywords: join with ' OR ' and replace spaces with '+'
        query = "+OR+".join([k.replace(" ", "+") for k in keywords])
        return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        
        
    def fetch(self, ticker: str,ticker_name:str) -> List[Dict]:
        cache_key = f"GoogleNews:{ticker}"

        if self.news_cache is not None and self.news_cache.is_cached(cache_key):
            return self.news_cache.get(cache_key)
        
        keywords = [ticker_name, "stock", "shares", "finance"]
        url = self._build_query_url(keywords)
        feed = feedparser.parse(url)
        headlines = []
        for entry in feed.entries:
            headlines.append(
                Headline(
                    source="GoogleNews",
                    title=entry.title,
                    description=getattr(entry, "summary", ""),  # may not always exist
                    url=entry.link
                )
            )
        if len(headlines) > 0:
            self.news_cache.add(cache_key,headlines)
        return headlines 


# --------------------------
# Smart Aggregator
# --------------------------
def aggregate_headlines_smart(ticker: str,ticker_name: str, rate_cache:RateLimitCache = None, news_cache:NewsApiCache = None) -> List[Dict]:
    logger = getLogger()
    sources_priority = [
        ("NewsAPI", NewsAPIClient(rate_cache=rate_cache,news_cache=news_cache,logger=logger), True),
        ("NewsData", NewsDataClient(rate_cache=rate_cache,news_cache=news_cache,logger=logger), True),
        ("GoogleNewsRSS", GoogleNewsClient(rate_cache=rate_cache,news_cache=news_cache,logger=logger), False),
    ]

    new_articles = []
    for name, news_client, rate_limited in sources_priority:  
        try:
            articles = news_client.fetch(ticker=ticker,ticker_name=ticker_name)
        except Exception as e:
            logger.logMessage(f"Error fetching news from {name}: {e}")
            
        if articles is not None and len(articles) > 0:
            new_articles.extend(articles)

    return new_articles
