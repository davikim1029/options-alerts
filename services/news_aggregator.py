# services/news_aggregator.py
"""
News aggregator + sentiment helper.

Exports:
 - aggregate_headlines_smart(ticker, ticker_name, rate_cache) -> list[Headline]
 - get_sentiment_signal(ticker, ticker_name, rate_cache) -> float  # [-1.0, 1.0]
 - Headline dataclass

Design:
 - Uses NewsAPI, NewsData, and Google News RSS (same sources your code used).
 - Applies rate-limit checks using provided RateLimitCache.
 - Provides hybrid sentiment: optional transformer pipeline (if enabled & available),
   otherwise a lightweight keyword+source weighting fallback.
 - Defensive: never raises to caller, always returns safe results.
"""

from dataclasses import dataclass
from typing import List, Optional
import os
import requests
import feedparser
import math
import re
from html import unescape
import re
from services.logging.logger_singleton import getLogger
from services.core.cache_manager import RateLimitCache,HeadlineCache
from services.scanner.scanner_utils import is_rate_limited

logger = getLogger()

# -------------------------------------------------------
# Headline model
# -------------------------------------------------------
@dataclass
class Headline:
    source: str
    title: str
    description: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[str] = None

    def combined_text(self) -> str:
        if self.description:
            return f"{self.title}. {self.description}"
        return self.title


# -------------------------------------------------------
# Clients (defensive, return [] if nothing / None on rate-limit)
# -------------------------------------------------------
class NewsClientBase:
    def __init__(self, rate_cache: Optional[RateLimitCache], logger):
        self.rate_cache = rate_cache
        self.logger = logger

    def fetch(self, ticker: str, ticker_name: str) -> Optional[List[Headline]]:
        raise NotImplementedError


class NewsAPIClient(NewsClientBase):
    def __init__(self, rate_cache, logger):
        super().__init__(rate_cache, logger)
        self.api_key = os.getenv("NEWSAPI_KEY")

    def fetch(self, ticker: str, ticker_name: str) -> Optional[List[Headline]]:
        if not self.api_key:
            self.logger.logMessage("[NewsAPI] API key missing; skipping NewsAPI")
            return []

        if self.rate_cache is not None and is_rate_limited(self.rate_cache, "NewsAPI"):
            return []
        
        news_sources_str = "bloomberg,reuters,the-wall-street-journal,cnbc,marketwatch,the-new-york-times,financial-times,forbes,business-insider,yahoo-news"

        url = "https://newsapi.org/v2/everything"
       
        keyword = ticker_name
        if ticker_name == "" or ticker_name is None:
            keyword = ticker
            
        params = {
            "q": f'{keyword}',          # wraps in quotes for exact matching
            "language": "en",
            "sources": news_sources_str,
            "sortBy": "publishedAt",
            "pageSize": 50,
            "apiKey": self.api_key
        }
        try:
            resp = requests.get(url, params=params)
            if resp.status_code == 429:
                self.logger.logMessage("[NewsAPI] Rate limited (429)")
                if self.rate_cache is not None:
                    self.rate_cache.add("NewsAPI", 3600 * 24)
                return None
            resp.raise_for_status()
            data = resp.json().get("articles", []) or []
            out = []
            for it in data:
                out.append(Headline(
                    source="newsapi",
                    title=it.get("title") or "",
                    description=it.get("description"),
                    url=it.get("url"),
                    published_at=it.get("publishedAt")
                ))
            return out
        except Exception as e:
            self.logger.logMessage(f"[NewsAPI] fetch error: {e}")
            return []


class NewsDataClient(NewsClientBase):
    def __init__(self, rate_cache, logger):
        super().__init__(rate_cache, logger)
        self.api_key = os.getenv("NEWSDATA_KEY")

    def fetch(self, ticker: str, ticker_name: str) -> Optional[List[Headline]]:
        if not self.api_key:
            self.logger.logMessage("[NewsData] API key missing; skipping NewsData")
            return []

        if self.rate_cache is not None and is_rate_limited(self.rate_cache, "NewsData"):
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
        try:
            resp = requests.get(url, params=params)
            if resp.status_code == 429:
                self.logger.logMessage("[NewsData] Rate limited (429)")
                if self.rate_cache is not None:
                    self.rate_cache.add("NewsData", 3600)
                return None
            resp.raise_for_status()
            items = resp.json().get("results", []) or []
            out = []
            for it in items:
                out.append(Headline(
                    source="newsdata",
                    title=it.get("title") or "",
                    description=it.get("description"),
                    url=it.get("link"),
                    published_at=it.get("pubDate") or it.get("date")
                ))
            return out
        except Exception as e:
            self.logger.logMessage(f"[NewsData] fetch error: {e}")
            return []


