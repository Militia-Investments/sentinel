import uuid
from datetime import datetime, timezone
from sentinel.gchat.client import chat
from sentinel.models import Idea, NewsArticle, ImpactAnalysis, KellyRecommendation, AlertRecord
from sentinel.db import save_alert
from sentinel.config import SENTINEL_ADMIN_SPACE
import structlog

log = structlog.get_logger()

URGENCY_EMOJI = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
DIRECTION_ICON = {
    "confirms_thesis": "✅",
    "threatens_thesis": "⚠️",
    "neutral": "➡️",
    "stop_thesis": "🛑",
}

def build_alert_card(idea: Idea, article: NewsArticle, analysis: ImpactAnalysis, kelly: KellyRecommendation, alert_id: str) -> dict:
    """Build a Google Chat Cards v2 card for a SENTINEL alert."""
    urgency_emoji = URGENCY_EMOJI.get(analysis.urgency, "⚪")
    direction_icon = DIRECTION_ICON.get(analysis.direction.value, "➡️")

    # Kelly sizing text
    if kelly.delta_usd == 0:
        kelly_text = f"Hold — maintain ${kelly.current_position_usd:,.0f}"
    elif kelly.delta_usd > 0:
        kelly_text = f"Add: ${kelly.current_position_usd:,.0f} → ${kelly.suggested_new_position_usd:,.0f} (+{kelly.fractional_kelly_pct:.1%})"
    else:
        kelly_text = f"Reduce: ${kelly.current_position_usd:,.0f} → ${kelly.suggested_new_position_usd:,.0f} ({kelly.fractional_kelly_pct:.1%})"

    return {
        "cardsV2": [{
            "cardId": f"sentinel_alert_{alert_id}",
            "card": {
                "header": {
                    "title": f"{urgency_emoji} SENTINEL Alert — {analysis.urgency.upper()}",
                    "subtitle": article.headline,
                },
                "sections": [
                    {
                        "header": f"{direction_icon} {analysis.direction.value.replace('_', ' ').title()}",
                        "widgets": [
                            {"textParagraph": {"text": analysis.narrative}},
                            {
                                "columns": {
                                    "columnItems": [
                                        {
                                            "horizontalSizeStyle": "FILL_AVAILABLE_SPACE",
                                            "widgets": [
                                                {"decoratedText": {"topLabel": "Action", "text": f"<b>{analysis.action.value.upper()}</b>"}},
                                                {"decoratedText": {"topLabel": "Confidence", "text": f"{analysis.confidence:.0%}"}},
                                            ]
                                        },
                                        {
                                            "horizontalSizeStyle": "FILL_AVAILABLE_SPACE",
                                            "widgets": [
                                                {"decoratedText": {"topLabel": "Tickers", "text": ", ".join(idea.tickers)}},
                                                {"decoratedText": {"topLabel": "Source", "text": f"<a href=\"{article.url}\">{article.source}</a>"}},
                                            ]
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    {
                        "header": "📊 Kelly Sizing Recommendation",
                        "widgets": [
                            {"textParagraph": {"text": kelly_text}},
                            {"textParagraph": {
                                "text": f"<i>Basis: {analysis.confidence:.0%} confidence × {abs(analysis.suggested_resize_pct):.0%} signal × 0.25 multiplier = {kelly.fractional_kelly_pct:.1%} fractional Kelly</i>"
                            }},
                            {
                                "buttonList": {
                                    "buttons": [
                                        {
                                            "text": "✅ Agree with sizing",
                                            "color": {"red": 0.204, "green": 0.659, "blue": 0.325},
                                            "onClick": {
                                                "action": {
                                                    "function": "sentinel_agree",
                                                    "parameters": [
                                                        {"key": "alert_id", "value": alert_id},
                                                        {"key": "idea_id", "value": idea.idea_id},
                                                    ]
                                                }
                                            }
                                        },
                                        {
                                            "text": "✏️ Set my own %",
                                            "onClick": {
                                                "action": {
                                                    "function": "sentinel_custom",
                                                    "parameters": [
                                                        {"key": "alert_id", "value": alert_id},
                                                        {"key": "idea_id", "value": idea.idea_id},
                                                    ]
                                                }
                                            }
                                        },
                                        {
                                            "text": "🔔 Adjust sensitivity",
                                            "onClick": {
                                                "action": {
                                                    "function": "sentinel_sensitivity",
                                                    "parameters": [
                                                        {"key": "idea_id", "value": idea.idea_id},
                                                        {"key": "space_name", "value": idea.channel_id},
                                                    ]
                                                }
                                            }
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
        }]
    }

async def post_alert(idea: Idea, article: NewsArticle, analysis: ImpactAnalysis, kelly: KellyRecommendation) -> AlertRecord:
    """Post alert card to idea's Google Chat space and save AlertRecord."""
    import asyncio
    alert_id = str(uuid.uuid4())
    card_body = build_alert_card(idea, article, analysis, kelly, alert_id)

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: chat.spaces().messages().create(
                parent=idea.channel_id,
                body=card_body
            ).execute()
        )
        message_ts = response.get("name", "")
    except Exception as e:
        log.error("gchat.post_alert.failed", idea_id=idea.idea_id, error=str(e))
        message_ts = ""

    record = AlertRecord(
        alert_id=alert_id,
        idea_id=idea.idea_id,
        article_id=article.article_id,
        slack_message_ts=message_ts,  # reuse field — stores Google Chat message name
    )
    await save_alert(record)
    return record
