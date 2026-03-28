import asyncio
import json

from anthropic import AsyncAnthropic

from sentinel.config import ANTHROPIC_API_KEY
from sentinel.models import NewsArticle, Idea, RelevanceScore

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

_SEMAPHORE = asyncio.Semaphore(10)


async def score_relevance(article: NewsArticle, idea: Idea) -> RelevanceScore:
    """Score the relevance of a news article to an investment idea using Claude Haiku."""
    prompt = f"""You are a financial news relevance filter.

Given an investment thesis and a news article, score how relevant the article is to the thesis on a scale of 0-10.

10 = Directly about the company/thesis, material impact likely
8-9 = Closely related, significant relevance
6-7 = Moderately relevant, some connection to thesis
4-5 = Tangentially related
2-3 = Weak connection
0-1 = Not relevant

Investment Thesis:
- Tickers: {", ".join(idea.tickers)}
- Thesis: {idea.thesis}
- Key Risks: {", ".join(idea.key_risks)}

News Article:
- Headline: {article.headline}
- Source: {article.source}
- Body: {article.body[:500]}

Respond with JSON only:
{{"score": <integer 0-10>, "rationale": "<brief explanation>"}}"""

    async with _SEMAPHORE:
        try:
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            score = int(parsed.get("score", 0))
            score = max(0, min(10, score))
            rationale = parsed.get("rationale", "")
        except Exception:
            score = 0
            rationale = "Failed to parse relevance score"

    return RelevanceScore(
        article_id=article.article_id,
        idea_id=idea.idea_id,
        score=score,
        rationale=rationale,
    )


async def score_relevance_batch(
    pairs: list[tuple[NewsArticle, Idea]]
) -> list[tuple[RelevanceScore, NewsArticle, Idea]]:
    """Score relevance for a batch of (article, idea) pairs concurrently (max 10 at once)."""
    tasks = [score_relevance(article, idea) for article, idea in pairs]
    scores = await asyncio.gather(*tasks, return_exceptions=True)

    results = []
    for i, score in enumerate(scores):
        if isinstance(score, Exception):
            article, idea = pairs[i]
            score = RelevanceScore(
                article_id=article.article_id,
                idea_id=idea.idea_id,
                score=0,
                rationale="Error during scoring",
            )
        article, idea = pairs[i]
        results.append((score, article, idea))

    return results
