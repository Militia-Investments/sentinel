import asyncio
import hashlib
from datetime import datetime, timezone

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import FINNHUB_API_KEY
from sentinel.models import NewsArticle

FINNHUB_BASE_URL = "https://finnhub.io/api/v1/company-news"

# Finnhub free tier: 60 req/min. One request per ticker — sleep 1s between
# tickers to stay comfortably within limits.
_REQUEST_DELAY = 1.0


def _make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def _fetch_ticker(session: aiohttp.ClientSession, ticker: str, since: datetime) -> list[NewsArticle]:
    """Fetch news for a single ticker from the Finnhub company-news endpoint."""
    now = datetime.now(timezone.utc)
    params = {
        "symbol": ticker,
        "from": since.strftime("%Y-%m-%d"),
        "to": now.strftime("%Y-%m-%d"),
        "token": FINNHUB_API_KEY,
    }
    async with session.get(FINNHUB_BASE_URL, params=params) as resp:
        if resp.status == 429:
            raise RuntimeError("Finnhub rate limit hit")
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Finnhub API error {resp.status}: {text}")
        items = await resp.json(content_type=None)

    if not isinstance(items, list):
        return []

    articles: list[NewsArticle] = []
    for item in items:
        url = item.get("url", "")
        if not url:
            continue

        ts = item.get("datetime", 0)
        published_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else now

        # Filter to articles published strictly after `since`
        if published_at <= since:
            continue

        related = item.get("related", "")
        tickers_mentioned = [t.strip() for t in related.split(",") if t.strip()] if related else [ticker]

        articles.append(NewsArticle(
            article_id=_make_article_id(url),
            source="finnhub",
            headline=item.get("headline", ""),
            body=item.get("summary", "")[:2000],
            url=url,
            published_at=published_at,
            tickers_mentioned=tickers_mentioned,
        ))

    return articles


async def fetch_articles_for_tickers(tickers: list[str], since: datetime) -> list[NewsArticle]:
    """Fetch Finnhub company news for all tickers, one request per ticker."""
    if not tickers:
        return []

    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    all_articles: list[NewsArticle] = []
    seen_ids: set[str] = set()

    async with aiohttp.ClientSession() as session:
        for i, ticker in enumerate(tickers):
            if i > 0:
                await asyncio.sleep(_REQUEST_DELAY)
            try:
                articles = await _fetch_ticker(session, ticker, since)
                for a in articles:
                    if a.article_id not in seen_ids:
                        seen_ids.add(a.article_id)
                        all_articles.append(a)
            except Exception:
                continue

    return all_articles
