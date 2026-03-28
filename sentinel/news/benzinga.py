import asyncio
import hashlib
from datetime import datetime, timezone

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.config import BENZINGA_API_KEY
from sentinel.models import NewsArticle

BENZINGA_BASE_URL = "https://api.benzinga.com/api/v2/news"


def _parse_benzinga_date(date_str: str) -> datetime:
    """Parse Benzinga date string to datetime."""
    from dateutil import parser as dateutil_parser
    try:
        dt = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.now(timezone.utc)


def _make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_articles_for_tickers(tickers: list[str], since: datetime) -> list[NewsArticle]:
    """Fetch news articles from Benzinga for the given tickers since the given datetime."""
    if not tickers:
        return []

    # Normalize since to UTC Unix timestamp
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    since_ts = int(since.timestamp())

    articles: list[NewsArticle] = []
    tickers_str = ",".join(tickers)

    params = {
        "token": BENZINGA_API_KEY,
        "tickers": tickers_str,
        "pageSize": 50,
        "updatedSince": since_ts,
        "displayOutput": "full",
    }

    async with aiohttp.ClientSession() as session:
        page = 0
        while True:
            params["page"] = page
            async with session.get(BENZINGA_BASE_URL, params=params) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Benzinga API error {resp.status}: {text}")
                data = await resp.json(content_type=None)

            # Benzinga returns a list directly or nested under a key
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = data.get("news", data.get("data", []))
            else:
                items = []

            if not items:
                break

            for item in items:
                url = item.get("url", "")
                if not url:
                    continue
                article_id = _make_article_id(url)
                title = item.get("title", "")
                summary = item.get("body", item.get("teaser", ""))
                # Extract ticker list from item
                item_tickers = []
                for stock in item.get("stocks", []):
                    sym = stock.get("name", "")
                    if sym:
                        item_tickers.append(sym)
                if not item_tickers:
                    item_tickers = tickers

                published_str = item.get("created", item.get("updated", ""))
                published_at = _parse_benzinga_date(published_str) if published_str else datetime.now(timezone.utc)

                articles.append(
                    NewsArticle(
                        article_id=article_id,
                        headline=title,
                        body=summary[:2000],
                        url=url,
                        source="benzinga",
                        tickers_mentioned=item_tickers,
                        published_at=published_at,
                    )
                )

            # If fewer than pageSize items returned, no more pages
            if len(items) < 50:
                break

            page += 1
            # Rate limit between paginated requests
            await asyncio.sleep(1)

    return articles
