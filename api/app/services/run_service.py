"""Run execution engine."""

import asyncio
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.geo_catalog import CountryCode, LanguageCode
from app.models import Brand, Prompt, Response, Run, RunStatus
from app.providers.base import GeoContext, LLMProvider, ProviderError, ProviderResponse
from app.services.analysis import analyze_response
from app.services.pricing import estimate_cost
from app.sources import SOURCES, display_name

logger = logging.getLogger(__name__)

PER_SOURCE_CONCURRENCY = 8

RETRY_KINDS: frozenset[str] = frozenset({"rate_limited", "api_error"})
RETRY_BASE_DELAY_S = 1.5
RETRY_MAX_JITTER_S = 0.5

SILENT_PROVIDER_KINDS: frozenset[str] = frozenset(
    {"no_ai_overview", "bad_response", "api_error", "rate_limited"}
)


@dataclass(frozen=True, slots=True)
class TaskPlan:
    run_id: int
    prompt_id: int
    prompt_text: str
    source_id: str
    geo: GeoContext


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    source_id: str
    prompt_id: int
    ok: bool
    error_kind: str | None = None
    error_message: str | None = None


def _configured_sources() -> dict[str, LLMProvider]:
    instances: dict[str, LLMProvider] = {}
    for source_id, provider_cls in SOURCES.items():
        if not provider_cls.is_configured():
            logger.info(
                "Source %s skipped — missing credentials (%s)",
                source_id,
                provider_cls.credential_hint(),
            )
            continue
        instances[source_id] = provider_cls()
    return instances


