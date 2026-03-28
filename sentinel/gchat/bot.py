import json
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import structlog

from sentinel.gchat.onboarding import (
    start_onboarding, handle_onboarding_message, handle_sensitivity_selection,
    _onboarding_state
)
from sentinel.gchat.sensitivity import show_sensitivity_menu, handle_sensitivity_change
from sentinel.gchat.client import chat
from sentinel.db import (
    get_idea, update_alert_response, get_ideas_for_pm, deactivate_idea
)
from sentinel.config import SENTINEL_ADMIN_SPACE
import asyncio

log = structlog.get_logger()
app = FastAPI(title="SENTINEL Google Chat Bot")


def _get_params(action: dict) -> dict:
    """Extract action parameters as a flat dict."""
    return {p["key"]: p["value"] for p in action.get("parameters", [])}


def _verify_google_chat_token(request: Request) -> None:
    """
    Verify the Bearer token Google Chat sends with every event.
    In production: use google.oauth2.id_token.verify_oauth2_token.
    For MVP: accept if Authorization header is present (tighten before prod).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")


@app.post("/chat/events")
async def handle_event(request: Request):
    _verify_google_chat_token(request)

    body = await request.json()
    event_type = body.get("type")

    log.info("gchat.event", type=event_type)

    if event_type == "MESSAGE":
        return await _handle_message(body)
    elif event_type == "CARD_CLICKED":
        return await _handle_card_click(body)
    elif event_type == "ADDED_TO_SPACE":
        return {"text": "👋 SENTINEL is ready. Send me *new idea* to get started!"}

    return {}


async def _handle_message(body: dict) -> dict:
    message = body.get("message", {})
    text = message.get("text", "").strip().lower()
    sender = message.get("sender", {})
    user_name = sender.get("name", "")
    display_name = sender.get("displayName", "User")
    space = body.get("space", {})
    space_name = space.get("name", "")
    space_type = space.get("type", "")

    # Strip @mentions
    text_clean = text
    for annotation in message.get("annotations", []):
        if annotation.get("type") == "USER_MENTION":
            mention_text = annotation.get("userMention", {}).get("user", {}).get("displayName", "")
            text_clean = text_clean.replace(f"@{mention_text.lower()}", "").strip()

    # If user is mid-onboarding, route to onboarding handler
    if user_name in _onboarding_state:
        await handle_onboarding_message(user_name, text_clean)
        return {}

    if "new idea" in text_clean:
        # Ensure we have a DM space to conduct onboarding
        if space_type == "DM":
            dm_space = space_name
        else:
            # Create or find DM space with the user
            try:
                dm = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: chat.spaces().findDirectMessage(name=user_name).execute()
                )
                dm_space = dm["name"]
            except Exception:
                return {"text": "Please DM me directly to create a new idea!"}

        await start_onboarding(user_name, display_name, dm_space)
        return {}

    elif "my ideas" in text_clean:
        ideas = await get_ideas_for_pm(user_name)
        active = [i for i in ideas if i.is_active]
        if not active:
            return {"text": "You have no active ideas. Send *new idea* to get started."}
        lines = "\n".join(
            f"• `{i.idea_id[:8]}` — {', '.join(i.tickers)} | ${i.position_size_usd:,.0f} | {i.news_sensitivity.value}"
            for i in active
        )
        return {"text": f"*Your active ideas ({len(active)}):*\n{lines}"}

    elif "stop idea" in text_clean:
        parts = text_clean.split()
        idx = parts.index("idea") + 1 if "idea" in parts else -1
        idea_id_prefix = parts[idx] if idx < len(parts) else ""

        ideas = await get_ideas_for_pm(user_name)
        match = next((i for i in ideas if i.idea_id.startswith(idea_id_prefix) and i.is_active), None)
        if not match:
            return {"text": f"No active idea found matching `{idea_id_prefix}`. Use *my ideas* to list yours."}

        await deactivate_idea(match.idea_id)
        return {"text": f"✅ Idea `{match.idea_id[:8]}` ({', '.join(match.tickers)}) deactivated."}

    return {}


async def _handle_card_click(body: dict) -> dict:
    action = body.get("action", {})
    function_name = action.get("actionMethodName", action.get("function", ""))
    params = _get_params(action)
    space = body.get("space", {})
    space_name = space.get("name", "")
    user = body.get("user", {})
    user_name = user.get("name", "")

    log.info("gchat.card_click", function=function_name, params=params)

    if function_name == "sentinel_agree":
        alert_id = params.get("alert_id", "")
        idea_id = params.get("idea_id", "")
        await update_alert_response(alert_id, "agree", None)
        idea = await get_idea(idea_id)
        delta_text = ""
        if idea:
            from sentinel.db import get_recent_alerts_for_idea
        return {"text": f"✅ Noted. Sizing recommendation logged for alert `{alert_id[:8]}`."}

    elif function_name == "sentinel_custom":
        alert_id = params.get("alert_id", "")
        # Google Chat dialogs (modals) require a different response format
        return {
            "actionResponse": {
                "type": "DIALOG",
                "dialogAction": {
                    "dialog": {
                        "body": {
                            "sections": [{
                                "header": "Set custom resize %",
                                "widgets": [{
                                    "textInput": {
                                        "name": "custom_pct",
                                        "label": "Resize % (e.g. -15 to reduce 15%, +10 to add 10%)",
                                        "type": "SINGLE_LINE",
                                    }
                                }, {
                                    "buttonList": {
                                        "buttons": [{
                                            "text": "Submit",
                                            "onClick": {
                                                "action": {
                                                    "function": "sentinel_custom_submit",
                                                    "parameters": [{"key": "alert_id", "value": alert_id}]
                                                }
                                            }
                                        }]
                                    }
                                }]
                            }]
                        }
                    }
                }
            }
        }

    elif function_name == "sentinel_custom_submit":
        alert_id = params.get("alert_id", "")
        form_inputs = body.get("commonEventObject", {}).get("formInputs", {})
        custom_pct_str = form_inputs.get("custom_pct", {}).get("stringInputs", {}).get("value", ["0"])[0]
        try:
            custom_pct = float(custom_pct_str.replace("%", "")) / 100
        except ValueError:
            return {"actionResponse": {"type": "DIALOG", "dialogAction": {"actionStatus": {"statusCode": "INVALID_ARGUMENT", "userFacingMessage": "Invalid percentage. Enter a number like -15 or +10."}}}}
        await update_alert_response(alert_id, f"custom:{custom_pct:.1%}", custom_pct)
        return {"actionResponse": {"type": "CLOSE_DIALOG", "dialogAction": {"actionStatus": {"statusCode": "OK", "userFacingMessage": f"✏️ Custom sizing logged: {custom_pct:+.1%}"}}}}

    elif function_name == "sentinel_sensitivity":
        idea_id = params.get("idea_id", "")
        await show_sensitivity_menu(space_name, idea_id)
        return {}

    elif function_name == "change_sensitivity":
        idea_id = params.get("idea_id", "")
        sensitivity_str = params.get("sensitivity", "medium")
        return await handle_sensitivity_change(idea_id, sensitivity_str, space_name)

    elif function_name == "onboarding_sensitivity":
        user_name_param = params.get("user_name", user_name)
        sensitivity = params.get("sensitivity", "medium")
        return await handle_sensitivity_selection(user_name_param, sensitivity)

    return {}


@app.get("/health")
async def health():
    return {"status": "ok"}