class GoogleNewsClient(NewsClientBase):
    def __init__(self, rate_cache, logger):
        super().__init__(rate_cache, logger)

    def _build_query_url(self, keywords: List[str]) -> str:
        query = "+OR+".join([k.replace(" ", "+") for k in keywords if k])
        return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    def fetch(self, ticker: str, ticker_name: str) -> Optional[List[Headline]]:
        query = ticker_name or ticker
        keywords = [query, "stock", "finance"]
        url = self._build_query_url(keywords)
        try:
            feed = feedparser.parse(url)
            out = []
            for entry in feed.entries:
                out.append(Headline(
                    source="google",
                    title=entry.title,
                    description=clean_description(getattr(entry, "summary", None)),
                    url=getattr(entry, "link", None),
                    published_at=getattr(entry, "published", None) or getattr(entry, "updated", None)
                ))
            return out
        except Exception as e:
            self.logger.logMessage(f"[GoogleNews] fetch error: {e}")
            return []


# -------------------------------------------------------
# Aggregator public function
# -------------------------------------------------------
def aggregate_headlines_smart(ticker: str, ticker_name: str, rate_cache: RateLimitCache = None) -> List[Headline]:
    """
    Aggregate headlines from prioritized sources.
    - Returns [] on failure or no articles.
    - Returns None only when a source indicates rate-limited (so caller can respect).
    """
    clients = [
        ("newsapi", NewsAPIClient(rate_cache, logger)),
        ("newsdata", NewsDataClient(rate_cache, logger)),
        ("google", GoogleNewsClient(rate_cache, logger)),
    ]

    aggregated: List[Headline] = []
    for name, client in clients:
        try:
            items = client.fetch(ticker, ticker_name)
        except Exception as e:
            logger.logMessage(f"[Aggregator] {name} fetch exception: {e}")
            items = []
        if items is None:
            # upstream rate-limited; stop and return None so caller can back off
            logger.logMessage(f"[Aggregator] {name} returned None (rate-limited); aborting further source calls")
            return None
        if items:
            aggregated.extend(items)

    return aggregated


# -------------------------------------------------------
# Sentiment computation (hybrid)
# - returns sentiment in [-1.0, 1.0]
# -------------------------------------------------------
# Keyword and source weights — small, explainable
KEYWORD_WEIGHTS = {
    "earnings": 0.18, "beat": 0.15, "miss": -0.2, "lawsuit": -0.35, "layoff": -0.2,
    "upgrade": 0.25, "downgrade": -0.25, "acquisition": 0.10, "bankruptcy": -0.45,
    "guidance": 0.08, "investigation": -0.25, "recall": -0.25, "partnership": 0.08,
    "growth": 0.12, "surge": 0.12, "drop": -0.12, "rally": 0.10, "decline": -0.12
}
SOURCE_WEIGHTS = {
    "newsapi": 1.2, "reuters": 1.2, "bloomberg": 1.2, "the-wall-street-journal": 1.1,
    "cnbc": 1.0, "marketwatch": 0.95, "financial-times": 1.1, "forbes": 0.9,
    "business-insider": 0.9, "yahoo-news": 0.8, "google": 0.9, "default": 1.0
}

# Optional transformer support — disable by default to avoid heavy deps
USE_TRANSFORMERS = os.getenv("USE_TRANSFORMERS", "false").lower() == "true"
_transformer_pipeline = None


def _load_transformer_pipeline():
    global _transformer_pipeline
    if _transformer_pipeline is not None:
        return _transformer_pipeline
    try:
        import transformers
        model_name = "distilbert/distilbert-base-uncased-finetuned-sst-2-english"
        tok = transformers.AutoTokenizer.from_pretrained(model_name)
        model = transformers.AutoModelForSequenceClassification.from_pretrained(model_name)
        _transformer_pipeline = transformers.pipeline("sentiment-analysis", model=model, tokenizer=tok, device=-1)
        logger.logMessage("[Sentiment] Transformer pipeline loaded")
    except Exception as e:
        logger.logMessage(f"[Sentiment] Transformer load failed: {e}")
        _transformer_pipeline = None
    return _transformer_pipeline


