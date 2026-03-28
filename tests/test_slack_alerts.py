"""Unit tests for the Slack alert block builder."""
import pytest
import os
from datetime import datetime, timezone

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("BENZINGA_API_KEY", "test-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-secret")
os.environ.setdefault("SENTINEL_ADMIN_CHANNEL", "C0000000000")

from sentinel.models import (
    Idea,
    NewsArticle,
    ImpactAnalysis,
    KellyRecommendation,
    ImpactDirection,
    RecommendedAction,
    NewsSensitivity,
)
from sentinel.slack.alerts import build_alert_blocks, URGENCY_EMOJI, DIRECTION_ICON


def make_idea() -> Idea:
    return Idea(
        idea_id="idea-test-001",
        pm_slack_user_id="U123",
        pm_display_name="Test PM",
        thesis="Long NVDA on AI demand",
        tickers=["NVDA", "AMD"],
        position_size_usd=2_000_000.0,
        conviction_score=7,
        key_risks=["Demand slowdown", "Competition"],
        news_sensitivity=NewsSensitivity.HIGH,
        channel_id="C9999",
    )


def make_article() -> NewsArticle:
    return NewsArticle(
        article_id="article-001",
        headline="NVIDIA Reports Record AI Chip Revenue",
        body="NVIDIA announces record quarterly revenue driven by AI datacenter demand.",
        url="https://example.com/nvidia-earnings",
        source="benzinga",
        tickers_mentioned=["NVDA"],
        published_at=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
    )


def make_analysis(
    direction: ImpactDirection = ImpactDirection.CONFIRMS_THESIS,
    urgency: str = "high",
    action: RecommendedAction = RecommendedAction.ADD,
) -> ImpactAnalysis:
    return ImpactAnalysis(
        article_id="article-001",
        idea_id="idea-test-001",
        direction=direction,
        urgency=urgency,
        narrative="Strong earnings confirm the AI demand thesis.",
        action=action,
        suggested_resize_pct=0.15,
        confidence=0.85,
        created_at=datetime.now(timezone.utc),
    )


def make_kelly(action: RecommendedAction = RecommendedAction.ADD) -> KellyRecommendation:
    return KellyRecommendation(
        idea_id="idea-test-001",
        analysis_id="article-001",
        full_kelly_pct=0.05,
        fractional_kelly_pct=0.05,
        current_position_usd=2_000_000.0,
        suggested_new_position_usd=2_100_000.0,
        delta_usd=100_000.0,
    )


class TestUrgencyEmoji:
    def test_critical_emoji(self):
        assert URGENCY_EMOJI["critical"] == "🔴"

    def test_high_emoji(self):
        assert URGENCY_EMOJI["high"] == "🟠"

    def test_medium_emoji(self):
        assert URGENCY_EMOJI["medium"] == "🟡"

    def test_low_emoji(self):
        assert URGENCY_EMOJI["low"] == "⚪"

    def test_all_urgency_levels_present(self):
        for level in ["critical", "high", "medium", "low"]:
            assert level in URGENCY_EMOJI


class TestDirectionIcon:
    def test_confirms_thesis_icon(self):
        assert DIRECTION_ICON["confirms_thesis"] == "✅"

    def test_threatens_thesis_icon(self):
        assert DIRECTION_ICON["threatens_thesis"] == "⚠️"

    def test_neutral_icon(self):
        assert DIRECTION_ICON["neutral"] == "➡️"

    def test_stop_thesis_icon(self):
        assert DIRECTION_ICON["stop_thesis"] == "🛑"

    def test_all_directions_present(self):
        for direction in ["confirms_thesis", "threatens_thesis", "neutral", "stop_thesis"]:
            assert direction in DIRECTION_ICON


class TestBlockStructure:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis()
        self.kelly = make_kelly()
        self.alert_id = "alert-test-001"
        self.blocks = build_alert_blocks(
            self.idea, self.article, self.analysis, self.kelly, self.alert_id
        )

    def test_blocks_is_list(self):
        assert isinstance(self.blocks, list)

    def test_blocks_not_empty(self):
        assert len(self.blocks) > 0

    def test_first_block_is_header(self):
        assert self.blocks[0]["type"] == "header"

    def test_header_contains_urgency_emoji(self):
        header_text = self.blocks[0]["text"]["text"]
        assert "🟠" in header_text  # HIGH urgency

    def test_header_contains_urgency_level(self):
        header_text = self.blocks[0]["text"]["text"]
        assert "HIGH" in header_text

    def test_section_block_present(self):
        block_types = [b["type"] for b in self.blocks]
        assert "section" in block_types

    def test_divider_present(self):
        block_types = [b["type"] for b in self.blocks]
        assert "divider" in block_types

    def test_actions_block_present(self):
        block_types = [b["type"] for b in self.blocks]
        assert "actions" in block_types

    def test_context_block_present(self):
        block_types = [b["type"] for b in self.blocks]
        assert "context" in block_types

    def test_direction_icon_in_section(self):
        # Find the direction section block
        direction_blocks = [
            b for b in self.blocks
            if b["type"] == "section" and "✅" in b.get("text", {}).get("text", "")
        ]
        assert len(direction_blocks) >= 1

    def test_article_url_in_blocks(self):
        blocks_text = str(self.blocks)
        assert "https://example.com/nvidia-earnings" in blocks_text

    def test_ticker_in_blocks(self):
        blocks_text = str(self.blocks)
        assert "NVDA" in blocks_text

    def test_alert_id_in_context(self):
        context_blocks = [b for b in self.blocks if b["type"] == "context"]
        assert len(context_blocks) >= 1
        context_text = str(context_blocks[0])
        assert self.alert_id in context_text

    def test_idea_id_in_context(self):
        context_blocks = [b for b in self.blocks if b["type"] == "context"]
        context_text = str(context_blocks[0])
        assert "idea-test-001" in context_text


