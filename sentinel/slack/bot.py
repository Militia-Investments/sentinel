import asyncio
import re

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.aiohttp import AsyncSocketModeHandler

from sentinel.config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, SLACK_SIGNING_SECRET
from sentinel.slack.onboarding import handle_new_idea, handle_onboarding_message, _onboarding_state
from sentinel.slack.sensitivity import show_sensitivity_menu, handle_sensitivity_change
from sentinel.db import get_idea, update_alert_response, get_ideas_for_pm, deactivate_idea
from sentinel.models import NewsSensitivity

app = AsyncApp(token=SLACK_BOT_TOKEN, signing_secret=SLACK_SIGNING_SECRET)
handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)


# ── Message Handlers ──────────────────────────────────────────────────────────

@app.message(re.compile(r"new idea", re.IGNORECASE))
async def on_new_idea(message, say, client):
    """Trigger onboarding when a user says 'new idea'."""
    user_id = message.get("user")
    if not user_id:
        return
    # Get user's display name
    try:
        user_info = await client.users_info(user=user_id)
        user_name = (
            user_info["user"]["profile"].get("display_name")
            or user_info["user"]["profile"].get("real_name")
            or user_id
        )
    except Exception:
        user_name = user_id

    await handle_new_idea(user_id, user_name, app)


@app.message(re.compile(r"my ideas", re.IGNORECASE))
async def on_my_ideas(message, say, client):
    """List all active ideas for the requesting PM."""
    user_id = message.get("user")
    if not user_id:
        return
    channel = message.get("channel")

    try:
        ideas = await get_ideas_for_pm(user_id)
        active_ideas = [i for i in ideas if i.is_active]
    except Exception as exc:
        await client.chat_postMessage(
            channel=channel,
            text=f":x: Failed to retrieve your ideas: {exc}",
        )
        return

    if not active_ideas:
        await client.chat_postMessage(
            channel=channel,
            text=":information_source: You have no active ideas. Say *new idea* to add one.",
        )
        return

    lines = ["*Your Active Ideas:*"]
    for idea in active_ideas:
        lines.append(
            f"• `{idea.idea_id[:8]}...` — {', '.join(idea.tickers)} | "
            f"<#{idea.channel_id}> | Sensitivity: {idea.news_sensitivity.value}"
        )
    await client.chat_postMessage(channel=channel, text="\n".join(lines))


@app.message(re.compile(r"stop idea\s+([a-f0-9\-]+)", re.IGNORECASE))
async def on_stop_idea(message, say, client, context):
    """Deactivate an idea by ID."""
    user_id = message.get("user")
    channel = message.get("channel")
    text = message.get("text", "")

    match = re.search(r"stop idea\s+([a-f0-9\-]+)", text, re.IGNORECASE)
    if not match:
        await client.chat_postMessage(
            channel=channel,
            text=":warning: Usage: `stop idea <idea_id>`",
        )
        return

    idea_id = match.group(1)
    try:
        idea = await get_idea(idea_id)
        if not idea:
            await client.chat_postMessage(
                channel=channel,
                text=f":x: Idea `{idea_id}` not found.",
            )
            return
        if idea.pm_slack_user_id != user_id:
            await client.chat_postMessage(
                channel=channel,
                text=":x: You can only deactivate your own ideas.",
            )
            return
        await deactivate_idea(idea_id)
        await client.chat_postMessage(
            channel=channel,
            text=f":white_check_mark: Idea `{idea_id}` ({', '.join(idea.tickers)}) has been deactivated.",
        )
    except Exception as exc:
        await client.chat_postMessage(
            channel=channel,
            text=f":x: Failed to deactivate idea: {exc}",
        )


@app.message(re.compile(r"sensitivity", re.IGNORECASE))
async def on_sensitivity(message, say, client):
    """Show sensitivity menu when triggered in an idea channel."""
    channel = message.get("channel")
    text = message.get("text", "")

    # Extract idea_id from message if provided, otherwise try to infer from channel
    match = re.search(r"sensitivity\s+([a-f0-9\-]+)", text, re.IGNORECASE)
    if match:
        idea_id = match.group(1)
        await show_sensitivity_menu(app, channel, idea_id)
    else:
        await client.chat_postMessage(
            channel=channel,
            text=":warning: Usage: `sensitivity <idea_id>`",
        )


