import asyncio
from datetime import datetime, timezone

from sentinel.models import Idea, NewsArticle
from sentinel.db import save_article, article_exists
from sentinel.news.finnhub import fetch_articles_for_tickers
from sentinel.news.edgar import fetch_filings_for_tickers
from sentinel.news.gdelt import fetch_articles_for_query

# Track last poll time per idea_id in memory
_last_poll_time: dict[str, datetime] = {}


async def _poll_idea(idea: Idea) -> list[tuple[NewsArticle, Idea]]:
    """Poll all three news sources for a single idea and return new (article, idea) pairs."""
    now = datetime.now(timezone.utc)
    since = _last_poll_time.get(idea.idea_id, now)

    # Gather from all sources in parallel
    benzinga_task = fetch_articles_for_tickers(idea.tickers, since)
    edgar_task = fetch_filings_for_tickers(idea.tickers)

    async def _empty() -> list:
        return []

    gdelt_task = (
        fetch_articles_for_query(idea.gdelt_query_term, since)
        if idea.gdelt_query_term
        else _empty()
    )

    results = await asyncio.gather(
        benzinga_task,
        edgar_task,
        gdelt_task,
        return_exceptions=True,
    )

    all_articles: list[NewsArticle] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        if isinstance(result, list):
            all_articles.extend(result)

    # Dedup: skip articles already in DynamoDB
    new_pairs: list[tuple[NewsArticle, Idea]] = []
    for article in all_articles:
        exists = await article_exists(article.article_id)
        if not exists:
            await save_article(article)
            new_pairs.append((article, idea))

    # Update last poll time
    _last_poll_time[idea.idea_id] = now

    return new_pairs


async def poll_all_sources(ideas: list[Idea]) -> list[tuple[NewsArticle, Idea]]:
    """Poll all sources for all active ideas and return new (article, idea) pairs."""
    if not ideas:
        return []

    # Poll all ideas concurrently
    tasks = [_poll_idea(idea) for idea in ideas]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_new_pairs: list[tuple[NewsArticle, Idea]] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        all_new_pairs.extend(result)

    return all_new_pairs
