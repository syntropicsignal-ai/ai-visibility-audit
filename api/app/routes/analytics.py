from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Analysis, Brand, IntentType, Prompt, Response, Run, Sentiment
from app.schemas import (
    BrandComparison,
    BrandComparisonEntry,
    CitationStat,
    CompetitorOpportunity,
    CompetitorShare,
    FunnelMetrics,
    FunnelStage,
    PromptPerformance,
    PromptRecommendation,
    RunSummary,
    SearchTermStat,
    SentimentCounts,
    GraphEdge,
    GraphNode,
    SourceBreakdown,
    TopicCompetitor,
    TopicGraph,
    TopicStat,
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
    self_brand_ids as _self_brand_ids,
    sentiment_counts as _sentiment_counts,
)
from app.sources import SOURCES, display_name

router = APIRouter()


# ---------- helpers ----------


async def _resolve_brand_ids(db: AsyncSession, brand_id: int | None) -> list[int]:
    """Return [brand_id] if given, otherwise fall back to all self-brand ids."""
    if brand_id is not None:
        return [brand_id]
    return await _self_brand_ids(db)


# ---------- endpoints ----------


@router.get("/visibility", response_model=VisibilityMetrics)
async def get_visibility(
    run_id: int | None = Query(None, description="Filter by run ID"),
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(
        None, description="Exclude prompts with this intent (e.g. 'brand' for fair comparisons)"
    ),
    db: AsyncSession = Depends(get_db),
) -> VisibilityMetrics:
    brand_ids = await _resolve_brand_ids(db, brand_id)
    if not brand_ids:
        return _empty_metrics()

    response_q = select(func.count(Response.id))
    if run_id is not None:
        response_q = response_q.where(Response.run_id == run_id)
    if exclude_intent is not None:
        response_q = response_q.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )
    total_responses = (await db.execute(response_q)).scalar() or 0

    analysis_q = (
        select(Analysis)
        .where(Analysis.brand_id.in_(brand_ids))
        .join(Response, Response.id == Analysis.response_id)
    )
    if run_id is not None:
        analysis_q = analysis_q.where(Response.run_id == run_id)
    if exclude_intent is not None:
        analysis_q = analysis_q.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )
    analyses = list((await db.execute(analysis_q)).scalars().all())

    return _metrics_from_analyses(analyses, total_responses)


@router.get("/runs/summary", response_model=list[RunSummary])
async def get_runs_summary(
    limit: int = Query(20, ge=1, le=100),
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(None, description="Exclude prompts with this intent"),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[RunSummary]:
    """Per-run aggregate metrics, newest first.

    Used for the time-series chart and delta computation on the dashboard.
    """
    brand_ids = await _resolve_brand_ids(db, brand_id)

    runs = list(
        (await db.execute(select(Run).order_by(Run.started_at.desc()).limit(limit))).scalars().all()
    )
    if not runs:
        return []

    run_ids = [r.id for r in runs]

    # Total responses per run
    totals_q = (
        select(Response.run_id, func.count(Response.id))
        .where(Response.run_id.in_(run_ids))
        .group_by(Response.run_id)
    )
    if source is not None:
        totals_q = totals_q.where(Response.source == source)
    if exclude_intent is not None:
        totals_q = totals_q.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )
    totals_by_run = {run_id: count for run_id, count in (await db.execute(totals_q)).all()}

    # All brand analyses for these runs in one query
    analyses_by_run: dict[int, list[Analysis]] = {rid: [] for rid in run_ids}
    if brand_ids:
        analyses_q = (
            select(Analysis, Response.run_id)
            .join(Response, Response.id == Analysis.response_id)
            .where(
                Analysis.brand_id.in_(brand_ids),
                Response.run_id.in_(run_ids),
            )
        )
        if source is not None:
            analyses_q = analyses_q.where(Response.source == source)
        if exclude_intent is not None:
            analyses_q = analyses_q.join(Prompt, Prompt.id == Response.prompt_id).where(
                Prompt.intent != exclude_intent
            )
        for analysis, run_id in (await db.execute(analyses_q)).all():
            analyses_by_run[run_id].append(analysis)

    return [
        RunSummary(
            run_id=run.id,
            started_at=run.started_at,
            completed_at=run.completed_at,
            status=run.status,
            total_cost=run.total_cost,
            metrics=_metrics_from_analyses(
                analyses_by_run.get(run.id, []),
                totals_by_run.get(run.id, 0),
            ),
            sentiment=_sentiment_counts(analyses_by_run.get(run.id, [])),
        )
        for run in runs
    ]


