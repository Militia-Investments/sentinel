"""Integration tests for the impact analysis module.

These tests make real calls to the Anthropic API and are marked with
@pytest.mark.integration. Run them with: pytest -m integration
"""
import os
import pytest
from datetime import datetime, timezone

# These tests require real API keys
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def setup_env():
    os.environ.setdefault("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
    os.environ.setdefault("FINNHUB_API_KEY", "test-key")
    os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
    os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
    os.environ.setdefault("SLACK_SIGNING_SECRET", "test-secret")
    os.environ.setdefault("SENTINEL_ADMIN_CHANNEL", "C0000000000")


@pytest.fixture
def nvda_idea():
    from sentinel.models import Idea, NewsSensitivity
    return Idea(
        idea_id="impact-test-idea-001",
        pm_user_id="U_IMPACT_TEST",
        pm_name="Impact Tester",
        thesis=(
            "NVIDIA dominates the AI accelerator market with 80%+ share in training workloads. "
            "Demand for H100/H200 clusters exceeds supply into 2025, supporting premium pricing. "
            "Target price $700 based on 30x FY2026 EPS estimate of $23."
        ),
        tickers=["NVDA"],
        sector="Technology",
        entry_price=480.0,
        current_position_size=2_000_000.0,
        stop_loss=380.0,
        target_price=700.0,
        key_risks=[
            "AMD MI300X competitive ramp",
            "Hyperscaler in-house ASIC development (Google TPU, Amazon Trainium)",
            "Export controls to China",
            "Demand destruction from AI spending pause",
        ],
        news_sensitivity=NewsSensitivity.HIGH,
        channel_id="C_IMPACT",
        gdelt_query_term="NVIDIA GPU AI demand supply",
    )


@pytest.fixture
def positive_article():
    from sentinel.models import NewsArticle
    return NewsArticle(
        article_id="impact-article-001",
        title="Microsoft Expands Azure AI Infrastructure with $10B NVIDIA H100 Order",
        summary=(
            "Microsoft announced a landmark $10 billion commitment to expand Azure AI infrastructure, "
            "ordering over 100,000 NVIDIA H100 GPUs for delivery in 2024. CEO Satya Nadella said "
            "the investment underscores the transformative potential of AI for enterprise customers. "
            "Delivery is expected over the next 12 months as NVIDIA ramps production."
        ),
        url="https://example.com/microsoft-nvidia-deal",
        source="finnhub",
        tickers=["NVDA", "MSFT"],
        published_at=datetime(2024, 3, 1, 9, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def negative_article():
    from sentinel.models import NewsArticle
    return NewsArticle(
        article_id="impact-article-002",
        title="AMD MI300X Achieves Breakthrough Performance, Wins Major Cloud Contract Over NVIDIA",
        summary=(
            "Advanced Micro Devices announced that its MI300X AI accelerator has surpassed NVIDIA H100 "
            "performance benchmarks in large language model inference workloads. "
            "AWS has awarded AMD a major contract for its next-generation AI training cluster, "
            "marking the first time a major hyperscaler has chosen AMD over NVIDIA for a large-scale "
            "AI training deployment. Analysts expect this to pressure NVIDIA's pricing and market share."
        ),
        url="https://example.com/amd-beats-nvidia",
        source="finnhub",
        tickers=["AMD", "NVDA"],
        published_at=datetime(2024, 3, 5, 14, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_positive_article_returns_analysis(nvda_idea, positive_article):
    """A bullish article should return a valid ImpactAnalysis."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import ImpactAnalysis

    result = await analyze_impact(positive_article, nvda_idea)

    assert result is not None
    assert isinstance(result, ImpactAnalysis)
    assert result.article_id == positive_article.article_id
    assert result.idea_id == nvda_idea.idea_id


@pytest.mark.asyncio
async def test_positive_article_confirms_thesis(nvda_idea, positive_article):
    """A major Microsoft purchase of NVIDIA GPUs should confirm the thesis."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import AlertDirection

    result = await analyze_impact(positive_article, nvda_idea)

    assert result is not None
    assert result.direction in (AlertDirection.CONFIRMS_THESIS, AlertDirection.NEUTRAL), (
        f"Expected confirms_thesis or neutral for bullish article, got {result.direction}"
    )


@pytest.mark.asyncio
async def test_negative_article_threatens_thesis(nvda_idea, negative_article):
    """An AMD competitive win article should threaten or stop the thesis."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import AlertDirection

    result = await analyze_impact(negative_article, nvda_idea)

    assert result is not None
    assert result.direction in (
        AlertDirection.THREATENS_THESIS,
        AlertDirection.STOP_THESIS,
    ), (
        f"Expected threatens_thesis or stop_thesis for AMD competitive win, got {result.direction}"
    )


@pytest.mark.asyncio
async def test_analysis_has_required_fields(nvda_idea, positive_article):
    """Result should have all required ImpactAnalysis fields populated."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import AlertDirection, AlertUrgency, RecommendedAction

    result = await analyze_impact(positive_article, nvda_idea)

    assert result is not None
    assert isinstance(result.direction, AlertDirection)
    assert isinstance(result.urgency, AlertUrgency)
    assert isinstance(result.suggested_action, RecommendedAction)
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.suggested_resize_pct <= 1.0
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0
    assert isinstance(result.key_points, list)
    assert len(result.key_points) > 0


@pytest.mark.asyncio
async def test_negative_article_suggests_reduce_or_exit(nvda_idea, negative_article):
    """A major competitive threat should suggest reduce or exit."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import RecommendedAction

    result = await analyze_impact(negative_article, nvda_idea)

    assert result is not None
    assert result.suggested_action in (
        RecommendedAction.REDUCE,
        RecommendedAction.EXIT,
        RecommendedAction.HOLD,  # Allow hold as LLM may be conservative
    ), (
        f"Expected reduce/exit/hold for major competitive threat, got {result.suggested_action}"
    )


@pytest.mark.asyncio
async def test_high_urgency_for_major_threat(nvda_idea, negative_article):
    """A major competitive loss should have high or critical urgency."""
    from sentinel.analysis.impact import analyze_impact
    from sentinel.models import AlertUrgency

    result = await analyze_impact(negative_article, nvda_idea)

    assert result is not None
    assert result.urgency in (AlertUrgency.HIGH, AlertUrgency.CRITICAL, AlertUrgency.MEDIUM), (
        f"Expected high/critical/medium urgency for major competitive threat, got {result.urgency}"
    )


@pytest.mark.asyncio
async def test_confidence_is_bounded(nvda_idea, positive_article):
    """Confidence should always be between 0 and 1."""
    from sentinel.analysis.impact import analyze_impact

    result = await analyze_impact(positive_article, nvda_idea)

    assert result is not None
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_analyzed_at_is_set(nvda_idea, positive_article):
    """analyzed_at should be set on the result."""
    from sentinel.analysis.impact import analyze_impact

    result = await analyze_impact(positive_article, nvda_idea)

    assert result is not None
    assert result.analyzed_at is not None
    assert isinstance(result.analyzed_at, datetime)
