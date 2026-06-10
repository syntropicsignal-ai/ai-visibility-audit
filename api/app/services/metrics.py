"""Shared visibility-metric helpers.

Used by `routes/analytics.py`, `routes/report.py`, and `routes/prompts.py`.
Previously duplicated across the first two; consolidated here so they
stay in lockstep.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Brand, Sentiment
from app.schemas import SentimentCounts, VisibilityMetrics


async def self_brand_ids(db: AsyncSession) -> list[int]:
    """All brand IDs flagged `is_self=True`."""
    rows = await db.execute(select(Brand.id).where(Brand.is_self.is_(True)))
    return [row[0] for row in rows.all()]


def empty_metrics() -> VisibilityMetrics:
    return VisibilityMetrics(
        total_responses=0,
        brand_mentioned=0,
        visibility_rate=0.0,
        recommendation_rate=0.0,
        citation_rate=0.0,
        link_rate=0.0,
    )


def metrics_from_analyses(analyses: list[Analysis], total_responses: int) -> VisibilityMetrics:
    """Compute aggregate visibility metrics from a list of self-brand analyses.

    `total_responses` is the denominator for all rates and may include
    responses with no matching analysis row (e.g. failed responses).
    """
    if total_responses == 0:
        return empty_metrics()

    mentioned = sum(1 for a in analyses if a.brand_found)
    recommended = sum(1 for a in analyses if a.recommended)
    with_link = sum(1 for a in analyses if a.link_present)
    cited = sum(1 for a in analyses if a.our_pages)

    return VisibilityMetrics(
        total_responses=total_responses,
        brand_mentioned=mentioned,
        visibility_rate=mentioned / total_responses,
        recommendation_rate=recommended / total_responses,
        citation_rate=cited / total_responses,
        link_rate=with_link / total_responses,
    )


def sentiment_counts(analyses: list[Analysis]) -> SentimentCounts:
    """Count self-brand mentions by sentiment.

    Only counts rows where the brand was actually found — `not_mentioned`
    is implicit in the difference between total responses and mentions.
    """
    pos = neu = neg = 0
    for a in analyses:
        if not a.brand_found:
            continue
        if a.sentiment == Sentiment.positive:
            pos += 1
        elif a.sentiment == Sentiment.negative:
            neg += 1
        elif a.sentiment == Sentiment.neutral:
            neu += 1
    return SentimentCounts(positive=pos, neutral=neu, negative=neg)


def generate_recommendation(
    *,
    prompt_text: str,
    top_competitor_name: str,
    top_competitor_recommended: int,
    competitor_cited_domains: list[str],
    triggered_queries: list[str],
) -> tuple[str, str]:
    """Pick a recommendation template based on the prompt's pattern.

    Order matters — checks are most-specific-first so the highest-leverage
    template fires when its preconditions are met. Returns (kind, text).
    """
    # 1. There's a clear competitor-owned domain we could compete with for citations.
    third_party = [
        d
        for d in competitor_cited_domains
        if not any(t in d for t in [top_competitor_name.lower().replace(" ", "")])
    ]
    if third_party:
        return (
            "get_cited",
            f"{top_competitor_name} wins this query partly via citations from "
            f"`{third_party[0]}`. Pitch a guest piece, claim a profile, or get "
            f"reviewed there — the AI is already trusting that domain.",
        )

    # 2. Competitor is being explicitly recommended — comparison content can flip the answer.
    if top_competitor_recommended > 0:
        return (
            "publish_comparison",
            f"{top_competitor_name} is being explicitly recommended for this prompt. "
            f"Publish a head-to-head comparison page — even an objective one — so "
            f"the AI has a reason to surface you alongside them.",
        )

    # 3. Concrete search query the AI issued that you could target directly.
    if triggered_queries:
        return (
            "target_query",
            f"AI's grounding query for this prompt was '{triggered_queries[0]}'. "
            f"Build a dedicated landing page targeting that exact phrase.",
        )

    # 4. Catch-all: foundational content gap.
    return (
        "publish_content",
        f"The AI knows {top_competitor_name} for this query but not you. "
        f"Publish foundational content covering '{prompt_text[:80]}' on a page "
        f"the AI can find and ground on.",
    )