@router.get("/runs/{run_id}/summary", response_model=RunSummary)
async def get_run_summary(
    run_id: int,
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(None, description="Exclude prompts with this intent"),
    db: AsyncSession = Depends(get_db),
) -> RunSummary:
    """Single-run aggregate metrics — the focused version of /runs/summary.

    Used by the Run detail page so we don't have to fetch the whole list
    just to render one row's worth of metrics.
    """
    run = (await db.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    brand_ids = await _resolve_brand_ids(db, brand_id)

    total_q = select(func.count(Response.id)).where(Response.run_id == run_id)
    if exclude_intent is not None:
        total_q = total_q.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )
    total_responses = (await db.execute(total_q)).scalar() or 0

    analyses: list[Analysis] = []
    if brand_ids:
        analyses_q = (
            select(Analysis)
            .join(Response, Response.id == Analysis.response_id)
            .where(
                Response.run_id == run_id,
                Analysis.brand_id.in_(brand_ids),
            )
        )
        if exclude_intent is not None:
            analyses_q = analyses_q.join(Prompt, Prompt.id == Response.prompt_id).where(
                Prompt.intent != exclude_intent
            )
        analyses = list((await db.execute(analyses_q)).scalars().all())

    return RunSummary(
        run_id=run.id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        total_cost=run.total_cost,
        metrics=_metrics_from_analyses(analyses, total_responses),
        sentiment=_sentiment_counts(analyses),
    )


@router.get("/by-source", response_model=list[SourceBreakdown])
async def get_by_source(
    run_id: int | None = Query(None, description="Filter by run ID"),
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(None, description="Exclude prompts with this intent"),
    db: AsyncSession = Depends(get_db),
) -> list[SourceBreakdown]:
    """Per-source visibility breakdown for a single run (or all runs if omitted).

    Iterates `app.sources.SOURCES` so the result row order matches the
    UI everywhere. Sources with no responses in scope return zero metrics
    rather than being omitted, so the UI can show "this source ran but
    didn't pick anything up".
    """
    brand_ids = await _resolve_brand_ids(db, brand_id)

    # Total responses per source
    totals_q = select(Response.source, func.count(Response.id)).group_by(Response.source)
    if run_id is not None:
        totals_q = totals_q.where(Response.run_id == run_id)
    if exclude_intent is not None:
        totals_q = totals_q.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )
    totals_by_source = {src: count for src, count in (await db.execute(totals_q)).all()}

    # Analyses per source
    analyses_by_source: dict[str, list[Analysis]] = {sid: [] for sid in SOURCES}
    if brand_ids:
        analyses_q = (
            select(Analysis, Response.source)
            .join(Response, Response.id == Analysis.response_id)
            .where(Analysis.brand_id.in_(brand_ids))
        )
        if run_id is not None:
            analyses_q = analyses_q.where(Response.run_id == run_id)
        if exclude_intent is not None:
            analyses_q = analyses_q.join(Prompt, Prompt.id == Response.prompt_id).where(
                Prompt.intent != exclude_intent
            )
        for analysis, source in (await db.execute(analyses_q)).all():
            # Tolerate orphan source values (e.g. data from a removed
            # provider) by ignoring them rather than crashing.
            if source in analyses_by_source:
                analyses_by_source[source].append(analysis)

    return [
        SourceBreakdown(
            source=sid,
            source_name=display_name(sid),
            metrics=_metrics_from_analyses(
                analyses_by_source.get(sid, []),
                totals_by_source.get(sid, 0),
            ),
            sentiment=_sentiment_counts(analyses_by_source.get(sid, [])),
        )
        for sid in SOURCES
    ]


