"""Unit tests for the Google Chat alert card builder."""
import pytest
import os
from datetime import datetime, timezone

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("BENZINGA_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CHAT_SERVICE_ACCOUNT_JSON", '{"type":"service_account","project_id":"test","private_key_id":"test","private_key":"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA2a2rwplBQLzgynykEMmYz0+Iq5rIABBTJUBNDl7KBFQNK\n7nBQFQJSEhRHpFW6h5MpRmFBzE2sxkgTt+I4MKJcFX0V2pWuJiQ7NhyBiGiI3Ts\n-----END RSA PRIVATE KEY-----\n","client_email":"test@test.iam.gserviceaccount.com","client_id":"123","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}')
os.environ.setdefault("GOOGLE_CHAT_SERVICE_ACCOUNT_EMAIL", "test@test.iam.gserviceaccount.com")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT_NUMBER", "123")
os.environ.setdefault("SENTINEL_ADMIN_SPACE", "spaces/TEST")

from unittest.mock import patch, MagicMock
import sys

# Patch out the Google API client build so we don't need real credentials at import time
_mock_chat = MagicMock()
with patch("google.oauth2.service_account.Credentials.from_service_account_info", return_value=MagicMock()), \
     patch("googleapiclient.discovery.build", return_value=_mock_chat):
    from sentinel.gchat.alerts import build_alert_card, URGENCY_EMOJI, DIRECTION_ICON

from sentinel.models import (
    Idea,
    NewsArticle,
    ImpactAnalysis,
    KellyRecommendation,
    ImpactDirection,
    RecommendedAction,
    NewsSensitivity,
)


def make_idea() -> Idea:
    return Idea(
        idea_id="idea-test-001",
        pm_slack_user_id="users/123456789",
        pm_display_name="Test PM",
        thesis="Long NVDA on AI demand",
        tickers=["NVDA", "AMD"],
        position_size_usd=2_000_000.0,
        conviction_score=7,
        key_risks=["Demand slowdown", "Competition"],
        news_sensitivity=NewsSensitivity.HIGH,
        channel_id="spaces/C9999",
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
    confidence: float = 0.85,
    resize_pct: float = 0.15,
) -> ImpactAnalysis:
    return ImpactAnalysis(
        article_id="article-001",
        idea_id="idea-test-001",
        direction=direction,
        urgency=urgency,
        narrative="Strong earnings confirm the AI demand thesis.",
        action=action,
        suggested_resize_pct=resize_pct,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )


def make_kelly(
    delta_usd: float = 100_000.0,
    current: float = 2_000_000.0,
    suggested: float = 2_100_000.0,
    fractional_kelly_pct: float = 0.05,
) -> KellyRecommendation:
    return KellyRecommendation(
        idea_id="idea-test-001",
        analysis_id="article-001",
        full_kelly_pct=0.05,
        fractional_kelly_pct=fractional_kelly_pct,
        current_position_usd=current,
        suggested_new_position_usd=suggested,
        delta_usd=delta_usd,
    )


class TestCardTopLevelStructure:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis()
        self.kelly = make_kelly()
        self.alert_id = "alert-test-001"
        self.card = build_alert_card(
            self.idea, self.article, self.analysis, self.kelly, self.alert_id
        )

    def test_card_has_cards_v2_key(self):
        assert "cardsV2" in self.card

    def test_cards_v2_is_list(self):
        assert isinstance(self.card["cardsV2"], list)

    def test_cards_v2_not_empty(self):
        assert len(self.card["cardsV2"]) > 0

    def test_card_id_contains_alert_id(self):
        card_id = self.card["cardsV2"][0]["cardId"]
        assert self.alert_id in card_id

    def test_card_has_header(self):
        card = self.card["cardsV2"][0]["card"]
        assert "header" in card

    def test_card_has_sections(self):
        card = self.card["cardsV2"][0]["card"]
        assert "sections" in card
        assert len(card["sections"]) > 0


