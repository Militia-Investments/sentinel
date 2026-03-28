import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from slack_bolt.async_app import AsyncApp
from anthropic import AsyncAnthropic

from sentinel.config import ANTHROPIC_API_KEY
from sentinel.models import Idea, NewsSensitivity
from sentinel.db import save_idea

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

# In-memory state: {user_id: {"step": int, "data": dict}}
_onboarding_state: dict[str, dict] = {}

# Step definitions
STEPS = {
    0: "What is the investment thesis? (Describe the trade idea in 1-3 sentences)",
    1: "What tickers are involved? (Comma-separated, e.g., AAPL, MSFT)",
    2: "What is your current position size in USD? (e.g., $2.5M, 2500000, 2.5m)",
    3: "What are your key risks? (Describe the main risks that could invalidate this thesis)",
    4: "What is your news sensitivity? Reply with: high, medium, or low\n• *high* — Alert me on scores ≥4 (very sensitive)\n• *medium* — Alert me on scores ≥6 (default)\n• *low* — Alert me on scores ≥8 (only major news)",
    5: "What is your conviction score? (1-10, where 10 = highest conviction)",
}


def _parse_position_size(text: str) -> Optional[float]:
    """Parse position size from human-readable string like '$2.5M', '2.5m', '2500000', '$2.5M USD'."""
    # Remove currency symbols, 'USD', whitespace
    clean = re.sub(r"[$,\s]", "", text.upper())
    clean = re.sub(r"\s*USD$", "", clean)

    # Match number with optional multiplier
    match = re.match(r"^([\d.]+)([KMB]?)$", clean)
    if not match:
        return None

    num_str, multiplier = match.groups()
    try:
        num = float(num_str)
    except ValueError:
        return None

    if multiplier == "K":
        num *= 1_000
    elif multiplier == "M":
        num *= 1_000_000
    elif multiplier == "B":
        num *= 1_000_000_000

    return num


def _parse_optional_float(text: str) -> Optional[float]:
    """Parse optional float or return None if 'none'/'skip'."""
    stripped = text.strip().lower()
    if stripped in ("none", "skip", "n/a", "na", "no", "-"):
        return None
    try:
        return float(stripped.replace(",", "").replace("$", ""))
    except ValueError:
        return None


async def _extract_risks(thesis: str, tickers: list[str]) -> list[str]:
    """Use LLM to extract key risks from the thesis."""
    prompt = f"""You are a financial risk analyst.

Given this investment thesis and tickers, identify the top 3-5 key risks that could invalidate the thesis.

Tickers: {", ".join(tickers)}
Thesis: {thesis}

Respond with a JSON array of risk strings only:
["risk1", "risk2", "risk3"]"""

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        risks = json.loads(raw)
        if isinstance(risks, list):
            return [str(r) for r in risks[:5]]
    except Exception:
        pass
    return ["Market downturn", "Earnings miss", "Regulatory risk"]


async def _generate_gdelt_query(thesis: str, tickers: list[str]) -> str:
    """Use LLM to generate an optimal GDELT search query term."""
    prompt = f"""You are a news search expert.

Given this investment thesis and tickers, generate the optimal GDELT news search query term.
The query should capture relevant news events that could impact this investment.
Keep it concise (2-5 words), use OR for alternatives if needed.

Tickers: {", ".join(tickers)}
Thesis: {thesis}

Respond with just the query string, nothing else. Example: "Tesla battery supply chain" or "NVDA AI chips demand" """

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": prompt}],
        )
        query = response.content[0].text.strip().strip('"').strip("'")
        return query
    except Exception:
        # Fallback: use first ticker + sector-like keywords
        return tickers[0] if tickers else ""


async def _send_dm(user_id: str, text: str, app: AsyncApp) -> None:
    """Send a direct message to the user."""
    await app.client.chat_postMessage(
        channel=user_id,
        text=text,
    )


async def handle_new_idea(user_id: str, user_name: str, app: AsyncApp) -> None:
    """Start the onboarding flow by DMing the user and initializing state."""
    _onboarding_state[user_id] = {
        "step": 0,
        "data": {
            "pm_slack_user_id": user_id,
            "pm_display_name": user_name,
        },
    }
    intro = (
        ":robot_face: *SENTINEL Onboarding — New Investment Idea*\n\n"
        "I'll ask you a few questions to set up monitoring for your new idea. "
        "You can type your answers directly in this DM.\n\n"
        f"*Step 1/6:* {STEPS[0]}"
    )
    await _send_dm(user_id, intro, app)


