import uuid
from datetime import datetime, timezone
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field


class NewsSensitivity(str, Enum):
    LOW = "low"        # score threshold >= 8
    MEDIUM = "medium"  # score threshold >= 6  (default)
    HIGH = "high"      # score threshold >= 4


class ImpactDirection(str, Enum):
    CONFIRMS_THESIS = "confirms_thesis"
    THREATENS_THESIS = "threatens_thesis"
    NEUTRAL = "neutral"
    STOP_THESIS = "stop_thesis"


class RecommendedAction(str, Enum):
    HOLD = "hold"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"


class Idea(BaseModel):
    idea_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    pm_slack_user_id: str
    pm_display_name: str
    channel_id: str = ""
    tickers: list[str]
    thesis: str
    key_risks: list[str] = Field(default_factory=list)
    position_size_usd: float
    news_sensitivity: NewsSensitivity = NewsSensitivity.MEDIUM
    conviction_score: int = 5
    gdelt_query_term: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


class NewsArticle(BaseModel):
    article_id: str
    source: str
    headline: str
    body: str
    url: str
    published_at: datetime
    tickers_mentioned: list[str] = Field(default_factory=list)


class RelevanceScore(BaseModel):
    article_id: str
    idea_id: str
    score: int = Field(ge=0, le=10)
    rationale: str = ""


class ImpactAnalysis(BaseModel):
    article_id: str
    idea_id: str
    direction: ImpactDirection
    action: RecommendedAction
    suggested_resize_pct: float = 0.0
    confidence: float = Field(ge=0.0, le=1.0)
    narrative: str
    urgency: str  # "low" | "medium" | "high" | "critical"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KellyRecommendation(BaseModel):
    idea_id: str
    analysis_id: str = ""
    full_kelly_pct: float
    fractional_kelly_pct: float
    suggested_new_position_usd: float
    current_position_usd: float
    delta_usd: float


class AlertRecord(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    idea_id: str
    article_id: str
    slack_message_ts: str = ""
    pm_response: Optional[str] = None
    pm_custom_resize_pct: Optional[float] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
