import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser
from tenacity import retry, stop_after_attempt, wait_exponential

from sentinel.models import NewsArticle

# Non-US exchange suffixes to exclude
NON_US_SUFFIXES = {"JP", "MM", "FP", "SW", "HK", "LN", "GR", "SS"}

EDGAR_BASE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

# SEC requires a User-Agent header
EDGAR_HEADERS = {
    "User-Agent": "SENTINEL/1.0 sentinel-ops@example.com",
    "Accept-Encoding": "gzip, deflate",
}


def _is_us_ticker(ticker: str) -> bool:
    """Return True if the ticker appears to be US-listed (no non-US suffix)."""
    parts = ticker.upper().split(".")
    if len(parts) > 1 and parts[-1] in NON_US_SUFFIXES:
        return False
    return True


def _make_article_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()


def _parse_entry_date(entry) -> datetime:
    """Parse the published date from a feedparser entry."""
    from dateutil import parser as dateutil_parser
    for attr in ("published", "updated"):
        val = getattr(entry, attr, None)
        if val:
            try:
                dt = dateutil_parser.parse(val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(timezone.utc)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def _fetch_ticker_filings(ticker: str, session: aiohttp.ClientSession) -> list[NewsArticle]:
    """Fetch 8-K filings from EDGAR RSS feed for a single ticker."""
    params = {
        "action": "getcompany",
        "CIK": ticker,
        "type": "8-K",
        "dateb": "",
        "owner": "include",
        "count": "20",
        "output": "atom",
    }
    url = EDGAR_BASE_URL
    async with session.get(url, params=params, headers=EDGAR_HEADERS) as resp:
        if resp.status != 200:
            return []
        content = await resp.text()

    feed = feedparser.parse(content)
    articles: list[NewsArticle] = []

    for entry in feed.entries:
        link = getattr(entry, "link", "") or ""
        if not link:
            # Try alternate link
            links = getattr(entry, "links", [])
            for lk in links:
                if lk.get("rel") == "alternate":
                    link = lk.get("href", "")
                    break

        if not link:
            continue

        article_id = _make_article_id(link)
        title = getattr(entry, "title", f"SEC 8-K Filing: {ticker}")
        summary = getattr(entry, "summary", getattr(entry, "description", ""))
        published_at = _parse_entry_date(entry)

        articles.append(
            NewsArticle(
                article_id=article_id,
                headline=title,
                body=summary[:2000],
                url=link,
                source="edgar",
                tickers_mentioned=[ticker],
                published_at=published_at,
            )
        )

    return articles


async def fetch_filings_for_tickers(tickers: list[str]) -> list[NewsArticle]:
    """Fetch SEC 8-K filings for US-listed tickers."""
    us_tickers = [t for t in tickers if _is_us_ticker(t)]
    if not us_tickers:
        return []

    articles: list[NewsArticle] = []
    async with aiohttp.ClientSession() as session:
        tasks = [_fetch_ticker_filings(ticker, session) for ticker in us_tickers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                continue
            articles.extend(result)

    return articles
