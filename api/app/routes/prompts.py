from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.geo_catalog import (
    DEFAULT_COUNTRY,
    CountryCode,
    LanguageCode,
    get_country,
)
from app.models import Brand, Prompt, Response, Sentiment
from app.schemas import (
    GeneratePromptsRequest,
    GeneratePromptsResponse,
    PromptCompetitorStat,
    PromptCreate,
    PromptDetail,
    PromptOut,
    PromptRecentResponse,
    PromptRunPoint,
    PromptSourceStats,
)
from app.services.citations import normalize_brand_domain
from app.services.metrics import (
    metrics_from_analyses as _metrics_from_analyses,
    self_brand_ids as _self_brand_ids,
)
from app.services.prompt_generator import GenerateRequest, PromptGenerator, get_generator
from app.sources import display_name

router = APIRouter()


async def _resolve_geo_for_domain(
    db: AsyncSession, domain: str
) -> tuple[CountryCode, LanguageCode]:
    """Find the Brand row whose domain matches and return its
    (country_code, language_code) as ISO codes. Falls back to (US, en).
    """
    target = normalize_brand_domain(domain)
    rows = (await db.execute(select(Brand))).scalars().all()
    for b in rows:
        for d in b.domains or []:
            if normalize_brand_domain(d) == target:
                # Validate against the catalog — a brand row carrying a
                # code the catalog no longer knows about falls back to US.
                country_iso = CountryCode(b.country_code)
                if get_country(country_iso) is None:
                    country_iso = DEFAULT_COUNTRY.iso_code
                return country_iso, LanguageCode(b.language_code)
    return DEFAULT_COUNTRY.iso_code, LanguageCode("en")


@router.post("/generate", response_model=GeneratePromptsResponse)
async def generate_prompts(
    data: GeneratePromptsRequest,
    db: AsyncSession = Depends(get_db),
    generator: PromptGenerator = Depends(get_generator),
):
    """Generate a benchmark query set for a website.

    Delegates to the injected `PromptGenerator` implementation. The
    response shape is preserved for backwards compatibility — `prompts`
    becomes `queries`, and `meta` is unpacked into the top-level fields
    the legacy schema expects.

    Geo (`country_code` / `language_code`) is ISO-coded and drives any
    geo-aware seed fetching the implementation does. The request can
    specify them explicitly; if omitted, the endpoint matches
    `data.url` against an existing Brand row and uses its geo. Final
    fallback is US/English.
    """
    country_code: CountryCode | None = CountryCode(data.country_code) if data.country_code else None
    language_code: LanguageCode | None = (
        LanguageCode(data.language_code) if data.language_code else None
    )
    if country_code is None or language_code is None:
        resolved_country, resolved_lang = await _resolve_geo_for_domain(db, data.url)
        country_code = country_code or resolved_country
        language_code = language_code or resolved_lang

    request = GenerateRequest(
        domain=data.url,
        num_queries=data.num_queries,
        country_code=country_code,
        language_code=language_code,
    )
    result = await generator.generate(request, db=db)

    meta = result.meta or {}
    return {
        "domain": result.domain,
        "pages_found": meta.get("pages_found") or 0,
        "client_profile_id": meta.get("client_profile_id"),
        "profile": meta.get("profile"),
        "competitors": meta.get("competitors") or [],
        "queries": [
            {
                "text": p.text,
                "intent": p.intent,
                "tags": p.tags,
                "length_mode": p.length_mode,
                "buyer_stage": p.buyer_stage,
                "shape": p.shape,
                "seed_source": p.seed_source,
                "seed_keyword": p.seed_keyword,
                "seed_search_volume": p.seed_search_volume,
                "seed_position": p.seed_position,
            }
            for p in result.prompts
        ],
    }