async def handle_onboarding_message(user_id: str, text: str, app: AsyncApp) -> None:
    """Route the incoming message to the correct onboarding step handler."""
    if user_id not in _onboarding_state:
        return

    state = _onboarding_state[user_id]
    step = state["step"]
    data = state["data"]

    if step == 0:
        # Thesis
        data["thesis"] = text.strip()
        state["step"] = 1
        await _send_dm(user_id, f"Got it! :memo:\n\n*Step 2/6:* {STEPS[1]}", app)

    elif step == 1:
        # Tickers
        tickers = [t.strip().upper() for t in re.split(r"[,\s]+", text) if t.strip()]
        if not tickers:
            await _send_dm(user_id, "Please enter at least one ticker symbol.", app)
            return
        data["tickers"] = tickers
        state["step"] = 2
        await _send_dm(user_id, f"Tickers noted: {', '.join(tickers)}\n\n*Step 3/6:* {STEPS[2]}", app)

    elif step == 2:
        # Position size
        position_size = _parse_position_size(text.strip())
        if position_size is None:
            await _send_dm(user_id, "Please enter a valid position size (e.g., $2.5M, 2500000, 2.5m).", app)
            return
        data["position_size_usd"] = position_size
        state["step"] = 3
        await _send_dm(user_id, f"*Step 4/6:* {STEPS[3]}", app)

    elif step == 3:
        # Key risks
        data["key_risks_text"] = text.strip()
        state["step"] = 4
        await _send_dm(user_id, f"*Step 5/6:* {STEPS[4]}", app)

    elif step == 4:
        # News sensitivity
        sensitivity_map = {
            "high": NewsSensitivity.HIGH,
            "medium": NewsSensitivity.MEDIUM,
            "low": NewsSensitivity.LOW,
        }
        sensitivity_str = text.strip().lower()
        if sensitivity_str not in sensitivity_map:
            await _send_dm(user_id, "Please reply with: high, medium, or low", app)
            return
        data["news_sensitivity"] = sensitivity_map[sensitivity_str].value
        state["step"] = 5
        await _send_dm(user_id, f"*Step 6/6:* {STEPS[5]}", app)

    elif step == 5:
        # Conviction score
        try:
            conviction_score = int(text.strip())
            if not (1 <= conviction_score <= 10):
                raise ValueError
        except ValueError:
            await _send_dm(user_id, "Please enter a number between 1 and 10.", app)
            return
        data["conviction_score"] = conviction_score
        state["step"] = 6

        # Acknowledge and start async LLM processing
        await _send_dm(
            user_id,
            ":hourglass_flowing_sand: Almost done! Analyzing your thesis to extract risks and generate news filters...",
            app,
        )
        await _complete_onboarding(user_id, app)


async def _complete_onboarding(user_id: str, app: AsyncApp) -> None:
    """Run LLM extractions, create the Slack channel, save Idea, and confirm to user."""
    state = _onboarding_state.get(user_id)
    if not state:
        return

    data = state["data"]
    thesis = data["thesis"]
    tickers = data["tickers"]

    # Run LLM calls in parallel
    risks, gdelt_query = await asyncio.gather(
        _extract_risks(thesis, tickers),
        _generate_gdelt_query(thesis, tickers),
    )

    # Build channel name: sentinel-{pm_display_name}-{first_ticker}-{YYYYMMDD}
    pm_name_clean = re.sub(r"[^a-z0-9]", "", data["pm_display_name"].lower())[:20]
    ticker_clean = re.sub(r"[^a-z0-9]", "", tickers[0].lower())
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    channel_name = f"sentinel-{pm_name_clean}-{ticker_clean}-{date_str}"
    # Truncate to 80 chars (Slack limit)
    channel_name = channel_name[:80]

    # Create Slack channel
    try:
        create_resp = await app.client.conversations_create(
            name=channel_name,
            is_private=False,
        )
        channel_id = create_resp["channel"]["id"]
        # Invite the PM to the channel
        await app.client.conversations_invite(
            channel=channel_id,
            users=user_id,
        )
    except Exception as exc:
        await _send_dm(
            user_id,
            f":warning: Could not create channel `{channel_name}`: {exc}\nUsing DM channel instead.",
            app,
        )
        channel_id = user_id  # fallback to DM

    # Create and save Idea
    idea = Idea(
        idea_id=str(uuid.uuid4()),
        pm_slack_user_id=data["pm_slack_user_id"],
        pm_display_name=data["pm_display_name"],
        thesis=thesis,
        tickers=tickers,
        position_size_usd=data["position_size_usd"],
        key_risks=risks,
        news_sensitivity=NewsSensitivity(data.get("news_sensitivity", "medium")),
        conviction_score=data.get("conviction_score", 5),
        channel_id=channel_id,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        gdelt_query_term=gdelt_query,
    )

    await save_idea(idea)

    # Clean up state
    del _onboarding_state[user_id]

    # Confirm to user
    risks_text = "\n".join(f"• {r}" for r in risks)
    confirmation = (
        f":white_check_mark: *SENTINEL is now monitoring your idea!*\n\n"
        f"*Idea ID:* `{idea.idea_id}`\n"
        f"*Tickers:* {', '.join(tickers)}\n"
        f"*Channel:* <#{channel_id}>\n"
        f"*Sensitivity:* {idea.news_sensitivity.value}\n"
        f"*GDELT Query:* `{gdelt_query}`\n\n"
        f"*Key Risks Identified:*\n{risks_text}\n\n"
        f"Alerts will be posted to <#{channel_id}>."
    )
    await _send_dm(user_id, confirmation, app)

    # Post welcome message to the new channel
    await app.client.chat_postMessage(
        channel=channel_id,
        text=(
            f":robot_face: *SENTINEL* is now monitoring this idea.\n"
            f"*Thesis:* {thesis}\n"
            f"*Tickers:* {', '.join(tickers)} | *Sensitivity:* {idea.news_sensitivity.value}\n"
            f"Alerts will appear here automatically."
        ),
    )
