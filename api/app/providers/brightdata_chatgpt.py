from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.config import settings
from app.providers import _brightdata
from app.providers.base import (
    GeoContext,
    LLMProvider,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderResponse,
    ShoppingProduct,
)

logger = logging.getLogger(__name__)


class _Citation(BaseModel):
    url: str | None = None
    model_config = ConfigDict(extra="ignore")


class _SearchSource(BaseModel):
    url: str | None = None
    model_config = ConfigDict(extra="ignore")


class _PurchasingOption(BaseModel):
    buy_link: str | None = None
    website: str | None = None
    model_config = ConfigDict(extra="ignore")


class _ShoppingItem(BaseModel):
    title: str | None = None
    price: str | None = None
    rating: float | None = None
    reviews: int | None = None
    image: str | None = None
    link: str | None = None
    description: str | None = None
    tag: str | None = None
    purchasing_options: list[_PurchasingOption] = []
    model_config = ConfigDict(extra="ignore")


class _ChatGPTRecord(BaseModel):
    answer_text: str | None = None
    citations: list[_Citation] = []
    search_sources: list[_SearchSource] = []
    web_search_query: str | list[str] | None = None
    # The sibling `recommendations` field is always null in live data
    # despite the docs; `shopping` is the real carousel.
    shopping: list[_ShoppingItem] = []
    error: str | None = None
    model_config = ConfigDict(extra="ignore")


@dataclass(frozen=True, slots=True)
class _Extracted:
    text: str
    source_urls: list[str]
    search_queries: list[str]
    shopping: list[ShoppingProduct]


class BrightDataChatGPTProvider(LLMProvider):
    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.brightdata_api_key)

    @classmethod
    def credential_hint(cls) -> str:
        return "BRIGHTDATA_API_KEY"

    def __init__(self) -> None:
        if not self.is_configured():
            raise ProviderAuthError("BRIGHTDATA_API_KEY is not configured")
        self._api_key = settings.brightdata_api_key
        self._dataset_id = settings.brightdata_chatgpt_dataset_id

    async def query(self, prompt: str, *, geo: GeoContext) -> ProviderResponse:
        body: list[dict[str, Any]] = [
            {
                "url": "https://chatgpt.com/",
                "prompt": prompt,
                "web_search": True,
                "country": geo.country_code,
            }
        ]

        start = time.perf_counter()
        record = await _brightdata.submit_and_wait_for_record(
            api_key=self._api_key,
            dataset_id=self._dataset_id,
            body=body,
            provider_label="Bright Data",
            start_ts=start,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        extracted = _extract_fields(record)
        return ProviderResponse(
            text=extracted.text,
            source_urls=_brightdata.dedupe(extracted.source_urls),
            search_queries=extracted.search_queries,
            shopping=extracted.shopping,
            tokens_used=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=latency_ms,
        )


def _first_buy_link(options: list[_PurchasingOption]) -> str | None:
    for opt in options:
        if opt.buy_link:
            return opt.buy_link
        if opt.website:
            return opt.website
    return None


def _extract_fields(record: dict[str, Any]) -> _Extracted:
    try:
        parsed = _ChatGPTRecord.model_validate(record)
    except ValidationError as e:
        raise ProviderBadResponseError(
            f"Bright Data ChatGPT record had unexpected shape: {e}"
        ) from e

    if not parsed.answer_text or not parsed.answer_text.strip():
        raise ProviderBadResponseError("Bright Data record contained no answer_text")

    source_urls = [c.url for c in parsed.citations if c.url]
    source_urls.extend(s.url for s in parsed.search_sources if s.url)

    search_queries: list[str] = []
    wsq = parsed.web_search_query
    if isinstance(wsq, str) and wsq.strip():
        search_queries.append(wsq)
    elif isinstance(wsq, list):
        search_queries.extend(q for q in wsq if isinstance(q, str) and q.strip())

    shopping: list[ShoppingProduct] = []
    for position, item in enumerate(parsed.shopping, start=1):
        if not item.title or not item.title.strip():
            continue
        shopping.append(
            ShoppingProduct(
                position=position,
                title=item.title.strip(),
                price=item.price,
                rating=item.rating,
                reviews=item.reviews,
                image=item.image,
                link=item.link or _first_buy_link(item.purchasing_options),
                description=item.description,
                tag=item.tag,
            )
        )

    return _Extracted(parsed.answer_text, source_urls, search_queries, shopping)