@router.get("", response_model=list[PromptOut])
async def list_prompts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Prompt).order_by(Prompt.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=PromptOut, status_code=201)
async def create_prompt(data: PromptCreate, db: AsyncSession = Depends(get_db)):
    prompt = Prompt(**data.model_dump())
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.get("/{prompt_id}", response_model=PromptOut)
async def get_prompt(prompt_id: int, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return prompt


# How many recent responses to return on the detail page. The full list lives
# behind /responses — this is just enough to give the user a quick snapshot.
_RECENT_RESPONSES_LIMIT = 10
# Trend chart looks back this many runs.
_TREND_RUNS_LIMIT = 20
# Snippet length for the recent-responses preview.
_SNIPPET_CHARS = 200


@router.get("/{prompt_id}/detail", response_model=PromptDetail)
async def get_prompt_detail(prompt_id: int, db: AsyncSession = Depends(get_db)) -> PromptDetail:
    """Everything the prompt detail page needs in one round-trip.

    Computes per-LLM aggregates, the per-run trend, competitor share for this
    prompt, and the most recent responses (with snippets, not full text — the
    user clicks through to /responses for the full view).
    """
    prompt = await db.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    self_ids = await _self_brand_ids(db)

    # Pull every response for this prompt with eager-loaded analyses + LLM + run.
    # MVP scale: per-prompt response counts are bounded (n_runs × n_llms),
    # so a single eager-loaded query is simpler than several aggregations.
    responses = list(
        (
            await db.execute(
                select(Response)
                .where(Response.prompt_id == prompt_id)
                .options(
                    selectinload(Response.analyses),
                    selectinload(Response.run),
                )
                .order_by(Response.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    # Self-brand analyses for the overall metrics
    self_analyses = [a for r in responses for a in r.analyses if a.brand_id in self_ids]
    metrics = _metrics_from_analyses(self_analyses, len(responses))

    # ---- Per-source aggregates ----
    per_source_buckets: dict[str, dict] = {}
    for r in responses:
        bucket = per_source_buckets.setdefault(
            r.source,
            {"total": 0, "self_analyses": []},
        )
        bucket["total"] += 1
        for a in r.analyses:
            if a.brand_id in self_ids:
                bucket["self_analyses"].append(a)

    per_source: list[PromptSourceStats] = []
    for source_id, bucket in per_source_buckets.items():
        analyses = bucket["self_analyses"]
        total = bucket["total"]
        mentioned = sum(1 for a in analyses if a.brand_found)
        recommended = sum(1 for a in analyses if a.recommended)
        per_source.append(
            PromptSourceStats(
                source=source_id,
                source_name=display_name(source_id),
                total_responses=total,
                mentioned_count=mentioned,
                recommended_count=recommended,
                hit_rate=mentioned / total if total else 0.0,
            )
        )
    per_source.sort(key=lambda s: s.hit_rate, reverse=True)

    # ---- Trend per run (oldest → newest, capped to last N runs) ----
    run_buckets: dict[int, dict] = {}
    for r in responses:
        bucket = run_buckets.setdefault(
            r.run_id,
            {
                "run": r.run,
                "total": 0,
                "mentioned": 0,
            },
        )
        bucket["total"] += 1
        for a in r.analyses:
            if a.brand_id in self_ids and a.brand_found:
                bucket["mentioned"] += 1
                break  # at most one self-mention per response

    trend_sorted = sorted(run_buckets.values(), key=lambda b: b["run"].started_at)
    trend = [
        PromptRunPoint(
            run_id=b["run"].id,
            started_at=b["run"].started_at,
            total_responses=b["total"],
            mentioned_count=b["mentioned"],
            hit_rate=b["mentioned"] / b["total"] if b["total"] else 0.0,
        )
        for b in trend_sorted[-_TREND_RUNS_LIMIT:]
    ]

    # ---- Competitors winning this prompt ----
    competitor_counts: dict[int, int] = {}
    for r in responses:
        for a in r.analyses:
            if a.brand_id in self_ids or not a.brand_found:
                continue
            competitor_counts[a.brand_id] = competitor_counts.get(a.brand_id, 0) + 1

    competitors: list[PromptCompetitorStat] = []
    if competitor_counts:
        brand_rows = (
            (await db.execute(select(Brand).where(Brand.id.in_(competitor_counts.keys()))))
            .scalars()
            .all()
        )
        for brand in brand_rows:
            competitors.append(
                PromptCompetitorStat(
                    brand_id=brand.id,
                    brand_name=brand.name,
                    mention_count=competitor_counts[brand.id],
                )
            )
        competitors.sort(key=lambda c: c.mention_count, reverse=True)

    # ---- Recent responses (already ordered desc above) ----
    recent: list[PromptRecentResponse] = []
    for r in responses[:_RECENT_RESPONSES_LIMIT]:
        self_a = next((a for a in r.analyses if a.brand_id in self_ids), None)
        snippet = (r.text or "").strip().replace("\n", " ")
        if len(snippet) > _SNIPPET_CHARS:
            snippet = snippet[:_SNIPPET_CHARS].rstrip() + "…"
        recent.append(
            PromptRecentResponse(
                response_id=r.id,
                run_id=r.run_id,
                source=r.source,
                source_name=display_name(r.source),
                created_at=r.created_at,
                snippet=snippet,
                mentioned=bool(self_a and self_a.brand_found),
                recommended=bool(self_a and self_a.recommended),
                sentiment=self_a.sentiment if self_a else Sentiment.not_mentioned,
                error_kind=r.error_kind,
            )
        )

    return PromptDetail(
        id=prompt.id,
        text=prompt.text,
        intent=prompt.intent,
        tags=prompt.tags,
        enabled=prompt.enabled,
        created_at=prompt.created_at,
        metrics=metrics,
        per_source=per_source,
        trend=trend,
        competitors=competitors,
        recent_responses=recent,
    )


@router.delete("/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: int, db: AsyncSession = Depends(get_db)):
    prompt = await db.get(Prompt, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")
    await db.delete(prompt)
    await db.commit()
