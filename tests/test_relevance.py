"""Integration tests for the relevance scoring module.

These tests make real calls to the Anthropic API and are marked with
@pytest.mark.integration. Run them with: pytest -m integration
"""
import os
import pytest
import pytest_asyncio
from datetime import datetime, timezone

# These tests require real API keys
pytestmark = pytest.mark.integration


@pytest.fixture
def sample_idea():
    os.environ.setdefault("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
    os.environ.setdefault("BENZINGA_API_KEY", "test-key")
    os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
    os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
    os.environ.setdefault("SLACK_SIGNING_SECRET", "test-secret")
    os.environ.setdefault("SENTINEL_ADMIN_CHANNEL", "C0000000000")

    from sentinel.models import Idea, NewsSensitivity
    return Idea(
        idea_id="integration-test-idea-001",
        pm_user_id="U_INTEGRATION",
        pm_name="Integration Tester",
        thesis=(
            "NVIDIA is positioned to benefit from the AI infrastructure buildout. "
            "Enterprise and hyperscaler demand for H100/H200 GPUs remains constrained, "
            "giving NVIDIA pricing power and record margins."
        ),
        tickers=["NVDA"],
        sector="Technology",
        entry_price=450.0,
        current_position_size=1_000_000.0,
        stop_loss=350.0,
        target_price=700.0,
        key_risks=[
            "Competitor GPU releases from AMD or Intel",
            "Export controls on AI chips to China",
            "Hyperscaler capex slowdown",
        ],
        news_sensitivity=NewsSensitivity.HIGH,
        channel_id="C_INTEGRATION",
        gdelt_query_term="NVIDIA AI chips GPU demand",
    )


@pytest.fixture
def relevant_article():
    from sentinel.models import NewsArticle
    return NewsArticle(
        article_id="integration-article-001",
        title="NVIDIA Reports Record Q4 Revenue, Raises Guidance on AI Demand",
        summary=(
            "NVIDIA Corporation today reported record fourth quarter and fiscal year 2024 revenue. "
            "Data Center revenue was $18.4 billion, up 409% from a year ago. "
            "The company raised its Q1 2025 guidance to $24 billion, citing insatiable demand "
            "for its H100 and H200 AI training GPUs from cloud providers and enterprises."
        ),
        url="https://example.com/nvda-q4-2024-earnings",
        source="benzinga",
        tickers=["NVDA"],
        published_at=datetime(2024, 2, 21, 22, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def irrelevant_article():
    from sentinel.models import NewsArticle
    return NewsArticle(
        article_id="integration-article-002",
        title="Local Restaurant Chain Reports Strong Same-Store Sales",
        summary=(
            "Denny's Corporation reported better-than-expected same-store sales growth "
            "for the holiday quarter, driven by new menu items and loyalty program growth. "
            "The company opened 12 new locations during the period."
        ),
        url="https://example.com/dennys-earnings",
        source="benzinga",
        tickers=["DENN"],
        published_at=datetime(2024, 2, 20, 16, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_relevant_article_scores_high(sample_idea, relevant_article):
    """A directly relevant earnings article should score high (>=7)."""
    from sentinel.analysis.relevance import score_relevance

    result = await score_relevance(relevant_article, sample_idea)

    assert result.article_id == relevant_article.article_id
    assert result.idea_id == sample_idea.idea_id
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 10
    assert result.score >= 7, (
        f"Expected score >= 7 for relevant NVIDIA earnings article, got {result.score}. "
        f"Reasoning: {result.reasoning}"
    )
    assert result.reasoning


@pytest.mark.asyncio
async def test_irrelevant_article_scores_low(sample_idea, irrelevant_article):
    """An unrelated article should score low (<= 3)."""
    from sentinel.analysis.relevance import score_relevance

    result = await score_relevance(irrelevant_article, sample_idea)

    assert result.article_id == irrelevant_article.article_id
    assert result.idea_id == sample_idea.idea_id
    assert isinstance(result.score, int)
    assert 0 <= result.score <= 10
    assert result.score <= 3, (
        f"Expected score <= 3 for irrelevant Denny's article, got {result.score}. "
        f"Reasoning: {result.reasoning}"
    )


@pytest.mark.asyncio
async def test_score_returns_relevance_score_model(sample_idea, relevant_article):
    """Result should be a properly structured RelevanceScore model."""
    from sentinel.analysis.relevance import score_relevance
    from sentinel.models import RelevanceScore

    result = await score_relevance(relevant_article, sample_idea)

    assert isinstance(result, RelevanceScore)
    assert result.article_id == relevant_article.article_id
    assert result.idea_id == sample_idea.idea_id
    assert isinstance(result.score, int)
    assert isinstance(result.reasoning, str)
    assert len(result.reasoning) > 0


@pytest.mark.asyncio
async def test_batch_scoring(sample_idea, relevant_article, irrelevant_article):
    """Batch scoring should handle multiple pairs concurrently."""
    from sentinel.analysis.relevance import score_relevance_batch

    pairs = [
        (relevant_article, sample_idea),
        (irrelevant_article, sample_idea),
    ]

    results = await score_relevance_batch(pairs)

    assert len(results) == 2
    for score, article, idea in results:
        assert score.article_id == article.article_id
        assert score.idea_id == idea.idea_id
        assert 0 <= score.score <= 10


@pytest.mark.asyncio
async def test_export_controls_article_scores_high(sample_idea):
    """An article about export controls on AI chips should score high for NVDA thesis."""
    from sentinel.analysis.relevance import score_relevance
    from sentinel.models import NewsArticle

    export_article = NewsArticle(
        article_id="integration-article-003",
        title="US Expands Export Controls on Advanced AI Chips to China, Restricting NVIDIA H100",
        summary=(
            "The Biden administration announced new export controls targeting advanced AI chips, "
            "specifically restricting the sale of NVIDIA H100 and A100 GPUs to China and "
            "additional countries. The new rules are expected to impact NVIDIA's China revenue, "
            "which represents approximately 20% of total Data Center sales."
        ),
        url="https://example.com/ai-chip-export-controls",
        source="edgar",
        tickers=["NVDA"],
        published_at=datetime(2024, 1, 10, 14, 0, tzinfo=timezone.utc),
    )

    result = await score_relevance(export_article, sample_idea)

    # Export controls are a key risk — should score very high
    assert result.score >= 8, (
        f"Expected score >= 8 for export controls article (key risk), got {result.score}. "
        f"Reasoning: {result.reasoning}"
    )
