"""Default PromptGenerator: adapts query_generator.generate_prompt_set
to the Protocol; translates ISO country → DFS at the boundary."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_catalog import DEFAULT_COUNTRY, CountryCode, get_country
from app.services.prompt_generator.base import (
    BUYER_STAGES,
    INTENT_NAMES,
    LENGTH_MODES,
    SEED_SOURCES,
    BuyerStage,
    GeneratedPrompt,
    GenerateRequest,
    GenerateResult,
    IntentName,
    LengthMode,
    PromptGenerator,
    SeedSource,
)

_PipelineFn = Callable[..., Awaitable[dict[str, Any]]]


def _coerce_intent(value: object) -> IntentName:
    if isinstance(value, str) and value in INTENT_NAMES:
        return cast(IntentName, value)
    return "informational"


def _coerce_length_mode(value: object) -> LengthMode:
    if isinstance(value, str) and value in LENGTH_MODES:
        return cast(LengthMode, value)
    return "conversational"


def _coerce_buyer_stage(value: object) -> BuyerStage:
    if isinstance(value, str) and value in BUYER_STAGES:
        return cast(BuyerStage, value)
    return "problem_aware"


def _coerce_seed_source(value: object) -> SeedSource | None:
    if isinstance(value, str) and value in SEED_SOURCES:
        return cast(SeedSource, value)
    return None


def _to_dfs_location_code(country_code: CountryCode) -> int:
    """Translate an ISO 3166-1 alpha-2 country code to DataForSEO's
    location id. Falls back to US (2840) for unknown countries."""
    country = get_country(country_code)
    return country.dfs_location_code if country else DEFAULT_COUNTRY.dfs_location_code


class DefaultPromptGenerator(PromptGenerator):
    """Multi-stage pipeline: site discovery → profile → keyword signals →
    corpus assembly → LLM oversample → critique-and-prune.

    Tuning knobs (page budget, competitor count, oversample factor) are
    constructor args rather than `GenerateRequest` fields so the public
    contract stays vendor- and implementation-neutral. Override them at
    construction time for tests / CLI smokes / operator-configured
    deployments.

    Optionally accepts a `tracker` for staged-progress reporting, used
    by the long-running run endpoint that polls for live status.
    """

    def __init__(
        self,
        *,
        max_competitors: int = 8,
        max_pages: int = 20,
        oversample_size: int | None = None,
        tracker: Any | None = None,
        pipeline: _PipelineFn | None = None,
    ) -> None:
        self._max_competitors = max_competitors
        self._max_pages = max_pages
        self._oversample_size = oversample_size
        self._tracker = tracker
        # `pipeline` lets tests inject a fake without monkeypatching the
        # query_generator module; production callers pass None and we
        # lazy-import the real one inside `generate` to keep the heavy
        # transitive imports (Exa, OpenAI clients, …) deferred.
        self._pipeline = pipeline

    async def generate(
        self,
        request: GenerateRequest,
        *,
        db: AsyncSession | None = None,
    ) -> GenerateResult:
        pipeline = self._pipeline
        if pipeline is None:
            from app.services.query_generator import generate_prompt_set

            pipeline = generate_prompt_set

        result = await pipeline(
            domain=request.domain,
            num_queries=request.num_queries,
            max_competitors=self._max_competitors,
            max_pages=self._max_pages,
            oversample_size=self._oversample_size,
            db=db,
            location_code=_to_dfs_location_code(request.country_code),
            language_code=request.language_code,
            tracker=self._tracker,
        )

        prompts = [
            GeneratedPrompt(
                text=str(q.get("text", "")),
                intent=_coerce_intent(q.get("intent")),
                length_mode=_coerce_length_mode(q.get("length_mode")),
                buyer_stage=_coerce_buyer_stage(q.get("buyer_stage")),
                shape=int(q.get("shape") or 0),
                tags=list(q.get("tags") or []),
                seed_source=_coerce_seed_source(q.get("seed_source")),
                seed_keyword=q.get("seed_keyword"),
                seed_search_volume=q.get("seed_search_volume"),
                seed_position=q.get("seed_position"),
            )
            for q in (result.get("queries") or [])
        ]

        profile = result.get("profile") or {}
        meta: dict[str, Any] = {
            "pages_found": result.get("pages_found"),
            "profile": profile,
            "competitors": result.get("competitors") or [],
            "corpus": result.get("corpus") or {},
            "personas": result.get("personas") or [],
            "keyword_signals": result.get("keyword_signals") or {},
            "client_profile_id": result.get("client_profile_id"),
        }

        return GenerateResult(
            domain=result.get("domain") or request.domain,
            brand_name=profile.get("brand_name") if isinstance(profile, dict) else None,
            prompts=prompts,
            meta=meta,
        )
