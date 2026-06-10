"""gemini.google.com via Bright Data's Gemini dataset (consumer
surface, not the Gemini API). Defensive multi-key extraction because
Bright Data's docs don't pin field names."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.providers import _brightdata
from app.providers.base import (
    GeoContext,
    LLMProvider,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderResponse,
)

logger = logging.getLogger(__name__)

# Bright Data's Gemini source rejects the `country` field, so it is
# omitted; the call runs against the default geo pool.


class BrightDataGeminiProvider(LLMProvider):
    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.brightdata_api_key) and bool(settings.brightdata_gemini_dataset_id)

    @classmethod
    def credential_hint(cls) -> str:
        return "BRIGHTDATA_API_KEY + BRIGHTDATA_GEMINI_DATASET_ID"

    def __init__(self) -> None:
        if not self.is_configured():
            raise ProviderAuthError(
                "BRIGHTDATA_API_KEY and BRIGHTDATA_GEMINI_DATASET_ID must both be set"
            )
        self._api_key = settings.brightdata_api_key
        self._dataset_id = settings.brightdata_gemini_dataset_id

    async def query(self, prompt: str, *, geo: GeoContext) -> ProviderResponse:
        # `country` intentionally omitted (see module comment).
        del geo
        body: list[dict[str, Any]] = [
            {
                "url": "https://gemini.google.com/",
                "prompt": prompt,
            }
        ]

        start = time.perf_counter()
        record = await _brightdata.submit_and_wait_for_record(
            api_key=self._api_key,
            dataset_id=self._dataset_id,
            body=body,
            provider_label="Bright Data Gemini",
            start_ts=start,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        text, source_urls, search_queries = _extract_fields(record)
        return ProviderResponse(
            text=text,
            source_urls=_brightdata.dedupe(source_urls),
            search_queries=search_queries,
            tokens_used=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=latency_ms,
        )


# Plausible BD field names in priority order; first non-empty wins.
_TEXT_FIELD_CANDIDATES = (
    "answer_text",
    "response_text",
    "response_content",
    "answer",
    "content",
    "text",
)
_URL_GROUP_KEYS = ("citations", "sources", "search_sources", "links")
_QUERY_KEYS = ("web_search_query", "search_query", "search_queries")


def _extract_fields(record: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    text: str | None = None
    matched_key: str | None = None
    for key in _TEXT_FIELD_CANDIDATES:
        v = record.get(key)
        if isinstance(v, str) and v.strip():
            text = v
            matched_key = key
            break
    if text is None:
        raise ProviderBadResponseError(
            "Bright Data Gemini record contained no recognizable text field "
            f"(tried {list(_TEXT_FIELD_CANDIDATES)}); keys present: "
            f"{list(record.keys())}"
        )
    if matched_key != "answer_text":
        logger.info(
            "Bright Data Gemini record used non-default text field %r",
            matched_key,
        )

    source_urls: list[str] = []
    for key in _URL_GROUP_KEYS:
        for entry in record.get(key) or []:
            if isinstance(entry, dict):
                url = entry.get("url")
                if isinstance(url, str):
                    source_urls.append(url)
            elif isinstance(entry, str):
                source_urls.append(entry)

    search_queries: list[str] = []
    for key in _QUERY_KEYS:
        v = record.get(key)
        if isinstance(v, str) and v.strip():
            search_queries.append(v)
        elif isinstance(v, list):
            for q in v:
                if isinstance(q, str) and q.strip():
                    search_queries.append(q)

    return text, source_urls, search_queries
