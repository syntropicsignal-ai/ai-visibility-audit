"""Audit report endpoint — one round-trip per printable report."""

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import (
    Analysis,
    Brand,
    ClientProfile,
    IntentType,
    Prompt,
    Response,
    Run,
    Sentiment,
)
from app.schemas import (
    CitationStat,
    CompetitorOpportunity,
    PromptRecommendation,
    ReportBrand,
    ReportBrandAwareness,
    ReportBrandRow,
    ReportPayload,
    ReportPeriod,
    ReportPromptSentimentRow,
    ReportSampleResponse,
    SearchTermStat,
    SentimentCounts,
    SourceBreakdown,
    VisibilityMetrics,
)
from app.services.citations import (
    build_brand_domain_index,
    match_brand_for_host,
    normalize_citation_host,
)
from app.services.metrics import (
    empty_metrics as _empty_metrics,
    generate_recommendation as _generate_recommendation,
    metrics_from_analyses as _metrics_from_analyses,
    sentiment_counts as _sentiment_counts,
)
from app.sources import SOURCES, display_name


logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- helpers ----------


def _dominant_sentiment(analyses: list[Analysis]) -> str:
    """Worst-tone-wins: any negative → negative; else any neutral; else any
    positive; else not_mentioned. The audit framing is "find what's bad",
    so a single negative answer marks the prompt for review."""
    has_neg = any(a.sentiment == Sentiment.negative for a in analyses if a.brand_found)
    if has_neg:
        return "negative"
    has_neu = any(a.sentiment == Sentiment.neutral for a in analyses if a.brand_found)
    if has_neu:
        return "neutral"
    has_pos = any(a.sentiment == Sentiment.positive for a in analyses if a.brand_found)
    if has_pos:
        return "positive"
    return "not_mentioned"


