"""Unit tests for the Kelly position sizing calculator."""
import pytest
from datetime import datetime, timezone
from unittest.mock import patch

# Patch config before importing kelly module
import os
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("FINNHUB_API_KEY", "test-key")
os.environ.setdefault("GOOGLE_CHAT_SERVICE_ACCOUNT_JSON", '{"type":"service_account","project_id":"test","private_key_id":"test","private_key":"-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA2a2rwplBQLzgynykEMmYz0+Iq5rIABBTJUBNDl7KBFQNK\n7nBQFQJSEhRHpFW6h5MpRmFBzE2sxkgTt+I4MKJcFX0V2pWuJiQ7NhyBiGiI3Ts\n-----END RSA PRIVATE KEY-----\n","client_email":"test@test.iam.gserviceaccount.com","client_id":"123","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}')
os.environ.setdefault("GOOGLE_CHAT_SERVICE_ACCOUNT_EMAIL", "test@test.iam.gserviceaccount.com")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT_NUMBER", "123")
os.environ.setdefault("SENTINEL_ADMIN_SPACE", "spaces/TEST")

from sentinel.models import (
    ImpactAnalysis,
    Idea,
    KellyRecommendation,
    RecommendedAction,
    ImpactDirection,
    NewsSensitivity,
)
from sentinel.analysis.kelly import calculate_kelly
from sentinel.config import FRACTIONAL_KELLY_MULTIPLIER


def make_idea(position_size: float = 1_000_000.0) -> Idea:
    return Idea(
        idea_id="test-idea-001",
        pm_slack_user_id="U123",
        pm_display_name="Test PM",
        thesis="Tech AI bull thesis",
        tickers=["NVDA"],
        key_risks=["Competition", "Regulation"],
        position_size_usd=position_size,
        conviction_score=7,
        news_sensitivity=NewsSensitivity.MEDIUM,
        channel_id="C123",
    )


def make_analysis(
    action: RecommendedAction,
    confidence: float = 0.8,
    resize_pct: float = 0.2,
    direction: ImpactDirection = ImpactDirection.CONFIRMS_THESIS,
    urgency: str = "medium",
) -> ImpactAnalysis:
    return ImpactAnalysis(
        article_id="article-001",
        idea_id="test-idea-001",
        direction=direction,
        urgency=urgency,
        narrative="Test analysis",
        action=action,
        suggested_resize_pct=resize_pct,
        confidence=confidence,
        created_at=datetime.now(timezone.utc),
    )


class TestKellyHold:
    def test_hold_returns_unchanged_position(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.HOLD)
        result = calculate_kelly(analysis, idea)

        assert result.delta_usd == 0.0
        assert result.current_position_usd == 1_000_000.0
        assert result.suggested_new_position_usd == 1_000_000.0
        assert result.full_kelly_pct == 0.0
        assert result.fractional_kelly_pct == 0.0

    def test_hold_does_not_modify_position(self):
        idea = make_idea(500_000.0)
        analysis = make_analysis(RecommendedAction.HOLD, confidence=1.0, resize_pct=0.5)
        result = calculate_kelly(analysis, idea)

        assert result.suggested_new_position_usd == 500_000.0


class TestKellyAdd:
    def test_add_increases_position(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.ADD, confidence=0.8, resize_pct=0.2)
        result = calculate_kelly(analysis, idea)

        assert result.suggested_new_position_usd > result.current_position_usd

    def test_add_capped_at_25_percent(self):
        idea = make_idea(1_000_000.0)
        # High confidence, high resize_pct — should be capped at 25%
        analysis = make_analysis(RecommendedAction.ADD, confidence=1.0, resize_pct=1.0)
        result = calculate_kelly(analysis, idea)

        max_allowed_new = result.current_position_usd * 1.25
        assert result.suggested_new_position_usd <= max_allowed_new + 0.01  # small float tolerance

    def test_add_kelly_formula(self):
        idea = make_idea(1_000_000.0)
        confidence = 0.6
        resize_pct = 0.3
        analysis = make_analysis(RecommendedAction.ADD, confidence=confidence, resize_pct=resize_pct)
        result = calculate_kelly(analysis, idea)

        expected_kelly_fraction = confidence * resize_pct
        expected_fractional_kelly = expected_kelly_fraction * FRACTIONAL_KELLY_MULTIPLIER
        capped = min(expected_fractional_kelly, 0.25)
        expected_new = 1_000_000.0 * (1 + capped)

        assert abs(result.full_kelly_pct - expected_kelly_fraction) < 1e-9
        assert abs(result.suggested_new_position_usd - expected_new) < 0.01

    def test_add_small_confidence(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.ADD, confidence=0.1, resize_pct=0.1)
        result = calculate_kelly(analysis, idea)

        # Should be a small addition
        assert result.suggested_new_position_usd > 1_000_000.0
        assert result.suggested_new_position_usd < 1_010_000.0


