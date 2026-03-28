import uuid
from datetime import datetime, timezone

from slack_bolt.async_app import AsyncApp

from sentinel.models import (
    Idea,
    NewsArticle,
    ImpactAnalysis,
    KellyRecommendation,
    AlertRecord,
    ImpactDirection,
    RecommendedAction,
)
from sentinel.db import save_alert

URGENCY_EMOJI = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "⚪",
}

DIRECTION_ICON = {
    "confirms_thesis": "✅",
    "threatens_thesis": "⚠️",
    "neutral": "➡️",
    "stop_thesis": "🛑",
}

ACTION_LABEL = {
    "hold": "Hold",
    "add": "Add to Position",
    "reduce": "Reduce Position",
    "exit": "Exit Position",
}


def build_alert_blocks(
    idea: Idea,
    article: NewsArticle,
    analysis: ImpactAnalysis,
    kelly: KellyRecommendation,
    alert_id: str,
) -> list[dict]:
    """Build Slack Block Kit message blocks for a SENTINEL alert."""
    urgency_emoji = URGENCY_EMOJI.get(analysis.urgency, "⚪")
    direction_icon = DIRECTION_ICON.get(analysis.direction.value, "➡️")
    action_label = ACTION_LABEL.get(analysis.action.value, analysis.action.value.title())

    tickers_str = ", ".join(f"`{t}`" for t in idea.tickers)

    # Format Kelly recommendation
    if kelly.delta_usd == 0:
        kelly_text = f"*Hold* — Maintain current position of ${kelly.current_position_usd:,.0f}"
    elif kelly.suggested_new_position_usd == 0.0:
        kelly_text = f"*Exit* — Close full position of ${kelly.current_position_usd:,.0f}"
    else:
        direction_word = "Increase" if kelly.delta_usd > 0 else "Decrease"
        kelly_text = (
            f"*{action_label}* — {direction_word} from "
            f"${kelly.current_position_usd:,.0f} → ${kelly.suggested_new_position_usd:,.0f} "
            f"({abs(kelly.fractional_kelly_pct) * 100:.1f}% fractional Kelly)"
        )

    blocks = [
        # Header
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{urgency_emoji} SENTINEL Alert — {analysis.urgency.upper()}",
                "emoji": True,
            },
        },
        # Direction + narrative
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{direction_icon} *{analysis.direction.value.replace('_', ' ').title()}*\n"
                    f"{analysis.narrative}"
                ),
            },
        },
        # Article details
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Tickers:*\n{tickers_str}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Source:*\n{article.source.title()}",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Confidence:*\n{analysis.confidence * 100:.0f}%",
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Published:*\n{article.published_at.strftime('%Y-%m-%d %H:%M UTC')}",
                },
            ],
        },
        # Article link
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Article:* <{article.url}|{article.headline}>",
            },
        },
        {"type": "divider"},
        # Kelly recommendation
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Recommended Action:*\n{kelly_text}",
            },
        },
        {"type": "divider"},
        # Action buttons
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Agree",
                        "emoji": True,
                    },
                    "style": "primary",
                    "action_id": f"sentinel_agree_{alert_id}",
                    "value": alert_id,
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✏️ Custom Resize",
                        "emoji": True,
                    },
                    "action_id": f"sentinel_custom_{alert_id}",
                    "value": alert_id,
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "⚙️ Sensitivity",
                        "emoji": True,
                    },
                    "action_id": f"sentinel_sensitivity_{idea.idea_id}",
                    "value": idea.idea_id,
                },
            ],
        },
        # Context footer
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"Alert ID: `{alert_id}` | "
                        f"Idea ID: `{idea.idea_id}` | "
                        f"Article ID: `{article.article_id}`"
                    ),
                }
            ],
        },
    ]

    return blocks


async def post_alert(
    app: AsyncApp,
    idea: Idea,
    article: NewsArticle,
    analysis: ImpactAnalysis,
    kelly: KellyRecommendation,
) -> AlertRecord:
    """Post an alert to the idea's Slack channel and save the AlertRecord."""
    alert_id = str(uuid.uuid4())
    blocks = build_alert_blocks(idea, article, analysis, kelly, alert_id)

    # Post to the idea's dedicated channel
    response = await app.client.chat_postMessage(
        channel=idea.channel_id,
        text=(
            f"{URGENCY_EMOJI.get(analysis.urgency, '⚪')} "
            f"SENTINEL Alert: {analysis.direction.value.replace('_', ' ').title()} — "
            f"{article.headline[:100]}"
        ),
        blocks=blocks,
    )

    slack_message_ts = response.get("ts", "")

    alert = AlertRecord(
        alert_id=alert_id,
        idea_id=idea.idea_id,
        article_id=article.article_id,
        slack_message_ts=slack_message_ts,
        created_at=datetime.now(timezone.utc),
    )

    await save_alert(alert)
    return alert