class TestCardHeader:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis(urgency="high")
        self.kelly = make_kelly()
        self.card = build_alert_card(
            self.idea, self.article, self.analysis, self.kelly, "alert-001"
        )
        self.header = self.card["cardsV2"][0]["card"]["header"]

    def test_header_title_contains_urgency_emoji(self):
        assert "🟠" in self.header["title"]  # HIGH urgency emoji

    def test_header_title_contains_urgency_level(self):
        assert "HIGH" in self.header["title"]

    def test_header_subtitle_is_article_headline(self):
        assert self.article.headline in self.header["subtitle"]

    def test_header_title_contains_sentinel(self):
        assert "SENTINEL" in self.header["title"]


class TestCardSections:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis()
        self.kelly = make_kelly()
        self.card = build_alert_card(
            self.idea, self.article, self.analysis, self.kelly, "alert-001"
        )
        self.sections = self.card["cardsV2"][0]["card"]["sections"]

    def test_two_sections(self):
        assert len(self.sections) == 2

    def test_first_section_has_direction_header(self):
        # direction header should contain the direction icon
        header = self.sections[0]["header"]
        assert "✅" in header  # CONFIRMS_THESIS

    def test_second_section_has_kelly_header(self):
        header = self.sections[1]["header"]
        assert "Kelly" in header

    def test_first_section_has_narrative_widget(self):
        widgets = self.sections[0]["widgets"]
        text_paragraphs = [w for w in widgets if "textParagraph" in w]
        assert len(text_paragraphs) >= 1
        narrative_text = str(text_paragraphs[0])
        assert "Strong earnings" in narrative_text

    def test_first_section_has_columns_widget(self):
        widgets = self.sections[0]["widgets"]
        column_widgets = [w for w in widgets if "columns" in w]
        assert len(column_widgets) >= 1

    def test_columns_contain_tickers(self):
        widgets = self.sections[0]["widgets"]
        widgets_str = str(widgets)
        assert "NVDA" in widgets_str

    def test_columns_contain_source_url(self):
        widgets = self.sections[0]["widgets"]
        widgets_str = str(widgets)
        assert "https://example.com/nvidia-earnings" in widgets_str

    def test_second_section_has_kelly_text(self):
        widgets = self.sections[1]["widgets"]
        widgets_str = str(widgets)
        assert "Kelly" in widgets_str or "Add" in widgets_str or "Hold" in widgets_str or "Reduce" in widgets_str


class TestKellyButtons:
    def setup_method(self):
        self.idea = make_idea()
        self.article = make_article()
        self.analysis = make_analysis()
        self.kelly = make_kelly()
        self.alert_id = "alert-test-abc123"
        self.card = build_alert_card(
            self.idea, self.article, self.analysis, self.kelly, self.alert_id
        )
        sections = self.card["cardsV2"][0]["card"]["sections"]
        kelly_section = sections[1]
        button_widgets = [w for w in kelly_section["widgets"] if "buttonList" in w]
        assert button_widgets, "No buttonList widget found in Kelly section"
        self.buttons = button_widgets[0]["buttonList"]["buttons"]

    def test_three_buttons(self):
        assert len(self.buttons) == 3

    def test_agree_button_function_name(self):
        agree_btn = self.buttons[0]
        function_name = agree_btn["onClick"]["action"]["function"]
        assert function_name == "sentinel_agree"

    def test_custom_button_function_name(self):
        custom_btn = self.buttons[1]
        function_name = custom_btn["onClick"]["action"]["function"]
        assert function_name == "sentinel_custom"

    def test_sensitivity_button_function_name(self):
        sensitivity_btn = self.buttons[2]
        function_name = sensitivity_btn["onClick"]["action"]["function"]
        assert function_name == "sentinel_sensitivity"

    def test_agree_button_has_alert_id_param(self):
        agree_btn = self.buttons[0]
        params = {p["key"]: p["value"] for p in agree_btn["onClick"]["action"]["parameters"]}
        assert params.get("alert_id") == self.alert_id

    def test_agree_button_has_idea_id_param(self):
        agree_btn = self.buttons[0]
        params = {p["key"]: p["value"] for p in agree_btn["onClick"]["action"]["parameters"]}
        assert params.get("idea_id") == self.idea.idea_id

    def test_custom_button_has_alert_id_param(self):
        custom_btn = self.buttons[1]
        params = {p["key"]: p["value"] for p in custom_btn["onClick"]["action"]["parameters"]}
        assert params.get("alert_id") == self.alert_id

    def test_custom_button_has_idea_id_param(self):
        custom_btn = self.buttons[1]
        params = {p["key"]: p["value"] for p in custom_btn["onClick"]["action"]["parameters"]}
        assert params.get("idea_id") == self.idea.idea_id

    def test_sensitivity_button_has_idea_id_param(self):
        sensitivity_btn = self.buttons[2]
        params = {p["key"]: p["value"] for p in sensitivity_btn["onClick"]["action"]["parameters"]}
        assert params.get("idea_id") == self.idea.idea_id


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


