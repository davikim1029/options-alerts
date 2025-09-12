import os
import requests
import feedparser
from services.core.cache_manager import RateLimitCache
from typing import List, Dict, Optional
from services.logging.logger_singleton import getLogger
from dataclasses import dataclass
from abc import ABC, abstractmethod


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
    def __init__(self,rate_cache,logger):
        self.rate_cache = rate_cache
        api_key = os.getenv("NEWSAPI_KEY")
        if not api_key:
            raise ValueError("NEWSAPI_KEY not set in environment.")
        self.api_key = api_key

    def fetch(self, ticker: str) -> Optional[List[Dict]]:
        
        news_sources = [
            "bloomberg.com", "reuters.com", "wsj.com", "cnbc.com", "marketwatch.com",
            "nytimes.com", "ft.com", "forbes.com", "businessinsider.com", "yahoo.com"
        ]
        news_sources_str = ",".join(news_sources)
        if self.rate_cache is not None and self.rate_cache.is_cached(f"NewsAPI:{ticker}"):
            return None

        url = f"https://newsapi.org/v2/everything?q={ticker}&language=en&sources={news_sources_str}"
        resp = requests.get(url, headers={"Authorization": f"Bearer {self.api_key}"})
        if resp.status_code == 429:
            logger.logMessage("[NewsAPI] Rate limit hit")
            if self.rate_cache is not None:
                self.rate_cache.add(f"NewsAPI:{ticker}", 24*3600)  # reset daily
            return None
        if resp.status_code != 200:
            return None
        
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
        return headlines  


class NewsDataClient(NewsClient):
    def __init__(self,rate_cache:RateLimitCache,logger):
        self.rate_cache = rate_cache
        self.api_key = os.getenv("NEWSDATA_KEY")

    def fetch(self, ticker: str) -> Optional[List[Dict]]:
        if self.rate_cache is not None and self.rate_cache.is_cached(f"NewsData:{ticker}"):
            return None
        
        categories = ["business"]  # could add more later, e.g., ["business", "technology"]
        categories_str = ",".join(categories)

        url = f"https://newsdata.io/api/1/news?apikey={self.api_key}&q={ticker}&language=en&category={categories_str}"
        resp = requests.get(url)
        if resp.status_code == 429:
            logger.logMessage("[NewsData] Rate limit hit")
            if self.rate_cache is not None:
                self.rate_cache.add(f"NewsData:{ticker}", 3600)  # assume hourly reset
            return None
        if resp.status_code != 200:
            return None
        
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
        return headlines    

class GoogleNewsClient(NewsClient):
    def __init__(self,rate_cache):
        self.rate_cache = rate_cache
        
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
        
        
    def fetch(self, ticker: str) -> List[Dict]:
        cache_key = f"GoogleNews:{ticker}"
        if self.rate_cache is not None and self.rate_cache.is_cached(cache_key):
            return self.rate_cache.get(cache_key)
        
        keywords = [ticker, "stock", "shares", "finance"]
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
        return headlines 


# --------------------------
# Smart Aggregator
# --------------------------
def aggregate_headlines_smart(ticker: str, rate_cache:RateLimitCache = None) -> List[Dict]:
    logger = getLogger()
    sources_priority = [
        ("NewsAPI", NewsAPIClient(rate_cache=rate_cache,logger=logger), True),
        ("NewsData", NewsDataClient(rate_cache=rate_cache,logger=logger), True),
        ("GoogleNewsRSS", GoogleNewsClient(rate_cache=rate_cache,logger=logger), False),
    ]

    new_articles = []
    for name, news_client, rate_limited in sources_priority:
        if rate_cache is not None and rate_cache.is_cached(f"{name}:{ticker}"):
            continue
        
        try:
            articles = news_client.fetch(ticker)
        except Exception as e:
            logger.logMessage(f"Error fetching news data: {e}")
            
        if articles:
            new_articles.extend(articles)

            if rate_limited and rate_cache is not None:
                rate_cache.add(f"{name}:{ticker}", 300)  # avoid hammering ticker-source combo
                break

    return new_articles
