import re
import json
import uuid
import asyncio
from datetime import datetime, timezone
from anthropic import AsyncAnthropic
from sentinel.gchat.client import chat
from sentinel.config import ANTHROPIC_API_KEY
from sentinel.models import Idea, NewsSensitivity
from sentinel.db import save_idea
import structlog

log = structlog.get_logger()
client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# In-memory state: {user_name: {"step": int, "dm_space": str, "data": dict}}
_onboarding_state: dict[str, dict] = {}

def _parse_position_size(text: str) -> float | None:
    """Parse position size from strings like '$2.5M', '2500000', '2.5m', '$1.2B'."""
    text = text.strip().replace(",", "").replace("$", "").replace(" ", "").upper()
    multiplier = 1.0
    if text.endswith("B"):
        multiplier = 1_000_000_000
        text = text[:-1]
    elif text.endswith("M"):
        multiplier = 1_000_000
        text = text[:-1]
    elif text.endswith("K"):
        multiplier = 1_000
        text = text[:-1]
    try:
        return float(text) * multiplier
    except ValueError:
        return None

async def _send_dm(space_name: str, text: str) -> None:
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: chat.spaces().messages().create(
            parent=space_name,
            body={"text": text}
        ).execute()
    )

async def _send_dm_card(space_name: str, card_body: dict) -> None:
    await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: chat.spaces().messages().create(
            parent=space_name,
            body=card_body
        ).execute()
    )

async def _extract_risks(thesis: str, tickers: list[str]) -> list[str]:
    prompt = f"""Given this trade thesis, extract 3-5 specific, concrete risks or news events
that would materially impact this position. Be specific (e.g. "FERC pipeline ruling" not "regulatory risk").
Return as JSON: {{"risks": ["...", "...", "..."]}}

Thesis: {thesis}
Tickers: {", ".join(tickers)}"""

    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        parsed = json.loads(response.content[0].text)
        return parsed.get("risks", [])
    except Exception:
        return ["Key risk 1", "Key risk 2", "Key risk 3"]

async def _generate_gdelt_query(thesis: str, tickers: list[str]) -> str:
    prompt = f"""Generate a short GDELT news search query (max 6 words) that would catch news
relevant to this trade. Focus on the company or macro theme, not the ticker symbol.
Example: "Grupo Mexico copper tariffs mining"
Return JSON: {{"gdelt_query": "..."}}

Thesis: {thesis}
Tickers: {", ".join(tickers)}"""

    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        parsed = json.loads(response.content[0].text)
        return parsed.get("gdelt_query", tickers[0] if tickers else "")
    except Exception:
        return tickers[0] if tickers else ""

async def start_onboarding(user_name: str, display_name: str, dm_space: str) -> None:
    """Begin onboarding flow in a DM space."""
    _onboarding_state[user_name] = {
        "step": 1,
        "dm_space": dm_space,
        "data": {"pm_slack_user_id": user_name, "pm_display_name": display_name}
    }
    await _send_dm(
        dm_space,
        f"Hey {display_name}! 👋 Let's set up a new idea. Tell me about the trade in a few sentences — "
        "what's the thesis and why are you in it?"
    )

