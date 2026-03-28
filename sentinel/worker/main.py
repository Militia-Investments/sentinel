import asyncio
import structlog
import structlog.stdlib

from sentinel.config import (
    POLL_INTERVAL_SECONDS,
    RELEVANCE_THRESHOLD_LOW,
    RELEVANCE_THRESHOLD_MEDIUM,
    RELEVANCE_THRESHOLD_HIGH,
    SENTINEL_ADMIN_CHANNEL,
)
from sentinel.db import get_all_active_ideas
from sentinel.news.poller import poll_all_sources
from sentinel.analysis.relevance import score_relevance
from sentinel.analysis.impact import analyze_impact
from sentinel.analysis.kelly import calculate_kelly
from sentinel.slack.alerts import post_alert
from sentinel.slack.bot import app, handler
from sentinel.models import NewsSensitivity

# Configure structlog with JSON renderer for CloudWatch
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()


def get_threshold(sensitivity: NewsSensitivity) -> int:
    """Return the relevance score threshold for the given sensitivity level."""
    if sensitivity == NewsSensitivity.HIGH:
        return RELEVANCE_THRESHOLD_HIGH
    elif sensitivity == NewsSensitivity.MEDIUM:
        return RELEVANCE_THRESHOLD_MEDIUM
    else:
        return RELEVANCE_THRESHOLD_LOW


async def news_poll_loop() -> None:
    """Main polling loop: fetch news, score relevance, analyze impact, post alerts."""
    log.info("sentinel.poll_loop.starting", interval_seconds=POLL_INTERVAL_SECONDS)

    while True:
        try:
            log.info("sentinel.poll_loop.heartbeat")

            # Fetch all active ideas
            ideas = await get_all_active_ideas()
            if not ideas:
                log.info("sentinel.poll_loop.no_active_ideas")
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            log.info("sentinel.poll_loop.ideas_loaded", count=len(ideas))

            # Poll all news sources
            new_pairs = await poll_all_sources(ideas)
            log.info("sentinel.poll_loop.articles_fetched", count=len(new_pairs))

            if not new_pairs:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
                continue

            # Score relevance for all (article, idea) pairs concurrently
            relevance_tasks = [score_relevance(article, idea) for article, idea in new_pairs]
            relevance_scores = await asyncio.gather(*relevance_tasks, return_exceptions=True)

            # Filter by threshold and process sequentially for impact analysis
            for i, score_result in enumerate(relevance_scores):
                if isinstance(score_result, Exception):
                    log.warning("sentinel.relevance.error", error=str(score_result))
                    continue

                article, idea = new_pairs[i]
                threshold = get_threshold(idea.news_sensitivity)

                if score_result.score < threshold:
                    log.debug(
                        "sentinel.relevance.below_threshold",
                        score=score_result.score,
                        threshold=threshold,
                        article_id=article.article_id,
                        idea_id=idea.idea_id,
                    )
                    continue

                log.info(
                    "sentinel.relevance.above_threshold",
                    score=score_result.score,
                    threshold=threshold,
                    article_id=article.article_id,
                    idea_id=idea.idea_id,
                )

                # Analyze impact
                analysis = await analyze_impact(article, idea)
                if analysis is None:
                    log.warning(
                        "sentinel.impact.failed",
                        article_id=article.article_id,
                        idea_id=idea.idea_id,
                    )
                    continue

                # Calculate Kelly sizing
                kelly = calculate_kelly(analysis, idea)

                # Post alert to Slack
                try:
                    alert = await post_alert(app, idea, article, analysis, kelly)
                    log.info(
                        "sentinel.alert.posted",
                        alert_id=alert.alert_id,
                        idea_id=idea.idea_id,
                        urgency=analysis.urgency.value,
                        direction=analysis.direction.value,
                    )
                except Exception as exc:
                    log.error(
                        "sentinel.alert.post_failed",
                        error=str(exc),
                        article_id=article.article_id,
                        idea_id=idea.idea_id,
                    )
                    # Notify admin channel
                    try:
                        await app.client.chat_postMessage(
                            channel=SENTINEL_ADMIN_CHANNEL,
                            text=f":x: Failed to post alert for idea `{idea.idea_id}`: {exc}",
                        )
                    except Exception:
                        pass

        except Exception as exc:
            log.error("sentinel.poll_loop.exception", error=str(exc), exc_info=True)
            # Notify admin channel
            try:
                await app.client.chat_postMessage(
                    channel=SENTINEL_ADMIN_CHANNEL,
                    text=f":x: SENTINEL poll loop exception: {exc}",
                )
            except Exception:
                pass

        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def slack_loop() -> None:
    """Start the Slack Socket Mode handler."""
    log.info("sentinel.slack_loop.starting")
    await handler.start_async()


async def main() -> None:
    """Entry point: run both loops concurrently."""
    log.info("sentinel.starting")
    await asyncio.gather(news_poll_loop(), slack_loop())


if __name__ == "__main__":
    asyncio.run(main())