class TestKellyReduce:
    def test_reduce_decreases_position(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(
            RecommendedAction.REDUCE,
            confidence=0.7,
            resize_pct=0.3,
            direction=ImpactDirection.THREATENS_THESIS,
        )
        result = calculate_kelly(analysis, idea)

        assert result.suggested_new_position_usd < result.current_position_usd

    def test_reduce_capped_at_50_percent(self):
        idea = make_idea(1_000_000.0)
        # High confidence, high resize_pct — should be capped at 50%
        analysis = make_analysis(
            RecommendedAction.REDUCE, confidence=1.0, resize_pct=1.0
        )
        result = calculate_kelly(analysis, idea)

        min_allowed_new = result.current_position_usd * 0.50
        assert result.suggested_new_position_usd >= min_allowed_new - 0.01

    def test_reduce_kelly_formula(self):
        idea = make_idea(1_000_000.0)
        confidence = 0.5
        resize_pct = 0.4
        analysis = make_analysis(RecommendedAction.REDUCE, confidence=confidence, resize_pct=resize_pct)
        result = calculate_kelly(analysis, idea)

        expected_kelly_fraction = confidence * resize_pct
        expected_fractional_kelly = expected_kelly_fraction * FRACTIONAL_KELLY_MULTIPLIER
        capped = min(expected_fractional_kelly, 0.50)
        expected_new = 1_000_000.0 * (1 - capped)

        assert abs(result.full_kelly_pct - expected_kelly_fraction) < 1e-9
        assert abs(result.suggested_new_position_usd - expected_new) < 0.01

    def test_reduce_never_goes_negative(self):
        idea = make_idea(100.0)
        analysis = make_analysis(
            RecommendedAction.REDUCE, confidence=1.0, resize_pct=0.99
        )
        result = calculate_kelly(analysis, idea)

        assert result.suggested_new_position_usd >= 0.0


class TestKellyExit:
    def test_exit_reduces_to_zero(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(
            RecommendedAction.EXIT,
            confidence=0.9,
            resize_pct=1.0,
            direction=ImpactDirection.STOP_THESIS,
        )
        result = calculate_kelly(analysis, idea)

        assert result.suggested_new_position_usd == 0.0

    def test_exit_records_original_position(self):
        idea = make_idea(750_000.0)
        analysis = make_analysis(RecommendedAction.EXIT)
        result = calculate_kelly(analysis, idea)

        assert result.current_position_usd == 750_000.0


class TestKellyEdgeCases:
    def test_confidence_zero_add(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.ADD, confidence=0.0, resize_pct=0.5)
        result = calculate_kelly(analysis, idea)

        assert result.full_kelly_pct == 0.0
        assert result.suggested_new_position_usd == 1_000_000.0

    def test_confidence_one_add_capped(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.ADD, confidence=1.0, resize_pct=1.0)
        result = calculate_kelly(analysis, idea)

        # kelly = 1.0 * 1.0 = 1.0, fractional = 0.25, capped at 0.25
        assert result.suggested_new_position_usd == pytest.approx(1_250_000.0, abs=0.01)

    def test_resize_pct_zero(self):
        idea = make_idea(1_000_000.0)
        analysis = make_analysis(RecommendedAction.ADD, confidence=0.8, resize_pct=0.0)
        result = calculate_kelly(analysis, idea)

        assert result.full_kelly_pct == 0.0
        assert result.suggested_new_position_usd == 1_000_000.0

    def test_result_type(self):
        idea = make_idea()
        analysis = make_analysis(RecommendedAction.HOLD)
        result = calculate_kelly(analysis, idea)

        assert isinstance(result, KellyRecommendation)
        assert result.idea_id == idea.idea_id
        assert result.analysis_id == analysis.article_id

    def test_fractional_kelly_multiplier_applied(self):
        """Verify that FRACTIONAL_KELLY_MULTIPLIER (0.25) is applied correctly."""
        idea = make_idea(1_000_000.0)
        confidence = 0.8
        resize_pct = 0.5
        analysis = make_analysis(RecommendedAction.ADD, confidence=confidence, resize_pct=resize_pct)
        result = calculate_kelly(analysis, idea)

        raw_kelly = confidence * resize_pct  # 0.4
        expected_fractional = raw_kelly * FRACTIONAL_KELLY_MULTIPLIER  # 0.4 * 0.25 = 0.1
        # 0.1 < 0.25 cap, so not capped
        expected_new = 1_000_000.0 * (1 + expected_fractional)  # 1_100_000

        assert abs(result.suggested_new_position_usd - expected_new) < 0.01