@router.get("/prompts", response_model=list[PromptPerformance])
async def get_prompt_performance(
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(None, description="Exclude prompts with this intent"),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[PromptPerformance]:
    """Per-prompt performance: hit rate across all runs + last-run mention status.

    Used for the Prompts page enrichment and the "prompts at risk" widget.
    """
    brand_ids = await _resolve_brand_ids(db, brand_id)

    prompt_q = select(Prompt).options(selectinload(Prompt.responses))
    if exclude_intent is not None:
        prompt_q = prompt_q.where(Prompt.intent != exclude_intent)
    prompts = list((await db.execute(prompt_q)).scalars().all())
    if not prompts:
        return []

    # Latest run id (for last-status)
    latest_run_id = (await db.execute(select(func.max(Run.id)))).scalar()

    # Pull all brand analyses for these prompts in one query
    analyses_by_prompt: dict[int, list[tuple[Analysis, int]]] = {p.id: [] for p in prompts}
    if brand_ids:
        analyses_q = (
            select(Analysis, Response.prompt_id, Response.run_id)
            .join(Response, Response.id == Analysis.response_id)
            .where(
                Analysis.brand_id.in_(brand_ids),
                Response.prompt_id.in_([p.id for p in prompts]),
            )
        )
        if source is not None:
            analyses_q = analyses_q.where(Response.source == source)
        rows = (await db.execute(analyses_q)).all()
        for analysis, prompt_id, run_id in rows:
            analyses_by_prompt[prompt_id].append((analysis, run_id))

    out: list[PromptPerformance] = []
    for prompt in prompts:
        prompt_analyses = analyses_by_prompt.get(prompt.id, [])
        # When filtering to a single source, the denominator is "responses
        # for this prompt FROM THAT SOURCE", not all responses across
        # sources — otherwise hit rate gets nonsense-divided.
        if source is None:
            total = len(prompt.responses)
        else:
            total = sum(1 for r in prompt.responses if r.source == source)
        mentioned = sum(1 for a, _ in prompt_analyses if a.brand_found)
        recommended = sum(1 for a, _ in prompt_analyses if a.recommended)

        # Last-run status: did any response in the latest run mention us?
        last_status: str
        if latest_run_id is None:
            last_status = "no_data"
        else:
            last_run_analyses = [a for a, rid in prompt_analyses if rid == latest_run_id]
            if not last_run_analyses:
                last_status = "no_data"
            elif any(a.brand_found for a in last_run_analyses):
                last_status = "mentioned"
            else:
                last_status = "missing"

        sentiment = _sentiment_counts([a for a, _ in prompt_analyses])
        out.append(
            PromptPerformance(
                prompt_id=prompt.id,
                text=prompt.text,
                intent=prompt.intent,
                tags=prompt.tags,
                enabled=prompt.enabled,
                total_responses=total,
                mentioned_count=mentioned,
                recommended_count=recommended,
                hit_rate=mentioned / total if total else 0.0,
                last_run_status=last_status,
                sentiment=sentiment,
            )
        )
    return out


@router.get("/topics", response_model=list[TopicStat])
async def get_topics(
    dimension: str = Query(
        "tag",
        regex="^(tag|intent)$",
        description="Group by 'tag' (default) or 'intent'.",
    ),
    exclude_intent: IntentType | None = Query(
        IntentType.brand,
        description="Exclude prompts with this intent. Defaults to 'brand' so the "
        "topic comparison is fair — branded queries inflate self-visibility.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[TopicStat]:
    """Per-topic aggregate.

    Topics are either tag values (a prompt with multiple tags counts in
    each bucket; tagless prompts go to '(untagged)') or intent values.

    Adds two metrics over the existing per-prompt rollup the frontend
    used to do: share of voice (self mentions / total brand mentions in
    the cluster) and the top non-self competitor by mention count. Both
    require per-brand visibility per cluster, which the per-prompt
    endpoint doesn't expose.
    """
    self_ids = await _self_brand_ids(db)
    self_id = self_ids[0] if self_ids else None

    brand_by_id: dict[int, Brand] = {
        b.id: b for b in (await db.execute(select(Brand))).scalars().all()
    }

    # Pull every (Prompt, Response, Analysis) row in scope. Each Analysis
    # row carries one brand's verdict for one response, so iterating these
    # gives us per-brand mention counts naturally.
    q = (
        select(Prompt, Response, Analysis)
        .join(Response, Response.prompt_id == Prompt.id)
        .join(Analysis, Analysis.response_id == Response.id)
    )
    if exclude_intent is not None:
        q = q.where(Prompt.intent != exclude_intent)
    if source is not None:
        q = q.where(Response.source == source)
    rows = (await db.execute(q)).all()

    # Per-topic state. Sets dedupe across the (response × brand) cartesian
    # we get from the Analysis join — without them, total_responses would
    # be (responses × brand_count) for each cluster.
    @dataclass
    class _Bucket:
        prompt_ids: set[int] = field(default_factory=set)
        response_ids: set[int] = field(default_factory=set)
        self_mentioned_response_ids: set[int] = field(default_factory=set)
        self_recommended_response_ids: set[int] = field(default_factory=set)
        self_sentiments: list[Sentiment] = field(default_factory=list)
        # Per-brand mentioned-response counts (analysis.brand_found == True).
        per_brand: dict[int, int] = field(default_factory=dict)

    buckets: dict[str, _Bucket] = {}

    def _topic_keys(prompt: Prompt) -> list[str]:
        if dimension == "intent":
            return [prompt.intent.value if hasattr(prompt.intent, "value") else str(prompt.intent)]
        return list(prompt.tags) if prompt.tags else ["(untagged)"]

    seen_self_for_response: set[tuple[str, int]] = set()
    seen_per_brand_response: set[tuple[str, int, int]] = set()

    for prompt, response, analysis in rows:
        for topic in _topic_keys(prompt):
            b = buckets.setdefault(topic, _Bucket())
            b.prompt_ids.add(prompt.id)
            b.response_ids.add(response.id)

            # Per-brand mention count — dedupe per (topic, brand, response)
            # because a response gets one Analysis row per brand, and we
            # don't want to double-count a competitor's mention.
            if analysis.brand_found:
                key = (topic, analysis.brand_id, response.id)
                if key not in seen_per_brand_response:
                    seen_per_brand_response.add(key)
                    b.per_brand[analysis.brand_id] = b.per_brand.get(analysis.brand_id, 0) + 1

            # Self-brand specifics — collect each response only once even
            # though the iteration may visit it multiple times via different
            # brand analyses for the same response.
            if self_id is not None and analysis.brand_id == self_id:
                self_key = (topic, response.id)
                if self_key not in seen_self_for_response:
                    seen_self_for_response.add(self_key)
                    if analysis.brand_found:
                        b.self_mentioned_response_ids.add(response.id)
                    if analysis.recommended:
                        b.self_recommended_response_ids.add(response.id)
                    b.self_sentiments.append(analysis.sentiment)

    out: list[TopicStat] = []
    for topic, b in buckets.items():
        total_responses = len(b.response_ids)
        mentioned_count = len(b.self_mentioned_response_ids)
        recommended_count = len(b.self_recommended_response_ids)
        total_brand_mentions = sum(b.per_brand.values())
        sov = mentioned_count / total_brand_mentions if total_brand_mentions > 0 else 0.0
        # Top competitor — highest mention count among non-self brands.
        # Pre-filter to brands we still know about (brand row could have
        # been deleted between runs; we just skip the orphan).
        comp_entries = [
            (bid, count)
            for bid, count in b.per_brand.items()
            if bid != self_id and bid in brand_by_id and count > 0
        ]
        comp_entries.sort(key=lambda x: x[1], reverse=True)
        top_competitor = (
            TopicCompetitor(
                brand_id=comp_entries[0][0],
                brand_name=brand_by_id[comp_entries[0][0]].name,
                mention_count=comp_entries[0][1],
            )
            if comp_entries
            else None
        )

        # Sentiment counts for self-brand only — matches what the per-prompt
        # rollup does. A None entry means we have no analysis for that
        # response (shouldn't happen for self_id but guarded anyway).
        s_pos = sum(1 for s in b.self_sentiments if s == Sentiment.positive)
        s_neu = sum(1 for s in b.self_sentiments if s == Sentiment.neutral)
        s_neg = sum(1 for s in b.self_sentiments if s == Sentiment.negative)

        out.append(
            TopicStat(
                topic=topic,
                prompt_count=len(b.prompt_ids),
                total_responses=total_responses,
                mentioned_count=mentioned_count,
                recommended_count=recommended_count,
                hit_rate=(mentioned_count / total_responses) if total_responses else 0.0,
                recommendation_rate=(
                    recommended_count / total_responses if total_responses else 0.0
                ),
                sentiment=SentimentCounts(positive=s_pos, neutral=s_neu, negative=s_neg),
                share_of_voice=sov,
                total_brand_mentions=total_brand_mentions,
                top_competitor=top_competitor,
            )
        )

    out.sort(key=lambda r: r.total_responses, reverse=True)
    return out


@router.get("/topics/graph", response_model=TopicGraph)
async def get_topic_graph(
    dimension: str = Query(
        "tag",
        regex="^(tag|intent)$",
        description="Group prompts by 'tag' (default) or 'intent'.",
    ),
    exclude_intent: IntentType | None = Query(
        IntentType.brand,
        description="Exclude prompts with this intent. Defaults to 'brand' so the "
        "graph reflects organic visibility.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    min_edge_weight: int = Query(
        1, ge=1, description="Drop edges below this weight to reduce visual noise."
    ),
    top_topics: int = Query(
        20,
        ge=1,
        le=200,
        description="Cap on the number of topic nodes — pick the largest by response "
        "count. By-tag is otherwise unreadable for prompt sets with many fine-grained tags.",
    ),
    db: AsyncSession = Depends(get_db),
) -> TopicGraph:
    """Topic ↔ brand graph.

    Two node kinds — `topic` (tag value or intent value) and `brand`
    (every tracked brand row). Edges are topic↔brand only, weighted
    by the number of responses in the topic where the brand was
    mentioned. Node `weight` is the topic's response count or the
    brand's total mention count across kept topics, so the layout can
    size nodes proportionally.

    Note on sources: an earlier draft of this view also emitted source
    nodes + topic↔source edges. It made the graph an unreadable
    hairball (every topic connects to every source). The dashboard's
    source-filter chip answers the "per-source" question with far
    less visual debt; we just call this endpoint with `?source=…` to
    re-derive a source-scoped graph instead of overlaying.
    """
    brands = list((await db.execute(select(Brand))).scalars().all())

    # One join over the (Prompt, Response, Analysis) triple — same
    # shape as /topics. Iterating these lets us tally per-topic-per-
    # brand mention counts AND per-topic-per-source response counts in
    # a single pass without re-querying.
    q = (
        select(Prompt, Response, Analysis)
        .join(Response, Response.prompt_id == Prompt.id)
        .join(Analysis, Analysis.response_id == Response.id)
    )
    if exclude_intent is not None:
        q = q.where(Prompt.intent != exclude_intent)
    if source is not None:
        q = q.where(Response.source == source)
    rows = (await db.execute(q)).all()

    def _topic_keys(prompt: Prompt) -> list[str]:
        if dimension == "intent":
            v = prompt.intent
            return [v.value if hasattr(v, "value") else str(v)]
        return list(prompt.tags) if prompt.tags else ["(untagged)"]

    # Per-topic dedupe state (one Analysis row per brand per response,
    # so without dedup we'd over-count topic_responses by N_brands).
    topic_responses: dict[str, set[int]] = {}
    # (topic, brand_id) -> set of response_ids where this brand was mentioned
    topic_brand_resp: dict[tuple[str, int], set[int]] = {}

    for prompt, response, analysis in rows:
        for topic in _topic_keys(prompt):
            topic_responses.setdefault(topic, set()).add(response.id)
            if analysis.brand_found:
                topic_brand_resp.setdefault((topic, analysis.brand_id), set()).add(response.id)

    # Cap topic nodes to the largest N — by-tag clusters can otherwise
    # produce 50+ singleton topics that drown the layout. The cap is
    # applied to the topic SET; edges referencing dropped topics are
    # filtered out below.
    topics_sorted = sorted(topic_responses.items(), key=lambda kv: len(kv[1]), reverse=True)[
        :top_topics
    ]
    kept_topics = {topic for topic, _ in topics_sorted}

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    for topic, resp_ids in topics_sorted:
        nodes.append(
            GraphNode(
                id=f"topic:{topic}",
                kind="topic",
                label=topic,
                weight=len(resp_ids),
            )
        )

    # Brand nodes: we emit every tracked brand even if it has no
    # mentions in scope, so the graph stays consistent across runs
    # (an absent competitor appears as a disconnected node).
    brand_total: dict[int, int] = {b.id: 0 for b in brands}
    for (topic, brand_id), resp_ids in topic_brand_resp.items():
        if topic not in kept_topics:
            continue
        brand_total[brand_id] = brand_total.get(brand_id, 0) + len(resp_ids)
    for b in brands:
        nodes.append(
            GraphNode(
                id=f"brand:{b.id}",
                kind="brand",
                label=b.name,
                weight=brand_total.get(b.id, 0),
                is_self=b.is_self,
            )
        )

    # Edges: topic↔brand only. Source nodes used to live here too but
    # made the graph an unreadable hairball — every topic connected to
    # every source. The source-filter chip on the dashboard answers the
    # "per-source" question better than a node would.
    for (topic, brand_id), resp_ids in topic_brand_resp.items():
        if topic not in kept_topics:
            continue
        weight = len(resp_ids)
        if weight < min_edge_weight or brand_id not in brand_total:
            continue
        edges.append(
            GraphEdge(
                source=f"topic:{topic}",
                target=f"brand:{brand_id}",
                kind="topic_brand",
                weight=weight,
            )
        )

    return TopicGraph(nodes=nodes, edges=edges)


@router.get("/competitors", response_model=list[CompetitorShare])
async def get_competitor_share(
    run_id: int | None = Query(None),
    include_self: bool = Query(False),
    exclude_intent: IntentType | None = Query(
        None, description="Exclude prompts with this intent (e.g. 'brand')"
    ),
    db: AsyncSession = Depends(get_db),
) -> list[CompetitorShare]:
    """Share of voice across brands.

    Defaults to competitors only — pass `include_self=true` to also include
    self-brands in the result (useful for stacked-bar visualisations).
    """
    query = (
        select(
            Brand.id,
            Brand.name,
            Brand.is_self,
            func.count(Analysis.id).filter(Analysis.brand_found.is_(True)).label("mentions"),
        )
        .join(Analysis, Analysis.brand_id == Brand.id)
        .join(Response, Response.id == Analysis.response_id)
        .group_by(Brand.id, Brand.name, Brand.is_self)
    )

    if run_id is not None:
        query = query.where(Response.run_id == run_id)
    if exclude_intent is not None:
        query = query.join(Prompt, Prompt.id == Response.prompt_id).where(
            Prompt.intent != exclude_intent
        )

    rows = (await db.execute(query)).all()
    visible = [r for r in rows if r.mentions > 0 and (include_self or not r.is_self)]
    total = sum(r.mentions for r in visible)

    return [
        CompetitorShare(
            brand_id=r.id,
            brand_name=r.name,
            is_self=r.is_self,
            mention_count=r.mentions,
            share_of_voice=r.mentions / total if total else 0.0,
        )
        for r in sorted(visible, key=lambda r: r.mentions, reverse=True)
    ]


@router.get("/citations", response_model=list[CitationStat])
async def get_citations(
    run_id: int | None = Query(None, description="Filter to a single run"),
    intent: IntentType | None = Query(None, description="Filter by prompt intent"),
    days: int | None = Query(
        None,
        ge=1,
        description="Limit to responses created in the last N days. Ignored if run_id is set.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[CitationStat]:
    """Top cited domains for the configured scope.

    Aggregates `Response.source_urls` across all responses matching the
    filters, normalizes each URL to its bare host (no `www.`, no port),
    and counts how many *responses* (not raw URLs) cited each host at
    least once. The dedupe inside a single response keeps a chatty answer
    that links Allegro five times from drowning out responses that linked
    Allegro once.

    Hosts that match a tracked `Brand.domains` entry are enriched with
    `brand_id` / `brand_name` / `is_self` so the UI can label them. The
    matching is subdomain-tolerant, so registering `example.com`
    catches `sklep.example.com` too.
    """
    # Build the response query in scope.
    q = select(Response.source_urls).join(Prompt, Prompt.id == Response.prompt_id)
    if run_id is not None:
        q = q.where(Response.run_id == run_id)
    if intent is not None:
        q = q.where(Prompt.intent == intent)
    if run_id is None and days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(Response.created_at >= cutoff)
    if source is not None:
        q = q.where(Response.source == source)

    rows = (await db.execute(q)).all()

    # Aggregate in Python — volumes are small (a few thousand URLs at
    # most) and the URL parsing / normalization is awkward in pure SQL.
    counts: Counter[str] = Counter()
    total_responses = 0
    for (source_urls,) in rows:
        total_responses += 1
        if not source_urls:
            continue
        seen_in_response: set[str] = set()
        for url in source_urls:
            host = normalize_citation_host(url)
            if host is None or host in seen_in_response:
                continue
            seen_in_response.add(host)
            counts[host] += 1

    if not counts:
        return []

    # Enrich with tracked-brand metadata.
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


@router.get("/citation-gap", response_model=list[CitationStat])
async def get_citation_gap(
    run_id: int | None = Query(None, description="Filter to a single run"),
    days: int | None = Query(
        None,
        ge=1,
        description="Limit to responses in the last N days. Ignored if run_id is set.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[CitationStat]:
    """Citation gap — domains cited where self brand wasn't mentioned.

    Inverse of the standard citations endpoint: aggregates `source_urls`
    only over non-brand-intent responses where the self brand was *not*
    mentioned. Those domains are content / authority gaps the brand
    could plug — get cited there, the AI starts surfacing you for the
    same prompts.

    Same response shape as `/citations` so the UI can render either with
    the same component.
    """
    self_brand_ids = await _self_brand_ids(db)
    if not self_brand_ids:
        return []

    # Find responses where:
    #   - prompt is non-brand-intent
    #   - in the optional run / time scope
    #   - self brand has no `brand_found = True` analysis
    response_q = (
        select(Response.id, Response.source_urls)
        .join(Prompt, Prompt.id == Response.prompt_id)
        .where(Prompt.intent != IntentType.brand)
    )
    if run_id is not None:
        response_q = response_q.where(Response.run_id == run_id)
    if run_id is None and days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        response_q = response_q.where(Response.created_at >= cutoff)
    if source is not None:
        response_q = response_q.where(Response.source == source)

    response_rows = (await db.execute(response_q)).all()
    if not response_rows:
        return []

    response_ids = [row[0] for row in response_rows]

    # Pull self-brand analyses for those responses; the response is a "gap"
    # response if no self analysis with brand_found=True exists for it.
    mentioned_response_ids: set[int] = set()
    if response_ids:
        analysis_rows = (
            await db.execute(
                select(Analysis.response_id).where(
                    Analysis.brand_id.in_(self_brand_ids),
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
        seen_in_response: set[str] = set()
        for url in source_urls:
            host = normalize_citation_host(url)
            if host is None or host in seen_in_response:
                continue
            seen_in_response.add(host)
            counts[host] += 1

    if not counts:
        return []

    brands = list((await db.execute(select(Brand))).scalars().all())
    brand_index = build_brand_domain_index(brands)

    out: list[CitationStat] = []
    for host, count in counts.most_common(limit):
        brand = match_brand_for_host(host, brand_index)
        # Filter out the self-brand row in the gap view — by definition
        # the brand wasn't mentioned, but if the AI cited the self
        # domain elsewhere the row would be misleading here.
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


@router.get("/search-terms", response_model=list[SearchTermStat])
async def get_search_terms(
    run_id: int | None = Query(None),
    days: int | None = Query(
        None,
        ge=1,
        description="Limit to responses in the last N days. Ignored if run_id is set.",
    ),
    limit: int = Query(50, ge=1, le=200),
    min_count: int = Query(2, ge=1, description="Drop one-off terms below this count."),
    db: AsyncSession = Depends(get_db),
) -> list[SearchTermStat]:
    """Frequency table of `Response.search_queries`.

    These are the terms the AI actually issued during grounding — high-
    signal for content strategy because they reveal what AIs *search for*
    when answering category questions, not what users typed in.

    Cleaning is intentionally light: lower-case, collapse whitespace,
    trim. No stop-word removal or stemming.
    """
    q = select(Response.search_queries, Response.prompt_id, Response.source).where(
        Response.search_queries.is_not(None)
    )
    if run_id is not None:
        q = q.where(Response.run_id == run_id)
    if run_id is None and days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        q = q.where(Response.created_at >= cutoff)

    rows = (await db.execute(q)).all()
    if not rows:
        return []

    # term -> {count, prompts, sources}
    counts: Counter[str] = Counter()
    prompts_by_term: dict[str, set[int]] = {}
    sources_by_term: dict[str, set[str]] = {}
    for search_queries, prompt_id, source in rows:
        if not search_queries:
            continue
        # Dedupe terms inside a single response so a chatty AI that issued
        # the same query 3 times doesn't dominate the table.
        seen: set[str] = set()
        for raw in search_queries:
            term = " ".join(raw.split()).lower()
            if not term or term in seen:
                continue
            # Skip URL fragments — some grounding pipelines emit them.
            if term.startswith(("http://", "https://", "www.")) or "/" in term and " " not in term:
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


@router.get("/funnel", response_model=FunnelMetrics)
async def get_funnel(
    run_id: int | None = Query(None, description="Filter by run ID"),
    brand_id: int | None = Query(None, description="Brand to measure (default: self)"),
    exclude_intent: IntentType | None = Query(
        IntentType.brand,
        description="Exclude prompts with this intent. Defaults to 'brand' so the "
        "funnel reflects organic discovery, not branded queries.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    db: AsyncSession = Depends(get_db),
) -> FunnelMetrics:
    """Compute the 5-stage GEO funnel for self (or a specific brand).

    Discovery is detected from `Response.search_queries` — we lower-case
    each query and check whether the brand name or any of its domains /
    aliases is a substring. Subdomain handling matches the brand-domain
    matcher elsewhere (`example.com` catches `sklep.example.com`).
    """
    brand_ids = await _resolve_brand_ids(db, brand_id)
    empty_stage = lambda label: FunnelStage(label=label, count=0, rate=0.0)  # noqa: E731
    empty = FunnelMetrics(
        total_responses=0,
        discovery=empty_stage("discovery"),
        citation=empty_stage("citation"),
        mention=empty_stage("mention"),
        recommendation=empty_stage("recommendation"),
        link=empty_stage("link"),
    )
    if not brand_ids:
        return empty

    # Pull responses + analyses for the scope, joined so we can compute
    # discovery (response-level field) and the analysis-level stages in
    # one pass.
    q = (
        select(Response, Analysis)
        .join(Analysis, (Analysis.response_id == Response.id) & (Analysis.brand_id.in_(brand_ids)))
        .join(Prompt, Prompt.id == Response.prompt_id)
    )
    if run_id is not None:
        q = q.where(Response.run_id == run_id)
    if exclude_intent is not None:
        q = q.where(Prompt.intent != exclude_intent)
    if source is not None:
        q = q.where(Response.source == source)
    rows = (await db.execute(q)).all()

    if not rows:
        return empty

    # Precompute brand-name + domain + alias needles for substring matching
    # against search_queries. Domain stripping (drop leading "www.") makes
    # "www.example.com" in source data match a tracked "example.com".
    brand_rows = list(
        (await db.execute(select(Brand).where(Brand.id.in_(brand_ids)))).scalars().all()
    )
    needles: set[str] = set()
    for b in brand_rows:
        if b.name:
            needles.add(b.name.lower())
        for d in b.domains or []:
            d2 = d.lower().strip()
            if d2.startswith("www."):
                d2 = d2[4:]
            if d2:
                needles.add(d2)
        for a in b.aliases or []:
            if a:
                needles.add(a.lower())

    total = len(rows)
    discovery = citation = mention = recommendation = link = 0
    for response, analysis in rows:
        if response.search_queries:
            joined = " ".join(response.search_queries).lower()
            if any(n in joined for n in needles):
                discovery += 1
        if analysis.our_pages:
            citation += 1
        if analysis.brand_found:
            mention += 1
        if analysis.recommended:
            recommendation += 1
        if analysis.link_present:
            link += 1

    def stage(label: str, count: int) -> FunnelStage:
        return FunnelStage(label=label, count=count, rate=count / total)

    return FunnelMetrics(
        total_responses=total,
        discovery=stage("discovery", discovery),
        citation=stage("citation", citation),
        mention=stage("mention", mention),
        recommendation=stage("recommendation", recommendation),
        link=stage("link", link),
    )


@router.get("/comparison", response_model=BrandComparison)
async def get_brand_comparison(
    run_id: int | None = Query(None, description="Filter to a single run"),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    db: AsyncSession = Depends(get_db),
) -> BrandComparison:
    """Head-to-head comparison of all tracked brands.

    Always excludes brand-intent prompts so the comparison is fair — nobody
    gets an unfair boost from their own branded queries. Each brand gets its
    own VisibilityMetrics computed against the same pool of responses.
    """
    brands = list((await db.execute(select(Brand))).scalars().all())
    if not brands:
        return BrandComparison(run_id=run_id, total_responses=0, brands=[])

    # Total non-brand responses in scope (shared denominator for all brands).
    total_q = (
        select(func.count(Response.id))
        .join(Prompt, Prompt.id == Response.prompt_id)
        .where(Prompt.intent != IntentType.brand)
    )
    if run_id is not None:
        total_q = total_q.where(Response.run_id == run_id)
    if source is not None:
        total_q = total_q.where(Response.source == source)
    total_responses = (await db.execute(total_q)).scalar() or 0

    # All analyses for non-brand prompts, bucketed by brand_id.
    analyses_q = (
        select(Analysis)
        .join(Response, Response.id == Analysis.response_id)
        .join(Prompt, Prompt.id == Response.prompt_id)
        .where(Prompt.intent != IntentType.brand)
    )
    if run_id is not None:
        analyses_q = analyses_q.where(Response.run_id == run_id)
    if source is not None:
        analyses_q = analyses_q.where(Response.source == source)
    all_analyses = list((await db.execute(analyses_q)).scalars().all())

    by_brand: dict[int, list[Analysis]] = {b.id: [] for b in brands}
    for a in all_analyses:
        if a.brand_id in by_brand:
            by_brand[a.brand_id].append(a)

    entries: list[BrandComparisonEntry] = []
    for brand in brands:
        brand_analyses = by_brand.get(brand.id, [])
        entries.append(
            BrandComparisonEntry(
                brand_id=brand.id,
                brand_name=brand.name,
                is_self=brand.is_self,
                metrics=_metrics_from_analyses(brand_analyses, total_responses),
                sentiment=_sentiment_counts(brand_analyses),
            )
        )

    # Sort: self brands first, then by visibility rate descending.
    entries.sort(
        key=lambda e: (not e.is_self, -e.metrics.visibility_rate),
    )

    return BrandComparison(
        run_id=run_id,
        total_responses=total_responses,
        brands=entries,
    )


# ---------- recommendations ----------


@router.get("/recommendations", response_model=list[PromptRecommendation])
async def get_recommendations(
    threshold: float = Query(
        0.3,
        ge=0,
        le=1,
        description="Self hit-rate ceiling. Prompts with hit_rate <= threshold "
        "and at least one competitor mention are surfaced as opportunities.",
    ),
    source: str | None = Query(
        None, description="Filter to one source id (e.g. 'brightdata_chatgpt')"
    ),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[PromptRecommendation]:
    """Per-prompt opportunity list.

    For every non-brand-intent prompt where the self brand is missing-or-rare
    and at least one competitor is mentioned, returns a card with the top
    competitor, the domains they were cited from, the search queries the AI
    issued, and a rule-based recommendation.

    The "winnable prompt" insight: if a competitor is mentioned for a query,
    the AI is willing to surface brand-similar sources for that query. The
    self brand just isn't being picked up — yet.
    """
    self_brand_ids = await _self_brand_ids(db)
    if not self_brand_ids:
        return []
    self_brand_id = self_brand_ids[0]  # we currently support one self-brand

    # All non-brand-intent prompts plus their responses
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

    # Pull every analysis for our prompts in one query, plus the matching
    # response so we can join citations and queries by response id.
    analysis_q = (
        select(Analysis, Response, Brand)
        .join(Response, Response.id == Analysis.response_id)
        .join(Brand, Brand.id == Analysis.brand_id)
        .where(Response.prompt_id.in_(prompt_ids))
    )
    if source is not None:
        analysis_q = analysis_q.where(Response.source == source)
    analysis_rows = (await db.execute(analysis_q)).all()

    # Group by prompt → list of (analysis, response, brand)
    by_prompt: dict[int, list] = {pid: [] for pid in prompt_ids}
    for analysis, response, brand in analysis_rows:
        by_prompt[response.prompt_id].append((analysis, response, brand))

    out: list[PromptRecommendation] = []
    for prompt in prompts:
        rows = by_prompt.get(prompt.id, [])
        # When filtered to one source, the denominator is responses for
        # this prompt FROM THAT SOURCE — otherwise hit rate is wrong.
        if source is None:
            total_responses = len(prompt.responses)
        else:
            total_responses = sum(1 for r in prompt.responses if r.source == source)
        if total_responses == 0:
            continue

        self_analyses = [a for a, _, b in rows if b.id == self_brand_id]
        self_mentioned = sum(1 for a in self_analyses if a.brand_found)
        self_hit_rate = self_mentioned / total_responses if total_responses else 0.0

        if self_hit_rate > threshold:
            continue  # we already win this prompt enough

        # Bucket competitor analyses (brand_found only)
        comp_buckets: dict[int, list] = {}
        comp_meta: dict[int, str] = {}
        for analysis, _resp, brand in rows:
            if brand.id == self_brand_id or not analysis.brand_found:
                continue
            comp_buckets.setdefault(brand.id, []).append(analysis)
            comp_meta[brand.id] = brand.name

        if not comp_buckets:
            continue  # no competitor either — no clear opportunity

        # Build CompetitorOpportunity entries, sort by mention count desc
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

        top_competitor_visibility = top_competitor.mention_count / total_responses
        opportunity_score = top_competitor_visibility * (1 - self_hit_rate)

        # Domains cited in responses where the top competitor was mentioned
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
        # Drop self-brand domains from the cited list (we don't want to
        # recommend our own pages to ourselves).
        self_brand_row = (
            await db.execute(select(Brand).where(Brand.id == self_brand_id))
        ).scalar_one_or_none()
        self_domains = (
            {d.lower() for d in (self_brand_row.domains or [])} if self_brand_row else set()
        )
        cited_domains = [
            host
            for host, _ in cited_counter.most_common(10)
            if not any(sd in host for sd in self_domains)
        ][:5]

        # Search queries triggered, deduped + capped
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
                self_total_responses=total_responses,
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
