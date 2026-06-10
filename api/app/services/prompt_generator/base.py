"""Public contract for prompt generators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable, get_args

from sqlalchemy.ext.asyncio import AsyncSession

from app.geo_catalog import CountryCode, LanguageCode


# Closed vocabularies — kept as `Literal` rather than Enum because every
# downstream consumer (JSON serialization, SQLAlchemy enum columns,
# FastAPI response models) wants plain strings. Static checkers reject
# anything outside the literal set; runtime values are just str.
IntentName = Literal[
    "transactional",
    "informational",
    "comparative",
    "brand",
    "local",
]
LengthMode = Literal["search_like", "conversational"]
BuyerStage = Literal["problem_unaware", "problem_aware", "solution_aware"]
SeedSource = Literal["brand", "gap", "synthetic"]

# Exposed as runtime tuples too — useful for "validate a value against
# the closed set" in places that don't have a static type checker
# inspecting them (e.g. JSON inputs at I/O boundaries).
INTENT_NAMES: tuple[IntentName, ...] = get_args(IntentName)
LENGTH_MODES: tuple[LengthMode, ...] = get_args(LengthMode)
BUYER_STAGES: tuple[BuyerStage, ...] = get_args(BuyerStage)
SEED_SOURCES: tuple[SeedSource, ...] = get_args(SeedSource)


@dataclass(slots=True)
class GenerateRequest:
    """Inputs to a single generator run.

    Vendor-neutral by design — `country_code` is ISO 3166-1 alpha-2 and
    `language_code` is ISO 639-1, both of which name real-world things
    that are meaningful outside of any specific search-data provider.
    Implementation-specific tuning knobs (page-fetch budgets, competitor
    counts, oversample factors, vendor location codes) belong in the
    implementation's own constructor, not in the contract.

    `extras` is a free-form escape hatch for fields that a custom
    implementation may want to consume but that don't belong in the
    universal vocabulary. Use sparingly; if a field shows up in two
    implementations, promote it to a real field here.
    """

    domain: str
    num_queries: int = 50
    country_code: CountryCode = CountryCode("US")  # ISO 3166-1 alpha-2
    language_code: LanguageCode = LanguageCode("en")  # ISO 639-1 alpha-2
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedPrompt:
    """One benchmark prompt produced by a generator.

    Required: `text`, `intent`. Everything else is optional metadata
    that downstream features (analytics, recommendations) may or may
    not use.
    """

    text: str
    intent: IntentName
    length_mode: LengthMode = "conversational"
    buyer_stage: BuyerStage = "problem_aware"
    shape: int = 0
    tags: list[str] = field(default_factory=list)
    seed_source: SeedSource | None = None
    seed_keyword: str | None = None
    seed_search_volume: int | None = None
    seed_position: int | None = None


@dataclass(slots=True)
class GenerateResult:
    """Output of a generator run.

    `prompts` is the contract — every implementation produces them.
    `meta` is a free-form bag for implementation-specific artifacts;
    the default implementation populates it with profile, competitors,
    keyword signals, corpus, and persona data, but a different
    implementation can leave it empty.
    """

    domain: str
    brand_name: str | None
    prompts: list[GeneratedPrompt]
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class PromptGenerator(Protocol):
    """The single method every generator implementation must provide.

    `db` is passed in for implementations that want to persist
    intermediate artifacts (a business profile, a run snapshot, etc).
    Pure stateless implementations can ignore it.
    """

    async def generate(
        self,
        request: GenerateRequest,
        *,
        db: AsyncSession | None = None,
    ) -> GenerateResult: ...
