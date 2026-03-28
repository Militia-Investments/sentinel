import json
from datetime import datetime, timezone
from typing import Optional

from anthropic import AsyncAnthropic

from sentinel.config import ANTHROPIC_API_KEY, SENTINEL_ADMIN_CHANNEL
from sentinel.models import (
    NewsArticle,
    Idea,
    ImpactAnalysis,
    ImpactDirection,
    RecommendedAction,
)
from sentinel.db import get_recent_alerts_for_idea

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def _summarize_recent_alerts(alerts) -> str:
    """Build a short text summary of recent alert history."""
    if not alerts:
        return "No recent alerts."
    lines = []
    for alert in alerts:
        lines.append(
            f"- [{alert.created_at.isoformat()[:10]}] {alert.direction} / {alert.urgency}"
            + (f" — PM response: {alert.pm_response}" if alert.pm_response else "")
        )
    return "\n".join(lines)


async def analyze_impact(article: NewsArticle, idea: Idea) -> Optional[ImpactAnalysis]:
    """Analyze the impact of a news article on an investment idea using Claude Sonnet."""
    # Get recent alerts for context
    try:
        recent_alerts = await get_recent_alerts_for_idea(idea.idea_id, limit=5)
        alerts_context = _summarize_recent_alerts(recent_alerts)
    except Exception:
        alerts_context = "Could not retrieve recent alert history."

    prompt = f"""You are a sophisticated financial analyst assessing the impact of news on an active investment position.

Investment Idea:
- Tickers: {", ".join(idea.tickers)}
- Thesis: {idea.thesis}
- Key Risks: {", ".join(idea.key_risks)}
- Current Position Size: ${idea.position_size_usd:,.0f}
- Conviction Score: {idea.conviction_score}/10

Recent Alert History:
{alerts_context}

New Article:
- Headline: {article.headline}
- Source: {article.source}
- Published: {article.published_at.isoformat()}
- Body: {article.body[:2000]}

Analyze this article's impact on the investment thesis and respond with JSON only:
{{
  "direction": "<confirms_thesis|threatens_thesis|neutral|stop_thesis>",
  "urgency": "<critical|high|medium|low>",
  "narrative": "<2-3 sentence summary of the impact>",
  "action": "<hold|add|reduce|exit>",
  "suggested_resize_pct": <float between 0 and 1, percentage of position to add/reduce>,
  "confidence": <float between 0 and 1>
}}

Guidelines:
- direction "stop_thesis" means the core thesis is broken; suggest exit
- urgency "critical" means immediate attention required (stop loss hit, major adverse event)
- suggested_resize_pct is the fraction of current position to add or reduce (e.g., 0.2 = 20%)
- confidence reflects how certain you are about the impact assessment"""

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)

        direction = ImpactDirection(parsed.get("direction", "neutral"))
        urgency = str(parsed.get("urgency", "low"))
        action = RecommendedAction(parsed.get("action", "hold"))
        suggested_resize_pct = float(parsed.get("suggested_resize_pct", 0.0))
        confidence = float(parsed.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
        narrative = parsed.get("narrative", "")

        return ImpactAnalysis(
            article_id=article.article_id,
            idea_id=idea.idea_id,
            direction=direction,
            urgency=urgency,
            narrative=narrative,
            action=action,
            suggested_resize_pct=suggested_resize_pct,
            confidence=confidence,
            created_at=datetime.now(timezone.utc),
        )

    except Exception as exc:
        # Log failure to admin channel (best effort — we import app lazily to avoid circular)
        try:
            from sentinel.slack.bot import app as slack_app
            await slack_app.client.chat_postMessage(
                channel=SENTINEL_ADMIN_CHANNEL,
                text=f":x: Impact analysis failed for article `{article.article_id}` / idea `{idea.idea_id}`: {exc}",
            )
        except Exception:
            pass
        return None