class TestActionButtons:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis()
        self.kelly = make_kelly()
        self.alert_id = "alert-test-abc123"
        self.blocks = build_alert_blocks(
            self.idea, self.article, self.analysis, self.kelly, self.alert_id
        )
        # Find the actions block
        self.actions_block = next(b for b in self.blocks if b["type"] == "actions")
        self.elements = self.actions_block["elements"]

    def test_three_buttons(self):
        assert len(self.elements) == 3

    def test_agree_button_action_id(self):
        agree_btn = self.elements[0]
        assert agree_btn["action_id"] == f"sentinel_agree_{self.alert_id}"

    def test_custom_button_action_id(self):
        custom_btn = self.elements[1]
        assert custom_btn["action_id"] == f"sentinel_custom_{self.alert_id}"

    def test_sensitivity_button_action_id(self):
        sensitivity_btn = self.elements[2]
        assert sensitivity_btn["action_id"] == f"sentinel_sensitivity_{self.idea.idea_id}"

    def test_agree_button_is_primary(self):
        agree_btn = self.elements[0]
        assert agree_btn.get("style") == "primary"

    def test_all_buttons_have_value(self):
        for btn in self.elements:
            assert "value" in btn
            assert btn["value"]

    def test_agree_button_value_is_alert_id(self):
        agree_btn = self.elements[0]
        assert agree_btn["value"] == self.alert_id

    def test_sensitivity_button_value_is_idea_id(self):
        sensitivity_btn = self.elements[2]
        assert sensitivity_btn["value"] == self.idea.idea_id


class TestAllUrgencyLevels:
    @pytest.mark.parametrize("urgency", [
        "critical",
        "high",
        "medium",
        "low",
    ])
    def test_urgency_produces_correct_emoji(self, urgency):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(urgency=urgency)
        kelly = make_kelly()
        blocks = build_alert_blocks(idea, article, analysis, kelly, "test-alert")

        expected_emoji = URGENCY_EMOJI[urgency]
        header_text = blocks[0]["text"]["text"]
        assert expected_emoji in header_text


class TestAllDirectionValues:
    @pytest.mark.parametrize("direction", [
        ImpactDirection.CONFIRMS_THESIS,
        ImpactDirection.THREATENS_THESIS,
        ImpactDirection.NEUTRAL,
        ImpactDirection.STOP_THESIS,
    ])
    def test_direction_produces_correct_icon(self, direction):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(direction=direction)
        kelly = make_kelly()
        blocks = build_alert_blocks(idea, article, analysis, kelly, "test-alert")

        expected_icon = DIRECTION_ICON[direction.value]
        blocks_str = str(blocks)
        assert expected_icon in blocks_str


class TestKellyActionBlocks:
    def test_hold_action_in_blocks(self):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(action=RecommendedAction.HOLD)
        kelly = KellyRecommendation(
            idea_id="idea-test-001",
            analysis_id="article-001",
            full_kelly_pct=0.0,
            fractional_kelly_pct=0.0,
            current_position_usd=2_000_000.0,
            suggested_new_position_usd=2_000_000.0,
            delta_usd=0.0,
        )
        blocks = build_alert_blocks(idea, article, analysis, kelly, "test-alert")
        blocks_str = str(blocks)
        assert "Hold" in blocks_str

    def test_exit_action_in_blocks(self):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(
            action=RecommendedAction.EXIT,
            direction=ImpactDirection.STOP_THESIS,
        )
        kelly = KellyRecommendation(
            idea_id="idea-test-001",
            analysis_id="article-001",
            full_kelly_pct=0.9,
            fractional_kelly_pct=0.9,
            current_position_usd=2_000_000.0,
            suggested_new_position_usd=0.0,
            delta_usd=-2_000_000.0,
        )
        blocks = build_alert_blocks(idea, article, analysis, kelly, "test-alert")
        blocks_str = str(blocks)
        assert "Exit" in blocks_str