async def handle_onboarding_message(user_name: str, text: str) -> None:
    """Route incoming DM text to the correct onboarding step handler."""
    state = _onboarding_state.get(user_name)
    if not state:
        return

    step = state["step"]
    dm_space = state["dm_space"]
    data = state["data"]

    if step == 1:
        # Received thesis
        data["thesis"] = text.strip()
        await _send_dm(dm_space, "Got it — extracting key risks... ⏳")

        # LLM risk extraction (need tickers — use empty list for now, refine after)
        # Actually we don't have tickers yet. Extract risks from thesis only.
        risks = await _extract_risks(data["thesis"], [])
        data["key_risks"] = risks

        risks_text = "\n".join(f"• {r}" for r in risks)
        await _send_dm(
            dm_space,
            f"Got it. I'm seeing a few key things to watch:\n{risks_text}\n\n"
            "Are there any other specific risks or events you want me to watch for? "
            "(Reply 'looks good' to continue, or add more)"
        )
        state["step"] = 2

    elif step == 2:
        # Confirmed or added risks
        if text.strip().lower() != "looks good":
            data["key_risks"].append(text.strip())
        await _send_dm(
            dm_space,
            "What tickers are you trading this through? (comma-separated, e.g. GMEXICOB, TX)"
        )
        state["step"] = 3

    elif step == 3:
        # Tickers
        tickers = [t.strip().upper() for t in text.split(",") if t.strip()]
        if not tickers:
            await _send_dm(dm_space, "Please enter at least one ticker, e.g. AAPL or GMEXICOB, TX")
            return
        data["tickers"] = tickers
        await _send_dm(dm_space, "What's the current position size in USD? (e.g. $2.5M, 2500000)")
        state["step"] = 4

    elif step == 4:
        # Position size
        size = _parse_position_size(text)
        if size is None or size <= 0:
            await _send_dm(dm_space, "Sorry, I didn't catch that. Try something like $2.5M or 2500000")
            return
        data["position_size_usd"] = size
        await _send_dm(dm_space, "Conviction score 1–10? (1 = watching, 10 = max size)")
        state["step"] = 5

    elif step == 5:
        # Conviction score
        try:
            score = int(text.strip())
            if not 1 <= score <= 10:
                raise ValueError
        except ValueError:
            await _send_dm(dm_space, "Please enter a number between 1 and 10")
            return
        data["conviction_score"] = score

        # Send sensitivity card with buttons
        await _send_dm_card(dm_space, {
            "cardsV2": [{
                "cardId": "sensitivity_select",
                "card": {
                    "header": {"title": "How sensitive should alerts be?"},
                    "sections": [{
                        "widgets": [{
                            "buttonList": {
                                "buttons": [
                                    {
                                        "text": "🔴 High — score ≥ 4",
                                        "onClick": {"action": {"function": "onboarding_sensitivity", "parameters": [{"key": "user_name", "value": user_name}, {"key": "sensitivity", "value": "high"}]}}
                                    },
                                    {
                                        "text": "🟡 Medium — score ≥ 6 (default)",
                                        "onClick": {"action": {"function": "onboarding_sensitivity", "parameters": [{"key": "user_name", "value": user_name}, {"key": "sensitivity", "value": "medium"}]}}
                                    },
                                    {
                                        "text": "🟢 Low — score ≥ 8",
                                        "onClick": {"action": {"function": "onboarding_sensitivity", "parameters": [{"key": "user_name", "value": user_name}, {"key": "sensitivity", "value": "low"}]}}
                                    }
                                ]
                            }
                        }]
                    }]
                }
            }]
        })
        state["step"] = 6

async def handle_sensitivity_selection(user_name: str, sensitivity: str) -> dict:
    """Called when PM clicks a sensitivity button during onboarding. Returns card update response."""
    state = _onboarding_state.get(user_name)
    if not state or state["step"] != 6:
        return {"text": "Session expired. Please start a new idea."}

    data = state["data"]
    data["news_sensitivity"] = sensitivity
    dm_space = state["dm_space"]

    await _send_dm(dm_space, "Perfect. Creating your idea space now... ⏳")
    await _complete_onboarding(user_name)

    return {"text": f"Sensitivity set to {sensitivity}."}

async def _complete_onboarding(user_name: str) -> None:
    state = _onboarding_state.pop(user_name, None)
    if not state:
        return

    data = state["data"]
    dm_space = state["dm_space"]

    # Generate GDELT query term
    gdelt_query = await _generate_gdelt_query(data["thesis"], data["tickers"])
    data["gdelt_query_term"] = gdelt_query

    # Create space name: sentinel-{pm_name}-{first_ticker}-{YYYYMMDD}
    pm_name_clean = re.sub(r"[^a-z0-9]", "", data["pm_display_name"].lower())[:20]
    ticker_clean = re.sub(r"[^a-z0-9]", "", data["tickers"][0].lower())[:10]
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    display_name = f"SENTINEL — {data['tickers'][0]} — {data['pm_display_name']}"

    # Create Google Chat space
    try:
        space = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: chat.spaces().create(body={
                "displayName": display_name[:128],
                "spaceType": "SPACE",
                "spaceDetails": {"description": f"SENTINEL alerts for {', '.join(data['tickers'])}"}
            }).execute()
        )
        space_name = space["name"]

        # Add PM to space
        await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: chat.spaces().members().create(
                parent=space_name,
                body={"member": {"name": user_name, "type": "HUMAN"}}
            ).execute()
        )
    except Exception as e:
        log.error("gchat.onboarding.create_space_failed", user_name=user_name, error=str(e))
        await _send_dm(dm_space, f"❌ Failed to create idea space: {e}. Please try again.")
        return

    # Build and save Idea
    idea = Idea(
        pm_slack_user_id=data["pm_slack_user_id"],
        pm_display_name=data["pm_display_name"],
        channel_id=space_name,
        tickers=data["tickers"],
        thesis=data["thesis"],
        key_risks=data["key_risks"],
        position_size_usd=data["position_size_usd"],
        conviction_score=data["conviction_score"],
        news_sensitivity=NewsSensitivity(data.get("news_sensitivity", "medium")),
        gdelt_query_term=data["gdelt_query_term"],
    )
    await save_idea(idea)

    await _send_dm(
        dm_space,
        f"Done! ✅ I've set up *{display_name}* for this idea.\n"
        f"I'll post all alerts there. You can adjust sensitivity anytime by "
        f"clicking 'Adjust sensitivity' on any alert."
    )
    log.info("gchat.onboarding.completed", idea_id=idea.idea_id, user=data["pm_display_name"])