async def _call_provider_with_retry(
    plan: TaskPlan, provider: LLMProvider
) -> tuple[ProviderResponse | None, str | None, str | None]:
    last_error: ProviderError | None = None
    for attempt in (1, 2):
        try:
            result = await provider.query(plan.prompt_text, geo=plan.geo)
            if attempt > 1:
                logger.info(
                    "Source %s recovered on retry for prompt %d",
                    plan.source_id,
                    plan.prompt_id,
                )
            return result, None, None
        except ProviderError as e:
            last_error = e
            if attempt == 1 and e.kind in RETRY_KINDS:
                delay = RETRY_BASE_DELAY_S + random.uniform(0, RETRY_MAX_JITTER_S)
                logger.info(
                    "Source %s hit [%s] for prompt %d — retrying in %.1fs",
                    plan.source_id,
                    e.kind,
                    plan.prompt_id,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            break

    assert last_error is not None
    return None, last_error.kind, str(last_error)


async def query_source(plan: TaskPlan, provider: LLMProvider) -> TaskOutcome:
    result, error_kind, error_message = await _call_provider_with_retry(plan, provider)

    if result is None and error_kind is not None:
        if error_kind in SILENT_PROVIDER_KINDS:
            log_method = logger.info if error_kind == "no_ai_overview" else logger.warning
            log_method(
                "Dropping %s response for prompt %d: [%s] %s",
                plan.source_id,
                plan.prompt_id,
                error_kind,
                error_message,
            )
            return TaskOutcome(
                source_id=plan.source_id,
                prompt_id=plan.prompt_id,
                ok=False,
                error_kind=error_kind,
                error_message=error_message,
            )
        logger.warning(
            "Source %s failed for prompt %d: [%s] %s",
            plan.source_id,
            plan.prompt_id,
            error_kind,
            error_message,
        )

    async with async_session() as session:
        response = Response(
            prompt_id=plan.prompt_id,
            run_id=plan.run_id,
            source=plan.source_id,
            text=result.text if result is not None else "",
            tokens_used=result.tokens_used if result is not None else None,
            input_tokens=result.input_tokens if result is not None else None,
            output_tokens=result.output_tokens if result is not None else None,
            latency_ms=result.latency_ms if result is not None else None,
            source_urls=result.source_urls if result is not None else None,
            search_queries=result.search_queries if result is not None else None,
            error_kind=error_kind,
            error_message=error_message,
        )
        session.add(response)
        await session.commit()
        await session.refresh(response)

        if result is not None:
            brands = list((await session.execute(select(Brand))).scalars().all())
            await analyze_response(session, response, brands)

    return TaskOutcome(
        source_id=plan.source_id,
        prompt_id=plan.prompt_id,
        ok=result is not None,
        error_kind=error_kind,
        error_message=error_message,
    )


async def _run_task_safely(plan: TaskPlan, provider: LLMProvider) -> TaskOutcome:
    try:
        return await query_source(plan, provider)
    except Exception as e:
        logger.exception(
            "Unexpected failure in query_source for %s / prompt %d — dropping row",
            plan.source_id,
            plan.prompt_id,
        )
        return TaskOutcome(
            source_id=plan.source_id,
            prompt_id=plan.prompt_id,
            ok=False,
            error_kind="internal_error",
            error_message=f"{type(e).__name__}: {e}",
        )


async def _compute_run_cost(session: AsyncSession, run_id: int) -> float | None:
    rows = (
        await session.execute(
            select(Response.source, Response.input_tokens, Response.output_tokens).where(
                Response.run_id == run_id
            )
        )
    ).all()

    total: float = 0.0
    counted = 0
    for source, in_tok, out_tok in rows:
        cost = estimate_cost(source, input_tokens=in_tok, output_tokens=out_tok)
        if cost is None:
            continue
        total += cost
        counted += 1

    if counted == 0:
        return None
    return round(total, 6)


async def _finalize_run(run_id: int, status: RunStatus) -> None:
    async with async_session() as session:
        run = await session.get(Run, run_id)
        if run is None:
            logger.error("Tried to finalize missing run %d", run_id)
            return
        run.status = status
        run.completed_at = datetime.now(timezone.utc)
        try:
            run.total_cost = await _compute_run_cost(session, run_id)
            logger.info("Run %d estimated cost: $%.4f", run_id, run.total_cost or 0.0)
        except Exception:
            logger.exception("Failed to compute cost for run %d", run_id)
        await session.commit()


async def execute_run(db: AsyncSession, brand_id: int) -> Run:
    brand = await db.get(Brand, brand_id)
    if brand is None:
        raise ValueError(f"Brand {brand_id} not found")
    if not brand.is_self:
        raise ValueError(
            f"Brand {brand_id} ({brand.name}) is not marked as self — "
            "runs can only target your own brand"
        )

    geo = GeoContext(
        country_code=CountryCode(brand.country_code),
        country_name=brand.country_name,
        language_code=LanguageCode(brand.language_code),
        language_name=brand.language_name,
    )

    prompts = list(
        (await db.execute(select(Prompt).where(Prompt.enabled.is_(True)))).scalars().all()
    )
    if not prompts:
        raise ValueError("No enabled prompts found")

    providers = _configured_sources()
    if not providers:
        hints = "; ".join(
            f"{display_name(sid)} ({cls.credential_hint()})" for sid, cls in SOURCES.items()
        )
        raise ValueError(f"No sources have credentials configured. Set one or more of: {hints}")

    run = Run(status=RunStatus.running)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    run_id = run.id

    logger.info(
        "Run %d started: brand=%s prompts=%d sources=%s market=%s/%s",
        run_id,
        brand.name,
        len(prompts),
        list(providers.keys()),
        geo.country_name,
        geo.language_code,
    )

    plans = [
        TaskPlan(
            run_id=run_id,
            prompt_id=prompt.id,
            prompt_text=prompt.text,
            source_id=source_id,
            geo=geo,
        )
        for prompt in prompts
        for source_id in providers
    ]

    per_source_sem: dict[str, asyncio.Semaphore] = {
        sid: asyncio.Semaphore(PER_SOURCE_CONCURRENCY) for sid in providers
    }

    async def _gated(plan: TaskPlan) -> TaskOutcome:
        async with per_source_sem[plan.source_id]:
            return await _run_task_safely(plan, providers[plan.source_id])

    try:
        outcomes = await asyncio.gather(*(_gated(plan) for plan in plans))
        successes = sum(1 for o in outcomes if o.ok)
        failures = len(outcomes) - successes
        logger.info(
            "Run %d finished: %d ok, %d failed (out of %d)",
            run_id,
            successes,
            failures,
            len(outcomes),
        )
        final_status = RunStatus.completed if successes > 0 else RunStatus.failed
    except Exception:
        logger.exception("Run %d crashed unexpectedly", run_id)
        final_status = RunStatus.failed

    await _finalize_run(run_id, final_status)

    # Return a fresh view of the run (the caller's session is fine, we just
    # need the updated status/completed_at).
    await db.rollback()
    refreshed = await db.get(Run, run_id)
    return refreshed if refreshed is not None else run
