"""Provider interface and typed error hierarchy.

Providers raise `ProviderError` subclasses for *expected* failures (auth,
rate limit, model not found, transient API errors). Anything else is a bug
and MUST propagate — we don't swallow unknown exceptions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.geo_catalog import CountryCode, LanguageCode


@dataclass(frozen=True, slots=True)
class GeoContext:
    # ISO codes; each provider translates to its own encoding at the boundary.
    country_code: CountryCode
    country_name: str
    language_code: LanguageCode
    language_name: str


@dataclass(frozen=True, slots=True)
class ShoppingProduct:
    position: int
    title: str
    price: str | None = None
    rating: float | None = None
    reviews: int | None = None
    image: str | None = None
    link: str | None = None
    description: str | None = None
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    text: str
    source_urls: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    shopping: list[ShoppingProduct] = field(default_factory=list)
    # input/output token splits when the SDK exposes them — cost
    # estimation needs them separately, see services/pricing.py.
    tokens_used: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None


class ProviderError(Exception):
    # `kind` is a stable identifier persisted in the DB.
    kind: str = "provider_error"

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class ProviderAuthError(ProviderError):
    kind = "auth_error"


class ProviderModelNotFoundError(ProviderError):
    kind = "model_not_found"


class ProviderRateLimitError(ProviderError):
    kind = "rate_limited"


class ProviderAPIError(ProviderError):
    kind = "api_error"


class ProviderBadResponseError(ProviderError):
    kind = "bad_response"


class ProviderEmptyResultError(ProviderError):
    # SERP-style "API healthy but no AI answer rendered" — signal, not
    # failure. Persisted as error_kind="no_ai_overview".
    kind = "no_ai_overview"


class LLMProvider(ABC):
    # Implementations raise ProviderError for known failures, propagate
    # everything else. is_configured() gates runtime participation.

    @classmethod
    @abstractmethod
    def is_configured(cls) -> bool: ...

    @classmethod
    @abstractmethod
    def credential_hint(cls) -> str:
        # Short hint surfaced in the UI next to a "missing credentials" badge.
        ...

    @abstractmethod
    async def query(self, prompt: str, *, geo: GeoContext) -> ProviderResponse:
        # SERP providers honour `geo` as real API parameters; LLM
        # providers inject it as a system instruction.
        ...


def build_geo_system_instruction(geo: GeoContext) -> str:
    # System instruction for LLM providers without a real geo knob.
    return (
        f"You are answering a search query from a user located in {geo.country_name}. "
        f"Respond in {geo.language_name}. Prioritize sources, brands, and information "
        f"that are relevant to users in {geo.country_name}."
    )
