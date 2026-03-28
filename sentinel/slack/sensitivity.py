from slack_bolt.async_app import AsyncApp

from sentinel.models import NewsSensitivity
from sentinel.db import update_idea_sensitivity, get_idea
from sentinel.config import RELEVANCE_THRESHOLD_LOW, RELEVANCE_THRESHOLD_MEDIUM, RELEVANCE_THRESHOLD_HIGH


async def show_sensitivity_menu(app: AsyncApp, channel_id: str, idea_id: str) -> None:
    """Post a message with sensitivity level buttons to the given channel."""
    await app.client.chat_postMessage(
        channel=channel_id,
        text="Adjust news sensitivity for this idea:",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        "*Adjust News Sensitivity*\n"
                        "Choose how sensitive SENTINEL should be to news for this idea:\n\n"
                        f"• *High* — Alert on score ≥{RELEVANCE_THRESHOLD_HIGH} (very sensitive)\n"
                        f"• *Medium* — Alert on score ≥{RELEVANCE_THRESHOLD_MEDIUM} (default)\n"
                        f"• *Low* — Alert on score ≥{RELEVANCE_THRESHOLD_LOW} (major news only)"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🔴 High",
                            "emoji": True,
                        },
                        "style": "danger",
                        "action_id": "sensitivity_high",
                        "value": f"{idea_id}:high",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "🟡 Medium",
                            "emoji": True,
                        },
                        "action_id": "sensitivity_medium",
                        "value": f"{idea_id}:medium",
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "⚪ Low",
                            "emoji": True,
                        },
                        "action_id": "sensitivity_low",
                        "value": f"{idea_id}:low",
                    },
                ],
            },
        ],
    )


async def handle_sensitivity_change(
    idea_id: str,
    sensitivity: NewsSensitivity,
    channel_id: str,
    app: AsyncApp,
) -> None:
    """Update the idea's sensitivity in DynamoDB and post confirmation."""
    await update_idea_sensitivity(idea_id, sensitivity)

    threshold_map = {
        NewsSensitivity.HIGH: RELEVANCE_THRESHOLD_HIGH,
        NewsSensitivity.MEDIUM: RELEVANCE_THRESHOLD_MEDIUM,
        NewsSensitivity.LOW: RELEVANCE_THRESHOLD_LOW,
    }
    threshold = threshold_map[sensitivity]

    await app.client.chat_postMessage(
        channel=channel_id,
        text=(
            f":white_check_mark: News sensitivity updated to *{sensitivity.value}*. "
            f"SENTINEL will now alert on relevance scores ≥{threshold}."
        ),
    )
