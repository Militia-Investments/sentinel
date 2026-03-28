import hashlib
from datetime import datetime, timezone

import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.models import NewsArticle

GDELT_BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"


def _make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _parse_gdelt_date(date_str: str) -> datetime:
    """Parse GDELT date string (YYYYMMDDHHMMSS) to datetime."""
    try:
        dt = datetime.strptime(date_str, "%Y%m%d%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_articles_for_query(query_term: str, since: datetime) -> list[NewsArticle]:
    """Fetch articles from GDELT Doc API for a given query term."""
    if not query_term:
        return []

    params = {
        "query": query_term,
        "mode": "artlist",
        "maxrecords": 25,
        "format": "json",
        "timespan": "15min",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(GDELT_BASE_URL, params=params) as resp:
            if resp.status != 200:
                return []
            try:
                data = await resp.json(content_type=None)
            except Exception:
                return []

    if not data or not isinstance(data, dict):
        return []

    raw_articles = data.get("articles", [])
    if not raw_articles:
        return []

    articles: list[NewsArticle] = []
    for item in raw_articles:
        url = item.get("url", "")
        if not url:
            continue

        article_id = _make_article_id(url)
        title = item.get("title", "")
        # GDELT artlist doesn't return full body — use title as summary fallback
        summary = item.get("seendate", "")

        date_str = item.get("seendate", "")
        published_at = _parse_gdelt_date(date_str) if date_str else datetime.now(timezone.utc)

        # Filter out articles older than since
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        if since.tzinfo is None:
            since_aware = since.replace(tzinfo=timezone.utc)
        else:
            since_aware = since
        if published_at < since_aware:
            continue

        domain = item.get("domain", "")
        source_country = item.get("sourcecountry", "")
        language = item.get("language", "")

        articles.append(
            NewsArticle(
                article_id=article_id,
                headline=title,
                body=f"[{domain}] {title}" if domain else title,
                url=url,
                source="gdelt",
                tickers_mentioned=[],
                published_at=published_at,
            )
        )

    return articles
