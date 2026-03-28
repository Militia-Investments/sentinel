import asyncio
from sentinel.gchat.client import chat
from sentinel.models import NewsSensitivity
from sentinel.db import update_idea_sensitivity, get_idea

THRESHOLD_LABELS = {
    NewsSensitivity.HIGH: "score ≥ 4",
    NewsSensitivity.MEDIUM: "score ≥ 6",
    NewsSensitivity.LOW: "score ≥ 8",
}

def build_sensitivity_card(idea_id: str, current: NewsSensitivity) -> dict:
    return {
        "cardsV2": [{
            "cardId": "sensitivity_menu",
            "card": {
                "header": {"title": f"Alert Sensitivity (current: {current.value.title()})"},
                "sections": [{
                    "widgets": [{
                        "buttonList": {
                            "buttons": [
                                {
                                    "text": "🔴 High — score ≥ 4",
                                    "onClick": {"action": {"function": "change_sensitivity", "parameters": [{"key": "idea_id", "value": idea_id}, {"key": "sensitivity", "value": "high"}]}}
                                },
                                {
                                    "text": "🟡 Medium — score ≥ 6",
                                    "onClick": {"action": {"function": "change_sensitivity", "parameters": [{"key": "idea_id", "value": idea_id}, {"key": "sensitivity", "value": "medium"}]}}
                                },
                                {
                                    "text": "🟢 Low — score ≥ 8",
                                    "onClick": {"action": {"function": "change_sensitivity", "parameters": [{"key": "idea_id", "value": idea_id}, {"key": "sensitivity", "value": "low"}]}}
                                }
                            ]
                        }
                    }]
                }]
            }
        }]
    }

async def show_sensitivity_menu(space_name: str, idea_id: str) -> None:
    idea = await get_idea(idea_id)
    if not idea:
        return
    card = build_sensitivity_card(idea_id, idea.news_sensitivity)
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: chat.spaces().messages().create(parent=space_name, body=card).execute()
    )

async def handle_sensitivity_change(idea_id: str, sensitivity_str: str, space_name: str) -> dict:
    sensitivity = NewsSensitivity(sensitivity_str)
    await update_idea_sensitivity(idea_id, sensitivity)
    label = THRESHOLD_LABELS[sensitivity]
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: chat.spaces().messages().create(
            parent=space_name,
            body={"text": f"✅ Alert sensitivity updated to *{sensitivity.value.title()}* ({label})"}
        ).execute()
    )
    return {"text": f"Sensitivity updated to {sensitivity.value}."}