class TestAllUrgencyLevels:
    @pytest.mark.parametrize("urgency", ["critical", "high", "medium", "low"])
    def test_urgency_produces_correct_emoji_in_header(self, urgency):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(urgency=urgency)
        kelly = make_kelly()
        card = build_alert_card(idea, article, analysis, kelly, "test-alert")

        expected_emoji = URGENCY_EMOJI[urgency]
        header_title = card["cardsV2"][0]["card"]["header"]["title"]
        assert expected_emoji in header_title


class TestAllDirectionValues:
    @pytest.mark.parametrize("direction", [
        ImpactDirection.CONFIRMS_THESIS,
        ImpactDirection.THREATENS_THESIS,
        ImpactDirection.NEUTRAL,
        ImpactDirection.STOP_THESIS,
    ])
    def test_direction_produces_correct_icon_in_section_header(self, direction):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(direction=direction)
        kelly = make_kelly()
        card = build_alert_card(idea, article, analysis, kelly, "test-alert")

        expected_icon = DIRECTION_ICON[direction.value]
        sections = card["cardsV2"][0]["card"]["sections"]
        first_section_header = sections[0]["header"]
        assert expected_icon in first_section_header


class TestKellyTextVariants:
    def test_hold_zero_delta_text(self):
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
        card = build_alert_card(idea, article, analysis, kelly, "test-alert")
        sections = card["cardsV2"][0]["card"]["sections"]
        kelly_section_str = str(sections[1])
        assert "Hold" in kelly_section_str

    def test_add_positive_delta_text(self):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(action=RecommendedAction.ADD)
        kelly = KellyRecommendation(
            idea_id="idea-test-001",
            analysis_id="article-001",
            full_kelly_pct=0.05,
            fractional_kelly_pct=0.05,
            current_position_usd=2_000_000.0,
            suggested_new_position_usd=2_100_000.0,
            delta_usd=100_000.0,
        )
        card = build_alert_card(idea, article, analysis, kelly, "test-alert")
        sections = card["cardsV2"][0]["card"]["sections"]
        kelly_section_str = str(sections[1])
        assert "Add" in kelly_section_str

    def test_reduce_negative_delta_text(self):
        idea = make_idea()
        article = make_article()
        analysis = make_analysis(action=RecommendedAction.REDUCE, direction=ImpactDirection.THREATENS_THESIS)
        kelly = KellyRecommendation(
            idea_id="idea-test-001",
            analysis_id="article-001",
            full_kelly_pct=0.05,
            fractional_kelly_pct=0.05,
            current_position_usd=2_000_000.0,
            suggested_new_position_usd=1_900_000.0,
            delta_usd=-100_000.0,
        )
        card = build_alert_card(idea, article, analysis, kelly, "test-alert")
        sections = card["cardsV2"][0]["card"]["sections"]
        kelly_section_str = str(sections[1])
        assert "Reduce" in kelly_section_str
