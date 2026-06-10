"""Prompt-generator routes for the review page (kick off + poll)."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session, get_db
from app.geo_catalog import (
    DEFAULT_COUNTRY,
    CountryCode,
    LanguageCode,
    get_country,
)
from app.models import Brand, GeneratorRun, PipelineRun
from app.services.citations import normalize_brand_domain
from app.services.prompt_generator import (
    GenerateRequest,
    GenerateResult,
    PromptGenerator,
    get_generator,
)
from app.services.prompt_generator.default import DefaultPromptGenerator

logger = logging.getLogger(__name__)

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


class GeneratorRunRequest(BaseModel):
    domain: str = Field(..., description="Bare domain or URL")
    num_queries: int = Field(50, ge=1, le=200)


def _result_to_run(result: GenerateResult, fallback_domain: str) -> GeneratorRun:
    """Materialize a GeneratorRun row from a `GenerateResult`."""
    meta = result.meta or {}
    corpus = meta.get("corpus") or {}
    personas = meta.get("personas") or []
    keyword_signals = meta.get("keyword_signals") or {}
    queries = [
        {
            "text": p.text,
            "intent": p.intent,
            "length_mode": p.length_mode,
            "buyer_stage": p.buyer_stage,
            "shape": p.shape,
            "tags": p.tags,
            "seed_source": p.seed_source,
            "seed_keyword": p.seed_keyword,
            "seed_search_volume": p.seed_search_volume,
            "seed_position": p.seed_position,
        }
        for p in result.prompts
    ]
    return GeneratorRun(
        domain=result.domain or normalize_brand_domain(fallback_domain),
        sources_meta={
            "pages": int(meta.get("pages_found") or 0),
            "competitor_count": len(meta.get("competitors") or []),
            "client_keywords_count": len(keyword_signals.get("client_keywords") or []),
            "corpus_counts": corpus.get("counts") or {},
            "persona_count": len(personas),
        },
        profile=meta.get("profile") or {},
        competitors=meta.get("competitors") or [],
        corpus=corpus,
        personas=personas,
        keyword_signals=keyword_signals,
        queries=queries,
    )


def _serialize_run(row: GeneratorRun) -> dict:
    return {
        "id": row.id,
        "domain": row.domain,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "sources_meta": row.sources_meta,
        "profile": row.profile,
        "competitors": row.competitors,
        "corpus": row.corpus,
        "personas": row.personas,
        "keyword_signals": row.keyword_signals,
        "queries": row.queries,
    }


@router.post("/run")
async def run_generator(
    req: GeneratorRunRequest,
    db: AsyncSession = Depends(get_db),
    generator: PromptGenerator = Depends(get_generator),
):
    """Run the prompt-generator pipeline synchronously and persist the
    snapshot to `generator_runs`. Returns the persisted row.
    """
    country_code, language_code = await _resolve_geo_for_domain(db, req.domain)

    request = GenerateRequest(
        domain=req.domain,
        num_queries=req.num_queries,
        country_code=country_code,
        language_code=language_code,
    )
    result = await generator.generate(request, db=db)

    row = _result_to_run(result, fallback_domain=req.domain)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _serialize_run(row)


async def _run_pipeline_in_background(
    pipeline_run_id: int,
    domain: str,
    num_queries: int,
    country_code: CountryCode,
    language_code: LanguageCode,
) -> None:
    """Background task body for `POST /generator/run-async`.

    Opens its OWN AsyncSession because the request-scoped session that
    spawned this task is already closed by the time we run. Anything
    that fails inside should be marked on the PipelineRun row, never
    re-raised — the request returned 202 long ago.
    """
    from app.services.pipeline_tracker import PipelineTracker

    async with async_session() as db:
        tracker = PipelineTracker(db, pipeline_run_id)
        generator_run_id: int | None = None
        error: str | None = None
        try:
            request = GenerateRequest(
                domain=domain,
                num_queries=num_queries,
                country_code=country_code,
                language_code=language_code,
            )
            generator = DefaultPromptGenerator(tracker=tracker)
            result = await generator.generate(request, db=db)
            row = _result_to_run(result, fallback_domain=domain)
            db.add(row)
            await db.commit()
            await db.refresh(row)
            generator_run_id = row.id
        except Exception as e:
            logger.exception("Pipeline run %s failed", pipeline_run_id)
            error = f"{type(e).__name__}: {e}"
        finally:
            await tracker.finalize(generator_run_id=generator_run_id, error=error)


@router.post("/run-async")
async def run_generator_async(req: GeneratorRunRequest, db: AsyncSession = Depends(get_db)):
    """Kick off the pipeline as a background task and return immediately.

    Client polls `GET /generator/run-status/{pipeline_run_id}` to watch
    staged progress. On completion, the response carries the final
    generator-run id under `generator_run_id`.
    """
    country_code, language_code = await _resolve_geo_for_domain(db, req.domain)
    target = normalize_brand_domain(req.domain)

    pipeline_row = PipelineRun(domain=target, status="running", stages=[])
    db.add(pipeline_row)
    await db.commit()
    await db.refresh(pipeline_row)

    asyncio.create_task(
        _run_pipeline_in_background(
            pipeline_run_id=pipeline_row.id,
            domain=req.domain,
            num_queries=req.num_queries,
            country_code=country_code,
            language_code=language_code,
        )
    )
    return {
        "pipeline_run_id": pipeline_row.id,
        "status": "running",
        "started_at": pipeline_row.started_at.isoformat() if pipeline_row.started_at else None,
    }


@router.get("/run-status/{pipeline_run_id}")
async def get_run_status(pipeline_run_id: int, db: AsyncSession = Depends(get_db)):
    """Return the current state of an in-flight (or completed) pipeline run.

    When the run is complete and a generator-run row was persisted, the
    final result (profile, competitors, corpus, personas, keyword
    signals, queries) is inlined under `result` so the caller doesn't
    have to make a second fetch.
    """
    row = (
        (await db.execute(select(PipelineRun).where(PipelineRun.id == pipeline_run_id)))
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"no pipeline_run id={pipeline_run_id}")

    result: dict | None = None
    if row.generator_run_id:
        run_row = (
            (await db.execute(select(GeneratorRun).where(GeneratorRun.id == row.generator_run_id)))
            .scalars()
            .first()
        )
        if run_row is not None:
            result = {
                "domain": run_row.domain,
                "profile": run_row.profile,
                "competitors": run_row.competitors,
                "corpus": run_row.corpus,
                "personas": run_row.personas,
                "keyword_signals": run_row.keyword_signals,
                "queries": run_row.queries,
            }

    return {
        "id": row.id,
        "domain": row.domain,
        "status": row.status,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "error": row.error,
        "stages": row.stages or [],
        "generator_run_id": row.generator_run_id,
        "result": result,
    }


@router.get("")
async def list_generator_runs(db: AsyncSession = Depends(get_db)):
    """Latest run per domain — the index of what's been generated."""
    rows = (
        (await db.execute(select(GeneratorRun).order_by(GeneratorRun.created_at.desc())))
        .scalars()
        .all()
    )
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r.domain in seen:
            continue
        seen.add(r.domain)
        out.append(
            {
                "id": r.id,
                "domain": r.domain,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "sources_meta": r.sources_meta,
                "brand_name": (r.profile or {}).get("brand_name"),
                "queries_count": len(r.queries or []),
            }
        )
    return out


@router.get("/{domain}")
async def get_generator_run(domain: str, db: AsyncSession = Depends(get_db)):
    """Latest generator-run for `domain`."""
    target = normalize_brand_domain(domain)

    row = (
        (
            await db.execute(
                select(GeneratorRun)
                .where(GeneratorRun.domain == target)
                .order_by(GeneratorRun.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(404, f"no generator run for {target}")

    return {"domain": target, "run": _serialize_run(row)}