async def _resolve_run_ids(
    db: AsyncSession,
    run_id: int | None,
    from_date: datetime | None,
    to_date: datetime | None,
) -> tuple[list[int], datetime, datetime]:
    """Resolve the report's time window to a concrete list of run_ids.

    Returns (run_ids, from_date, to_date) where the dates are normalized
    to whatever bounds the actual runs cover. For single-run mode we use
    the run's started_at as both from and to, which is fine because the
    cover renders the period as a date range that collapses to a single
    timestamp.
    """
    if run_id is not None:
        run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return [run.id], run.started_at, run.completed_at or run.started_at

    if from_date is None or to_date is None:
        # Default window: last 30 days
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=30)

    runs = list(
        (
            await db.execute(
                select(Run)
                .where(Run.started_at >= from_date, Run.started_at <= to_date)
                .order_by(Run.started_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [r.id for r in runs], from_date, to_date


async def _self_brand(db: AsyncSession) -> Brand | None:
    return (
        await db.execute(select(Brand).where(Brand.is_self.is_(True)).limit(1))
    ).scalar_one_or_none()


async def _client_profile(db: AsyncSession) -> ClientProfile | None:
    return (
        await db.execute(select(ClientProfile).order_by(ClientProfile.updated_at.desc()).limit(1))
    ).scalar_one_or_none()


_LANGUAGE_TO_CODE = {
    "english": "en",
    "polish": "pl",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "dutch": "nl",
    "czech": "cs",
}


def _language_to_code(lang: str | None) -> str:
    """Map a human language name (or ISO code) to a 2-letter ISO code.

    Client profiles store the language as a human name like "Polish".
    Anything we don't recognize falls back to English so the report still
    renders."""
    if not lang:
        return "en"
    key = lang.strip().lower()
    if key in _LANGUAGE_TO_CODE:
        return _LANGUAGE_TO_CODE[key]
    if len(key) == 2 and key.isalpha():
        return key
    return "en"


def _to_report_brand(brand: Brand) -> ReportBrand:
    return ReportBrand(
        id=brand.id,
        name=brand.name,
        domain=brand.domains[0] if brand.domains else None,
        is_self=brand.is_self,
    )


# ---------- section computers ----------


async def _compute_window_metrics(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
) -> tuple[VisibilityMetrics, SentimentCounts]:
    """Aggregate self-brand metrics and sentiment counts over a list of runs.

    Excludes brand-intent prompts so the headline visibility number is
    directly comparable across windows (brand-by-name questions skew
    visibility upward in any window where they ran)."""
    if not run_ids:
        return _empty_metrics(), SentimentCounts(positive=0, neutral=0, negative=0)

    total_q = (
        select(func.count(Response.id))
        .join(Prompt, Prompt.id == Response.prompt_id)
        .where(Response.run_id.in_(run_ids), Prompt.intent != IntentType.brand)
    )
    total = (await db.execute(total_q)).scalar() or 0

    analyses = list(
        (
            await db.execute(
                select(Analysis)
                .join(Response, Response.id == Analysis.response_id)
                .join(Prompt, Prompt.id == Response.prompt_id)
                .where(
                    Analysis.brand_id == self_brand_id,
                    Response.run_id.in_(run_ids),
                    Prompt.intent != IntentType.brand,
                )
            )
        )
        .scalars()
        .all()
    )

    return _metrics_from_analyses(analyses, total), _sentiment_counts(analyses)


async def _compute_by_source(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
) -> list[SourceBreakdown]:
    if not run_ids:
        return []

    totals_by_source: dict[str, int] = {}
    rows = (
        await db.execute(
            select(Response.source, func.count(Response.id))
            .join(Prompt, Prompt.id == Response.prompt_id)
            .where(Response.run_id.in_(run_ids), Prompt.intent != IntentType.brand)
            .group_by(Response.source)
        )
    ).all()
    for source, count in rows:
        totals_by_source[source] = count

    analyses_by_source: dict[str, list[Analysis]] = {sid: [] for sid in SOURCES}
    rows = (
        await db.execute(
            select(Analysis, Response.source)
            .join(Response, Response.id == Analysis.response_id)
            .join(Prompt, Prompt.id == Response.prompt_id)
            .where(
                Analysis.brand_id == self_brand_id,
                Response.run_id.in_(run_ids),
                Prompt.intent != IntentType.brand,
            )
        )
    ).all()
    for analysis, source in rows:
        if source in analyses_by_source:
            analyses_by_source[source].append(analysis)

    out: list[SourceBreakdown] = []
    for sid in SOURCES:
        if totals_by_source.get(sid, 0) == 0:
            continue  # skip sources that never ran in the window
        out.append(
            SourceBreakdown(
                source=sid,
                source_name=display_name(sid),
                metrics=_metrics_from_analyses(
                    analyses_by_source.get(sid, []), totals_by_source.get(sid, 0)
                ),
                sentiment=_sentiment_counts(analyses_by_source.get(sid, [])),
            )
        )
    return out


async def _compute_citations(
    db: AsyncSession,
    run_ids: list[int],
    limit: int = 12,
) -> list[CitationStat]:
    if not run_ids:
        return []

    rows = (
        await db.execute(select(Response.source_urls).where(Response.run_id.in_(run_ids)))
    ).all()

    counts: Counter[str] = Counter()
    total_responses = 0
    for (source_urls,) in rows:
        total_responses += 1
        if not source_urls:
            continue
        seen: set[str] = set()
        for url in source_urls:
            host = normalize_citation_host(url)
            if host is None or host in seen:
                continue
            seen.add(host)
            counts[host] += 1

    if not counts:
        return []

    brands = list((await db.execute(select(Brand))).scalars().all())
    brand_index = build_brand_domain_index(brands)

    out: list[CitationStat] = []
    for host, count in counts.most_common(limit):
        brand = match_brand_for_host(host, brand_index)
        out.append(
            CitationStat(
                domain=host,
                citation_count=count,
                share=count / total_responses if total_responses else 0.0,
                brand_id=brand.id if brand else None,
                brand_name=brand.name if brand else None,
                is_self=brand.is_self if brand else False,
            )
        )
    return out


async def _compute_competitor_visibility(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
    competitor_ids: list[int],
) -> list[ReportBrandRow]:
    """Self-brand pinned first, then chosen competitors. Same denominator
    (non-brand-intent responses in window) so rates are directly
    comparable."""
    if not run_ids:
        return []

    target_ids = [self_brand_id, *competitor_ids]
    brands_rows = (await db.execute(select(Brand).where(Brand.id.in_(target_ids)))).scalars().all()
    brand_by_id = {b.id: b for b in brands_rows}

    total_q = (
        select(func.count(Response.id))
        .join(Prompt, Prompt.id == Response.prompt_id)
        .where(Response.run_id.in_(run_ids), Prompt.intent != IntentType.brand)
    )
    total = (await db.execute(total_q)).scalar() or 0

    analyses_by_brand: dict[int, list[Analysis]] = {bid: [] for bid in target_ids}
    rows = (
        (
            await db.execute(
                select(Analysis)
                .join(Response, Response.id == Analysis.response_id)
                .join(Prompt, Prompt.id == Response.prompt_id)
                .where(
                    Analysis.brand_id.in_(target_ids),
                    Response.run_id.in_(run_ids),
                    Prompt.intent != IntentType.brand,
                )
            )
        )
        .scalars()
        .all()
    )
    for a in rows:
        if a.brand_id in analyses_by_brand:
            analyses_by_brand[a.brand_id].append(a)

    # All brands (self + competitors) ranked together by visibility rate.
    # The self-brand row carries `is_self=True` so the UI can still highlight
    # it, but the ordering reflects actual leaderboard position — pinning it
    # to the top would misrepresent the data when competitors outperform.
    rows_out: list[ReportBrandRow] = []
    for bid in target_ids:
        brand = brand_by_id.get(bid)
        if brand is None:
            continue
        rows_out.append(
            ReportBrandRow(
                brand_id=brand.id,
                brand_name=brand.name,
                is_self=brand.is_self,
                metrics=_metrics_from_analyses(analyses_by_brand[bid], total),
                sentiment=_sentiment_counts(analyses_by_brand[bid]),
            )
        )
    rows_out.sort(key=lambda r: r.metrics.visibility_rate, reverse=True)
    return rows_out


async def _compute_brand_awareness(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
) -> ReportBrandAwareness:
    """Brand-intent prompts grouped by the worst tone the AI used about us.

    The whole point of this section in the audit is to spotlight prompts
    where the brand-by-name response is bad — that's where attention is
    needed most. So we sort each group by total_responses (more data =
    higher confidence), and the negative/neutral lists come first in the
    payload."""
    if not run_ids:
        return ReportBrandAwareness(
            total_brand_prompts=0,
            total_responses=0,
            sentiment_counts=SentimentCounts(positive=0, neutral=0, negative=0),
            recommendation_rate=0.0,
            negative=[],
            neutral=[],
            positive=[],
            not_mentioned=[],
        )

    # Pull all brand-intent prompts with their responses + analyses for the window.
    prompts_rows = (
        (
            await db.execute(
                select(Prompt)
                .where(Prompt.intent == IntentType.brand)
                .options(selectinload(Prompt.responses))
            )
        )
        .scalars()
        .all()
    )
    prompts = list(prompts_rows)

    if not prompts:
        return ReportBrandAwareness(
            total_brand_prompts=0,
            total_responses=0,
            sentiment_counts=SentimentCounts(positive=0, neutral=0, negative=0),
            recommendation_rate=0.0,
            negative=[],
            neutral=[],
            positive=[],
            not_mentioned=[],
        )

    prompt_ids = [p.id for p in prompts]
    analyses_rows = (
        await db.execute(
            select(Analysis, Response.prompt_id, Response.run_id)
            .join(Response, Response.id == Analysis.response_id)
            .where(
                Analysis.brand_id == self_brand_id,
                Response.run_id.in_(run_ids),
                Response.prompt_id.in_(prompt_ids),
            )
        )
    ).all()

    analyses_by_prompt: dict[int, list[Analysis]] = {pid: [] for pid in prompt_ids}
    for analysis, prompt_id, _run_id in analyses_rows:
        analyses_by_prompt[prompt_id].append(analysis)

    # Total responses per prompt (in window)
    totals_q = (
        select(Response.prompt_id, func.count(Response.id))
        .where(Response.run_id.in_(run_ids), Response.prompt_id.in_(prompt_ids))
        .group_by(Response.prompt_id)
    )
    totals_by_prompt = {pid: c for pid, c in (await db.execute(totals_q)).all()}

    grouped: dict[str, list[ReportPromptSentimentRow]] = {
        "negative": [],
        "neutral": [],
        "positive": [],
        "not_mentioned": [],
    }
    overall = SentimentCounts(positive=0, neutral=0, negative=0)
    total_brand_responses = 0
    total_recommended = 0

    for prompt in prompts:
        analyses = analyses_by_prompt.get(prompt.id, [])
        total_resp = totals_by_prompt.get(prompt.id, 0)
        if total_resp == 0:
            continue  # prompt didn't run in the window
        sc = _sentiment_counts(analyses)
        overall = SentimentCounts(
            positive=overall.positive + sc.positive,
            neutral=overall.neutral + sc.neutral,
            negative=overall.negative + sc.negative,
        )
        recommended = sum(1 for a in analyses if a.recommended)
        total_brand_responses += total_resp
        total_recommended += recommended

        dominant = _dominant_sentiment(analyses)
        grouped[dominant].append(
            ReportPromptSentimentRow(
                prompt_id=prompt.id,
                text=prompt.text,
                dominant_sentiment=dominant,
                recommended_count=recommended,
                total_responses=total_resp,
                sentiment_counts=sc,
            )
        )

    for key in grouped:
        grouped[key].sort(key=lambda r: r.total_responses, reverse=True)

    return ReportBrandAwareness(
        total_brand_prompts=sum(len(v) for v in grouped.values()),
        total_responses=total_brand_responses,
        sentiment_counts=overall,
        recommendation_rate=(
            total_recommended / total_brand_responses if total_brand_responses else 0.0
        ),
        negative=grouped["negative"],
        neutral=grouped["neutral"],
        positive=grouped["positive"],
        not_mentioned=grouped["not_mentioned"],
    )


async def _compute_samples(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
    sample_count: int,
) -> list[ReportSampleResponse]:
    """Pick the most informative responses for the report.

    Selection priority (per slot, no duplicates):
      1. The most recent negative-sentiment response
      2. The most recent recommended response
      3. The most recent response with citations of *our* pages
      4. The most recent response that mentions us with positive sentiment
      5. Fill remaining slots with the most recent self-mentioned responses

    If none match a category we just skip it. Responses with empty text
    or errors are excluded.
    """
    if not run_ids or sample_count <= 0:
        return []

    rows = (
        await db.execute(
            select(Response, Analysis, Prompt)
            .join(
                Analysis,
                (Analysis.response_id == Response.id) & (Analysis.brand_id == self_brand_id),
            )
            .join(Prompt, Prompt.id == Response.prompt_id)
            .where(
                Response.run_id.in_(run_ids),
                Response.error_kind.is_(None),
                func.length(Response.text) > 0,
            )
            .order_by(Response.created_at.desc())
        )
    ).all()

    picked: list[ReportSampleResponse] = []
    seen_ids: set[int] = set()

    def to_sample(resp: Response, analysis: Analysis, prompt: Prompt) -> ReportSampleResponse:
        cited = []
        our_pages = analysis.our_pages or {}
        if isinstance(our_pages, dict):
            for v in our_pages.values():
                if isinstance(v, list):
                    cited.extend(v)
                elif isinstance(v, str):
                    cited.append(v)
        return ReportSampleResponse(
            response_id=resp.id,
            run_id=resp.run_id,
            source=resp.source,
            source_name=display_name(resp.source),
            prompt_text=prompt.text,
            prompt_intent=prompt.intent,
            response_text=resp.text,
            brand_found=analysis.brand_found,
            sentiment=analysis.sentiment,
            recommended=analysis.recommended,
            cited_domains=[normalize_citation_host(u) or u for u in cited][:5],
        )

    def take_first(predicate) -> bool:
        for resp, analysis, prompt in rows:
            if resp.id in seen_ids:
                continue
            if predicate(resp, analysis, prompt):
                picked.append(to_sample(resp, analysis, prompt))
                seen_ids.add(resp.id)
                return True
        return False

    take_first(lambda r, a, p: a.brand_found and a.sentiment == Sentiment.negative)
    if len(picked) < sample_count:
        take_first(lambda r, a, p: a.brand_found and a.recommended)
    if len(picked) < sample_count:
        take_first(lambda r, a, p: a.brand_found and bool(a.our_pages))
    if len(picked) < sample_count:
        take_first(lambda r, a, p: a.brand_found and a.sentiment == Sentiment.positive)

    # Fill remaining slots with most-recent self-mentioned responses
    for resp, analysis, prompt in rows:
        if len(picked) >= sample_count:
            break
        if resp.id in seen_ids:
            continue
        if analysis.brand_found:
            picked.append(to_sample(resp, analysis, prompt))
            seen_ids.add(resp.id)

    return picked[:sample_count]


# ---------- endpoint ----------


# ---------- advanced-tier section computers ----------


async def _compute_citation_gap(
    db: AsyncSession, run_ids: list[int], self_brand_id: int, limit: int = 8
) -> list[CitationStat]:
    """Domains cited where the self brand wasn't mentioned in the response.

    Same math as the analytics endpoint but scoped to `run_ids`. Self-
    brand-owned domains are filtered out of the result — by definition
    the brand wasn't mentioned in this slice, so a row pointing at the
    self domain would be misleading.
    """
    if not run_ids:
        return []

    response_rows = (
        await db.execute(
            select(Response.id, Response.source_urls)
            .join(Prompt, Prompt.id == Response.prompt_id)
            .where(Response.run_id.in_(run_ids), Prompt.intent != IntentType.brand)
        )
    ).all()
    if not response_rows:
        return []

    response_ids = [row[0] for row in response_rows]
    mentioned_response_ids: set[int] = set()
    if response_ids:
        analysis_rows = (
            await db.execute(
                select(Analysis.response_id).where(
                    Analysis.brand_id == self_brand_id,
                    Analysis.brand_found.is_(True),
                    Analysis.response_id.in_(response_ids),
                )
            )
        ).all()
        mentioned_response_ids = {row[0] for row in analysis_rows}

    counts: Counter[str] = Counter()
    gap_total = 0
    for resp_id, source_urls in response_rows:
        if resp_id in mentioned_response_ids:
            continue
        gap_total += 1
        if not source_urls:
            continue
        seen: set[str] = set()
        for url in source_urls:
            host = normalize_citation_host(url)
            if host is None or host in seen:
                continue
            seen.add(host)
            counts[host] += 1

    if not counts:
        return []

    brands = list((await db.execute(select(Brand))).scalars().all())
    brand_index = build_brand_domain_index(brands)

    out: list[CitationStat] = []
    for host, count in counts.most_common(limit):
        brand = match_brand_for_host(host, brand_index)
        if brand and brand.is_self:
            continue
        out.append(
            CitationStat(
                domain=host,
                citation_count=count,
                share=count / gap_total if gap_total else 0.0,
                brand_id=brand.id if brand else None,
                brand_name=brand.name if brand else None,
                is_self=False,
            )
        )
    return out


async def _compute_search_terms(
    db: AsyncSession, run_ids: list[int], limit: int = 15, min_count: int = 2
) -> list[SearchTermStat]:
    """Top grounding queries within the report window."""
    if not run_ids:
        return []

    rows = (
        await db.execute(
            select(Response.search_queries, Response.prompt_id, Response.source).where(
                Response.run_id.in_(run_ids),
                Response.search_queries.is_not(None),
            )
        )
    ).all()
    if not rows:
        return []

    counts: Counter[str] = Counter()
    prompts_by_term: dict[str, set[int]] = {}
    sources_by_term: dict[str, set[str]] = {}
    for search_queries, prompt_id, source in rows:
        if not search_queries:
            continue
        seen: set[str] = set()
        for raw in search_queries:
            term = " ".join(raw.split()).lower()
            if not term or term in seen:
                continue
            if term.startswith(("http://", "https://", "www.")) or (
                "/" in term and " " not in term
            ):
                continue
            seen.add(term)
            counts[term] += 1
            prompts_by_term.setdefault(term, set()).add(prompt_id)
            sources_by_term.setdefault(term, set()).add(source)

    out: list[SearchTermStat] = []
    for term, count in counts.most_common(limit):
        if count < min_count:
            continue
        out.append(
            SearchTermStat(
                term=term,
                count=count,
                prompt_count=len(prompts_by_term.get(term, set())),
                source_count=len(sources_by_term.get(term, set())),
            )
        )
    return out


async def _compute_recommendations(
    db: AsyncSession,
    run_ids: list[int],
    self_brand_id: int,
    threshold: float = 0.3,
    limit: int = 8,
) -> list[PromptRecommendation]:
    """Top-N "winnable" prompts within the window.

    Same shape as analytics.get_recommendations but scoped to run_ids.
    Recommendation-text generation is rule-based (mirrors the analytics
    router); duplicated rather than imported because moving it into a
    shared module is bigger than this PR's scope.
    """
    if not run_ids:
        return []

    prompts = list(
        (
            await db.execute(
                select(Prompt)
                .where(Prompt.intent != IntentType.brand)
                .options(selectinload(Prompt.responses))
            )
        )
        .scalars()
        .all()
    )
    if not prompts:
        return []
    prompt_ids = [p.id for p in prompts]

    analysis_rows = (
        await db.execute(
            select(Analysis, Response, Brand)
            .join(Response, Response.id == Analysis.response_id)
            .join(Brand, Brand.id == Analysis.brand_id)
            .where(
                Response.prompt_id.in_(prompt_ids),
                Response.run_id.in_(run_ids),
            )
        )
    ).all()

    by_prompt: dict[int, list] = {pid: [] for pid in prompt_ids}
    for analysis, response, brand in analysis_rows:
        by_prompt[response.prompt_id].append((analysis, response, brand))

    self_brand_row = (
        await db.execute(select(Brand).where(Brand.id == self_brand_id))
    ).scalar_one_or_none()
    self_domains = {d.lower() for d in (self_brand_row.domains or [])} if self_brand_row else set()

    out: list[PromptRecommendation] = []
    for prompt in prompts:
        rows = by_prompt.get(prompt.id, [])
        if not rows:
            continue

        # Total responses for this prompt within the window
        total_in_window = sum(1 for r in prompt.responses if r.run_id in set(run_ids))
        if total_in_window == 0:
            continue

        self_analyses = [a for a, _, b in rows if b.id == self_brand_id]
        self_mentioned = sum(1 for a in self_analyses if a.brand_found)
        self_hit_rate = self_mentioned / total_in_window if total_in_window else 0.0
        if self_hit_rate > threshold:
            continue

        comp_buckets: dict[int, list] = {}
        comp_meta: dict[int, str] = {}
        for analysis, _resp, brand in rows:
            if brand.id == self_brand_id or not analysis.brand_found:
                continue
            comp_buckets.setdefault(brand.id, []).append(analysis)
            comp_meta[brand.id] = brand.name
        if not comp_buckets:
            continue

        comp_summaries: list[CompetitorOpportunity] = []
        for bid, analyses in comp_buckets.items():
            comp_summaries.append(
                CompetitorOpportunity(
                    brand_id=bid,
                    brand_name=comp_meta[bid],
                    mention_count=len(analyses),
                    recommended_count=sum(1 for a in analyses if a.recommended),
                )
            )
        comp_summaries.sort(key=lambda c: c.mention_count, reverse=True)
        top_competitor = comp_summaries[0]
        opportunity_score = (top_competitor.mention_count / total_in_window) * (1 - self_hit_rate)

        top_comp_response_ids = {
            resp.id
            for analysis, resp, brand in rows
            if brand.id == top_competitor.brand_id and analysis.brand_found
        }
        cited_counter: Counter[str] = Counter()
        for _a, resp, _b in rows:
            if resp.id not in top_comp_response_ids:
                continue
            for url in resp.source_urls or []:
                host = normalize_citation_host(url)
                if host:
                    cited_counter[host] += 1
        cited_domains = [
            host
            for host, _ in cited_counter.most_common(10)
            if not any(sd in host for sd in self_domains)
        ][:5]

        seen_q: set[str] = set()
        triggered_queries: list[str] = []
        for _a, resp, _b in rows:
            if resp.id not in top_comp_response_ids:
                continue
            for q in resp.search_queries or []:
                key = q.strip().lower()
                if key and key not in seen_q:
                    seen_q.add(key)
                    triggered_queries.append(q.strip())
                if len(triggered_queries) >= 5:
                    break
            if len(triggered_queries) >= 5:
                break

        kind, text = _generate_recommendation(
            prompt_text=prompt.text,
            top_competitor_name=top_competitor.brand_name,
            top_competitor_recommended=top_competitor.recommended_count,
            competitor_cited_domains=cited_domains,
            triggered_queries=triggered_queries,
        )

        out.append(
            PromptRecommendation(
                prompt_id=prompt.id,
                prompt_text=prompt.text,
                intent=prompt.intent,
                self_hit_rate=self_hit_rate,
                self_mentioned_count=self_mentioned,
                self_total_responses=total_in_window,
                top_competitor=top_competitor,
                other_competitors=comp_summaries[1:5],
                cited_domains=cited_domains,
                triggered_search_queries=triggered_queries,
                opportunity_score=opportunity_score,
                recommendation_kind=kind,
                recommendation_text=text,
            )
        )

    out.sort(key=lambda r: r.opportunity_score, reverse=True)
    return out[:limit]


@router.get("", response_model=ReportPayload)
async def get_report(
    run_id: int | None = Query(None, description="Single-run mode: aggregate just this run"),
    from_date: datetime | None = Query(None, description="Range mode: start (ISO 8601)"),
    to_date: datetime | None = Query(None, description="Range mode: end (ISO 8601)"),
    competitor_ids: list[int] = Query(
        default=[],
        description="Brand ids to include in competitor visibility table",
    ),
    sample_count: int = Query(5, ge=0, le=20, description="Number of sample responses to include"),
    language: str | None = Query(
        None,
        description="ISO 639-1 language code; falls back to client profile or 'en'",
    ),
    tier: str = Query(
        "simple",
        regex="^(simple|advanced)$",
        description=(
            "Report tier. 'simple' returns the snapshot sections (KPIs, "
            "brand awareness, per-source, citations, competitor visibility, "
            "samples). 'advanced' adds recommendations, citation gap, "
            "and search-term analysis."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> ReportPayload:
    self_brand = await _self_brand(db)
    if self_brand is None:
        raise HTTPException(
            status_code=400,
            detail="No self-brand configured. Mark a brand as is_self=True before generating a report.",
        )

    run_ids, period_from, period_to = await _resolve_run_ids(db, run_id, from_date, to_date)

    # Period metadata
    period = ReportPeriod(
        kind="run" if run_id is not None else "range",
        run_id=run_id,
        from_date=period_from,
        to_date=period_to,
        run_count=len(run_ids),
    )

    # Resolve competitor brands (drop ids that don't exist or are self)
    competitor_brands: list[Brand] = []
    if competitor_ids:
        rows = (
            (
                await db.execute(
                    select(Brand).where(Brand.id.in_(competitor_ids), Brand.is_self.is_(False))
                )
            )
            .scalars()
            .all()
        )
        competitor_brands = list(rows)

    # Language: explicit > client_profile > "en". The client profile stores
    # the human language name ("Polish", "English"), so normalize here.
    if language is None:
        cp = await _client_profile(db)
        language = _language_to_code(cp.language) if cp else "en"

    # Headline metrics for the window
    metrics, sentiment = await _compute_window_metrics(db, run_ids, self_brand.id)

    # Prior-window metrics for delta. Only computed in range mode (the
    # single-run delta is already shown on the dashboard, and the report
    # framing is "this period vs the previous period of the same length").
    metrics_prior: VisibilityMetrics | None = None
    sentiment_prior: SentimentCounts | None = None
    if run_id is None and run_ids:
        delta = period_to - period_from
        prior_to = period_from
        prior_from = prior_to - delta
        prior_run_rows = list(
            (
                await db.execute(
                    select(Run.id).where(
                        Run.started_at >= prior_from,
                        Run.started_at < prior_to,
                    )
                )
            ).all()
        )
        prior_run_ids = [r[0] for r in prior_run_rows]
        if prior_run_ids:
            metrics_prior, sentiment_prior = await _compute_window_metrics(
                db, prior_run_ids, self_brand.id
            )

    by_source = await _compute_by_source(db, run_ids, self_brand.id)
    citations = await _compute_citations(db, run_ids, limit=12)
    competitor_visibility = await _compute_competitor_visibility(
        db, run_ids, self_brand.id, [b.id for b in competitor_brands]
    )
    brand_awareness = await _compute_brand_awareness(db, run_ids, self_brand.id)
    samples = await _compute_samples(db, run_ids, self_brand.id, sample_count)

    # Advanced-tier sections — computed only on demand. Each is independent;
    # we compute them sequentially because they're cheap individually.
    recommendations: list[PromptRecommendation] = []
    citation_gap: list[CitationStat] = []
    search_terms: list[SearchTermStat] = []
    if tier == "advanced":
        recommendations = await _compute_recommendations(
            db, run_ids, self_brand.id, threshold=0.3, limit=8
        )
        citation_gap = await _compute_citation_gap(db, run_ids, self_brand.id, limit=8)
        search_terms = await _compute_search_terms(db, run_ids, limit=15, min_count=2)

    return ReportPayload(
        period=period,
        self_brand=_to_report_brand(self_brand),
        competitors=[_to_report_brand(b) for b in competitor_brands],
        language=language,
        tier=tier,
        metrics=metrics,
        sentiment=sentiment,
        metrics_prior=metrics_prior,
        sentiment_prior=sentiment_prior,
        brand_awareness=brand_awareness,
        by_source=by_source,
        citations=citations,
        competitor_visibility=competitor_visibility,
        samples=samples,
        recommendations=recommendations,
        citation_gap=citation_gap,
        search_terms=search_terms,
    )


# ---------- PDF rendering ----------


def _build_report_render_url(query: dict[str, str | list[str]]) -> str:
    """Compose the URL Playwright should navigate to.

    Frontend route uses "human" param names (`from`, `to`, `competitors`,
    `samples`, `lang`, `tier`, `run_id`). The PDF endpoint accepts the
    backend-canonical names and translates them here so the renderer
    fetches the same view the user would see in their browser.
    """
    parts: list[tuple[str, str]] = []
    for k, v in query.items():
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            parts.append((k, ",".join(str(x) for x in v)))
        else:
            parts.append((k, str(v)))
    qs = urlencode(parts, doseq=False)
    base = settings.report_render_url.rstrip("/")
    return f"{base}/report?{qs}" if qs else f"{base}/report"


@router.get("/pdf")
async def get_report_pdf(
    run_id: int | None = Query(None),
    from_date: datetime | None = Query(None),
    to_date: datetime | None = Query(None),
    competitor_ids: list[int] = Query(default=[]),
    sample_count: int = Query(5, ge=0, le=20),
    language: str | None = Query(None),
    tier: str = Query("simple", regex="^(simple|advanced)$"),
) -> FastAPIResponse:
    """Render the report HTML to a PDF and stream it back.

    Headless Chromium navigates to the existing `/report` Vue route
    (running on the web container) with the requested params, waits
    for the report DOM + a small networkidle buffer to make sure
    chart canvases have painted, then snapshots A4 PDF.

    Why we don't render server-side templates: the report layout
    lives in Vue with reactive data bindings + Chart.js canvases.
    Re-implementing that pixel-perfectly in Jinja would be wasted
    work — easier to drive the same UI we ship to humans.

    Errors are surfaced as plain HTTPException so the frontend can
    show an actionable toast; we don't try to recover from a
    chromium crash inside the request.
    """
    # Lazy import — keeps the cold-start cost out of the API process
    # for everyone who doesn't generate PDFs.
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout

    query_params: dict[str, str | list[str]] = {}
    if run_id is not None:
        query_params["run_id"] = str(run_id)
    if from_date is not None:
        query_params["from"] = from_date.isoformat()
    if to_date is not None:
        query_params["to"] = to_date.isoformat()
    if competitor_ids:
        query_params["competitors"] = [str(c) for c in competitor_ids]
    if sample_count != 5:
        query_params["samples"] = str(sample_count)
    if language:
        query_params["lang"] = language
    query_params["tier"] = tier

    target_url = _build_report_render_url(query_params)
    logger.info("Rendering report PDF: %s", target_url)

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
            try:
                context = await browser.new_context(
                    # A4 at 96dpi is roughly 794×1123 px. We render at a
                    # 2× device-scale factor so figures stay crisp when
                    # the PDF is zoomed in by the reader.
                    viewport={"width": 1024, "height": 1400},
                    device_scale_factor=2,
                )
                page = await context.new_page()
                await page.goto(target_url, wait_until="networkidle", timeout=30_000)
                # Belt-and-braces: wait for the data-driven container
                # the Vue route mounts AFTER the API call resolves.
                await page.wait_for_selector(".report-page", timeout=15_000)
                # Charts paint after a microtask; small buffer prevents
                # blank canvases on the first cold render.
                await page.wait_for_timeout(settings.report_render_extra_wait_ms)
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    # No browser-default header/footer; the report has
                    # its own footer with the Syntropic attribution.
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            finally:
                await browser.close()
    except PWTimeout as e:
        logger.exception("Report PDF render timed out for %s", target_url)
        raise HTTPException(
            status_code=504,
            detail=(
                "Timed out rendering the report. The web container may be "
                "unreachable or the report had no data; check the API logs."
            ),
        ) from e
    except Exception as e:  # noqa: BLE001 — surface the message to the caller
        logger.exception("Report PDF render failed")
        raise HTTPException(
            status_code=500,
            detail=f"Report PDF render failed: {e}",
        ) from e

    filename = "ai-visibility-audit-report.pdf"
    return FastAPIResponse(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
