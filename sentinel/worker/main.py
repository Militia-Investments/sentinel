import asyncio
import structlog
import structlog
import uvicorn
from sentinel.config import POLL_INTERVAL_SECONDS, RELEVANCE_THRESHOLD_LOW, RELEVANCE_THRESHOLD_MEDIUM, RELEVANCE_THRESHOLD_HIGH, SENTINEL_ADMIN_SPACE
from sentinel.db import get_all_active_ideas
from sentinel.news.poller import poll_all_sources
from sentinel.analysis.relevance import score_relevance
from sentinel.analysis.impact import analyze_impact
from sentinel.analysis.kelly import calculate_kelly
from sentinel.gchat.alerts import post_alert
from sentinel.gchat.client import chat
from sentinel.models import NewsSensitivity
import asyncio

log = structlog.get_logger()

# Configure structlog for CloudWatch JSON output
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ]
)


def get_threshold(sensitivity: NewsSensitivity) -> int:
    return {
        NewsSensitivity.LOW: RELEVANCE_THRESHOLD_LOW,
        NewsSensitivity.MEDIUM: RELEVANCE_THRESHOLD_MEDIUM,
        NewsSensitivity.HIGH: RELEVANCE_THRESHOLD_HIGH,
    }[sensitivity]


async def _post_admin_message(text: str) -> None:
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: chat.spaces().messages().create(
                parent=SENTINEL_ADMIN_SPACE,
                body={"text": text}
            ).execute()
        )
    except Exception:
        pass


async def news_poll_loop():
    while True:
        try:
            log.info("sentinel.poll.start")
            ideas = await get_all_active_ideas()

            if not ideas:
                log.info("sentinel.poll.no_active_ideas")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            article_idea_pairs = await poll_all_sources(ideas)
            log.info("sentinel.poll.fetched", article_count=len(article_idea_pairs))

            if not article_idea_pairs:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Relevance filter — up to 10 concurrent Haiku calls
            semaphore = asyncio.Semaphore(10)
            async def score_with_sem(article, idea):
                async with semaphore:
                    return await score_relevance(article, idea)

            relevance_scores = await asyncio.gather(*[
                score_with_sem(article, idea)
                for article, idea in article_idea_pairs
            ])

            to_analyze = [
                (article, idea)
                for (article, idea), score in zip(article_idea_pairs, relevance_scores)
                if score.score >= get_threshold(idea.news_sensitivity)
            ]

            log.info("sentinel.poll.to_analyze", count=len(to_analyze))

            # Impact analysis — sequential to control Sonnet spend
            for article, idea in to_analyze:
                try:
                    analysis = await analyze_impact(article, idea)
                    if analysis is None:
                        continue
                    kelly = calculate_kelly(analysis, idea)
                    await post_alert(idea, article, analysis, kelly)
                    log.info("sentinel.alert.posted", idea_id=idea.idea_id, article_id=article.article_id)
                except Exception as e:
                    log.error("sentinel.alert.failed", idea_id=idea.idea_id, error=str(e))
                    await _post_admin_message(f"⚠️ Alert failed for idea `{idea.idea_id[:8]}`: {e}")

            log.info("sentinel.poll.heartbeat", ideas=len(ideas), analyzed=len(to_analyze))

        except Exception as e:
            log.error("sentinel.poll.loop_error", error=str(e))
            await _post_admin_message(f"🔴 Poll loop error: {e}")

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def web_server_loop():
    """Run FastAPI/uvicorn as an async task."""
    from sentinel.gchat.bot import app as fastapi_app
    config = uvicorn.Config(fastapi_app, host="0.0.0.0", port=8080, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    log.info("sentinel.starting")
    await asyncio.gather(
        news_poll_loop(),
        web_server_loop(),
    )


if __name__ == "__main__":
    asyncio.run(main())