def compute_headlines_sentiment(headlines: List[Headline]) -> float:
    """
    Compute a sentiment score in [-1.0, 1.0] for a list of Headline objects.
    - If transformer pipeline available and USE_TRANSFORMERS True -> use it (batched).
    - Else use keyword + source weighting fallback.
    - Returns 0.0 neutral if no headlines or on error.
    """
    try:
        if not headlines:
            return 0.0

        texts = [h.combined_text()[:400] for h in headlines]

        # Transformer path (yields roughly -1..1 via mapping)
        if USE_TRANSFORMERS:
            pipeline = _load_transformer_pipeline()
            if pipeline:
                try:
                    results = pipeline(texts, truncation=True)
                    vals = []
                    for r in results:
                        label = r.get("label", "").upper()
                        score = float(r.get("score", 0.0))
                        if label == "POSITIVE":
                            vals.append(score)
                        elif label == "NEGATIVE":
                            vals.append(-score)
                        else:
                            vals.append(0.0)
                    if vals:
                        mean = sum(vals) / len(vals)
                        # ensure range [-1,1]
                        return float(max(-1.0, min(1.0, mean)))
                except Exception as e:
                    logger.logMessage(f"[Sentiment] Transformer scoring failed: {e}")

        # Fallback heuristic: keyword + source weight + recency weight
        weighted_scores = []
        total_weight = 0.0
        for h in headlines:
            text = h.combined_text().lower()
            kw_score = 0.0
            for kw, w in KEYWORD_WEIGHTS.items():
                if kw in text:
                    kw_score += w

            # lightweight lexical polarity fallback
            pos_hits = sum(1 for w in ("up", "gain", "beat", "rise", "surge", "rally") if w in text)
            neg_hits = sum(1 for w in ("down", "miss", "loss", "drop", "decline", "slump") if w in text)
            lex_score = 0.05 * (pos_hits - neg_hits)

            # source weight
            src = (h.source or "").lower()
            sw = SOURCE_WEIGHTS.get(src, SOURCE_WEIGHTS["default"])

            # recency weight (best-effort)
            rec_w = 1.0
            if h.published_at:
                try:
                    from datetime import datetime, timezone
                    pub = datetime.fromisoformat(h.published_at.replace("Z", "+00:00"))
                    age_days = max(0.0, (datetime.now(timezone.utc) - pub).days)
                    rec_w = math.exp(-age_days / 3.0)
                except Exception:
                    rec_w = 1.0

            combined = (kw_score + lex_score) * sw * rec_w
            weighted_scores.append(combined)
            total_weight += abs(sw * rec_w)

        if not weighted_scores or total_weight == 0:
            return 0.0

        avg = sum(weighted_scores) / len(weighted_scores)
        # clamp to [-1,1], but we expect values small so scale if needed
        if avg > 1.0: avg = 1.0
        if avg < -1.0: avg = -1.0
        return float(avg)

    except Exception as e:
        logger.logMessage(f"[Sentiment] compute_headlines_sentiment error: {e}")
        return 0.0


# -------------------------------------------------------
# Convenience: one-call sentiment getter used in scanner
# -------------------------------------------------------
def get_sentiment_signal(ticker: str, ticker_name: str = "", rate_cache: RateLimitCache = None,headline_cache: HeadlineCache = None) -> Optional[float]:
    """
    Fetch headlines and compute sentiment signal.
    Returns float in [-1,1] or None if upstream rate-limited (so caller can back off).
    """
    try:
        headlines = aggregate_headlines_smart(ticker, ticker_name, rate_cache=rate_cache)
        if headlines is None:
            # upstream told us to back off due to rate limits
            return None
        if not headlines:
            return 0.0
        headline_cache.add(ticker,strip_unwanted_fields(headlines))
        return compute_headlines_sentiment(headlines)
    except Exception as e:
        logger.logMessage(f"[Aggregator] get_sentiment_signal error for {ticker}: {e}")
        return 0.0

def clean_description(html_text: str) -> str:
    """Remove HTML tags, decode entities, and normalize whitespace."""
    import re
    from html import unescape

    if not html_text:
        return ""

    no_tags = re.sub(r"<.*?>", "", html_text)
    text = unescape(no_tags)

    # Replace non-breaking spaces and normalize multiple spaces
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def strip_unwanted_fields(headlines, drop_keys=None):
    drop_keys = set(drop_keys or ["url"])
    cleaned = []

    for h in headlines:
        if isinstance(h, dict):
            source = h
        else:
            source = vars(h)  # Get object attributes

        # Keep only wanted fields
        filtered = {k: v for k, v in source.items() if k not in drop_keys}
        cleaned.append(filtered)

    return cleaned