@app.message(re.compile(r".*", re.DOTALL))
async def on_any_message(message, say, client):
    """Catch-all for DM messages during onboarding flow."""
    user_id = message.get("user")
    if not user_id:
        return
    # Only handle if user is in onboarding state and this is a DM
    channel_type = message.get("channel_type", "")
    if channel_type == "im" and user_id in _onboarding_state:
        await handle_onboarding_message(user_id, message.get("text", ""), app)


# ── Action Handlers ───────────────────────────────────────────────────────────

@app.action(re.compile(r"sentinel_agree_(.+)"))
async def on_sentinel_agree(ack, body, client):
    """Handle 'Agree' button click — log PM agreement."""
    await ack()
    action = body["actions"][0]
    alert_id = action.get("value", "")
    user_id = body["user"]["id"]
    channel = body["channel"]["id"]
    message_ts = body["message"]["ts"]

    try:
        await update_alert_response(alert_id, "agree")
    except Exception:
        pass

    # Update the message to show response was recorded
    await client.chat_postMessage(
        channel=channel,
        thread_ts=message_ts,
        text=f":white_check_mark: <@{user_id}> agreed with the recommendation.",
    )


@app.action(re.compile(r"sentinel_custom_(.+)"))
async def on_sentinel_custom(ack, body, client):
    """Handle 'Custom Resize' button — open modal for custom input."""
    await ack()
    action = body["actions"][0]
    alert_id = action.get("value", "")
    trigger_id = body["trigger_id"]

    await client.views_open(
        trigger_id=trigger_id,
        view={
            "type": "modal",
            "callback_id": "custom_resize_modal",
            "private_metadata": alert_id,
            "title": {
                "type": "plain_text",
                "text": "Custom Position Resize",
            },
            "submit": {
                "type": "plain_text",
                "text": "Submit",
            },
            "close": {
                "type": "plain_text",
                "text": "Cancel",
            },
            "blocks": [
                {
                    "type": "input",
                    "block_id": "resize_block",
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "resize_input",
                        "placeholder": {
                            "type": "plain_text",
                            "text": "e.g., Reduce by 20%, Add $500K, Exit full position",
                        },
                    },
                    "label": {
                        "type": "plain_text",
                        "text": "Describe your intended action:",
                    },
                }
            ],
        },
    )


@app.action(re.compile(r"sentinel_sensitivity_(.+)"))
async def on_sentinel_sensitivity(ack, body, client):
    """Handle 'Sensitivity' button — show sensitivity menu."""
    await ack()
    action = body["actions"][0]
    idea_id = action.get("value", "")
    channel = body["channel"]["id"]
    await show_sensitivity_menu(app, channel, idea_id)


@app.action(re.compile(r"sensitivity_(high|medium|low)"))
async def on_sensitivity_button(ack, body, client):
    """Handle sensitivity level button click."""
    await ack()
    action = body["actions"][0]
    value = action.get("value", "")
    channel = body["channel"]["id"]

    parts = value.split(":", 1)
    if len(parts) != 2:
        return
    idea_id, sensitivity_str = parts

    try:
        sensitivity = NewsSensitivity(sensitivity_str)
        await handle_sensitivity_change(idea_id, sensitivity, channel, app)
    except Exception as exc:
        await client.chat_postMessage(
            channel=channel,
            text=f":x: Failed to update sensitivity: {exc}",
        )


# ── View Handler ──────────────────────────────────────────────────────────────

@app.view("custom_resize_modal")
async def on_custom_resize_modal(ack, body, client):
    """Handle custom resize modal submission."""
    await ack()
    user_id = body["user"]["id"]
    alert_id = body["view"]["private_metadata"]
    values = body["view"]["state"]["values"]

    custom_text = values.get("resize_block", {}).get("resize_input", {}).get("value", "")

    try:
        await update_alert_response(alert_id, f"custom: {custom_text}")
    except Exception:
        pass

    # Notify user in DM
    await client.chat_postMessage(
        channel=user_id,
        text=f":white_check_mark: Your custom action has been recorded: _{custom_text}_",
    )
