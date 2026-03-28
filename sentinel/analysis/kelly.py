from sentinel.models import ImpactAnalysis, Idea, KellyRecommendation, RecommendedAction
from sentinel.config import FRACTIONAL_KELLY_MULTIPLIER


def calculate_kelly(analysis: ImpactAnalysis, idea: Idea) -> KellyRecommendation:
    """Calculate fractional Kelly position sizing recommendation.

    Formula:
    - Hold: return position unchanged, full_kelly_pct = 0
    - Add: full_kelly_pct = confidence * suggested_resize_pct
           fractional_kelly_pct = full_kelly_pct * FRACTIONAL_KELLY_MULTIPLIER
           capped at 25% addition
    - Reduce: full_kelly_pct = confidence * suggested_resize_pct
              fractional_kelly_pct = full_kelly_pct * FRACTIONAL_KELLY_MULTIPLIER
              capped at 50% reduction
    - Exit: reduce to 0 (100% reduction, capped at 50% per trade — but exit means full)
    """
    action = analysis.action
    current = idea.position_size_usd

    if action == RecommendedAction.HOLD:
        return KellyRecommendation(
            idea_id=idea.idea_id,
            analysis_id=analysis.article_id,
            full_kelly_pct=0.0,
            fractional_kelly_pct=0.0,
            current_position_usd=current,
            suggested_new_position_usd=current,
            delta_usd=0.0,
        )

    if action == RecommendedAction.EXIT:
        # Exit: reduce to 0
        full_kelly_pct = analysis.confidence * abs(analysis.suggested_resize_pct) if analysis.suggested_resize_pct else analysis.confidence
        fractional_kelly_pct = full_kelly_pct * FRACTIONAL_KELLY_MULTIPLIER
        # Exit means full liquidation regardless of cap
        new_position = 0.0
        return KellyRecommendation(
            idea_id=idea.idea_id,
            analysis_id=analysis.article_id,
            full_kelly_pct=full_kelly_pct,
            fractional_kelly_pct=fractional_kelly_pct,
            current_position_usd=current,
            suggested_new_position_usd=new_position,
            delta_usd=new_position - current,
        )

    # Add or Reduce
    full_kelly_pct = analysis.confidence * abs(analysis.suggested_resize_pct)
    fractional_kelly_pct = full_kelly_pct * FRACTIONAL_KELLY_MULTIPLIER

    if action == RecommendedAction.ADD:
        # Cap maximum addition at 25%
        capped_fraction = min(fractional_kelly_pct, 0.25)
        delta = current * capped_fraction
        new_position = current + delta
    else:
        # Reduce — cap maximum reduction at 50%
        capped_fraction = min(fractional_kelly_pct, 0.50)
        delta = current * capped_fraction
        new_position = current - delta
        new_position = max(0.0, new_position)

    return KellyRecommendation(
        idea_id=idea.idea_id,
        analysis_id=analysis.article_id,
        full_kelly_pct=full_kelly_pct,
        fractional_kelly_pct=fractional_kelly_pct if action == RecommendedAction.ADD else -fractional_kelly_pct,
        current_position_usd=current,
        suggested_new_position_usd=new_position,
        delta_usd=new_position - current,
    )
