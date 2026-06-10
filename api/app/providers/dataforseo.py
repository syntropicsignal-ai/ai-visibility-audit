"""Google AI Overview via the DataForSEO SERP endpoint. "No AIO"
(common — Google renders for ~30-40% of queries) surfaces as
ProviderEmptyResultError(kind="no_ai_overview")."""

import time
from typing import Any

import httpx

from app.config import settings
from app.geo_catalog import DEFAULT_COUNTRY, get_country
from app.providers.base import (
    GeoContext,
    LLMProvider,
    ProviderAPIError,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderEmptyResultError,
    ProviderRateLimitError,
    ProviderResponse,
)

DATAFORSEO_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
REQUEST_TIMEOUT_S = 60.0


class DataForSEOProvider(LLMProvider):
    @classmethod
    def is_configured(cls) -> bool:
        return bool(settings.dataforseo_login and settings.dataforseo_password)

    @classmethod
    def credential_hint(cls) -> str:
        return "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD"

    def __init__(self) -> None:
        if not self.is_configured():
            raise ProviderAuthError("DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD are not configured")
        self._auth = (settings.dataforseo_login, settings.dataforseo_password)

    async def query(self, prompt: str, *, geo: GeoContext) -> ProviderResponse:
        # ISO -> DFS at the adapter boundary. Unknown codes fall back to
        # US rather than failing the query — same policy as the rest of
        # the codebase. The catalog is the source of truth; no local map.
        country = get_country(geo.country_code) or DEFAULT_COUNTRY
        body = [
            {
                "keyword": prompt,
                "location_code": country.dfs_location_code,
                "language_code": geo.language_code,
                "load_async_ai_overview": True,
                "expand_ai_overview": True,
            }
        ]

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
                resp = await client.post(
                    DATAFORSEO_ENDPOINT,
                    json=body,
                    auth=self._auth,
                )
        except httpx.TimeoutException as e:
            raise ProviderAPIError(f"DataForSEO request timed out: {e}") from e
        except httpx.HTTPError as e:
            raise ProviderAPIError(f"DataForSEO request failed: {e}") from e

        latency_ms = int((time.perf_counter() - start) * 1000)

        if resp.status_code in (401, 403):
            raise ProviderAuthError(
                f"DataForSEO rejected credentials: {resp.text}",
                status_code=resp.status_code,
            )
        if resp.status_code == 429:
            raise ProviderRateLimitError(
                f"DataForSEO rate limited: {resp.text}",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise ProviderAPIError(
                f"DataForSEO HTTP {resp.status_code}: {resp.text}",
                status_code=resp.status_code,
            )

        try:
            payload = resp.json()
        except ValueError as e:
            raise ProviderBadResponseError(f"DataForSEO returned non-JSON: {e}") from e

        text, source_urls = _parse_ai_overview(payload)

        return ProviderResponse(
            text=text,
            source_urls=_dedupe(source_urls),
            search_queries=[prompt],
            tokens_used=None,  # DataForSEO bills per request.
            latency_ms=latency_ms,
        )


def _parse_ai_overview(payload: dict[str, Any]) -> tuple[str, list[str]]:
    # Walks payload["tasks"][0]["result"][0]["items"] for the ai_overview entry.
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ProviderBadResponseError("DataForSEO response missing 'tasks'")

    task = tasks[0]
    task_status = task.get("status_code")
    if task_status != 20000:
        raise ProviderAPIError(
            f"DataForSEO task failed: {task_status} {task.get('status_message')}"
        )

    results = task.get("result")
    if not isinstance(results, list) or not results:
        raise ProviderEmptyResultError("DataForSEO returned no results for this query")

    items = results[0].get("items")
    if not isinstance(items, list):
        raise ProviderEmptyResultError("DataForSEO result had no items array")

    aio_item = next((it for it in items if it.get("type") == "ai_overview"), None)
    if aio_item is None:
        raise ProviderEmptyResultError("Google did not render an AI Overview for this query")

    text = _extract_aio_text(aio_item)
    if not text:
        raise ProviderBadResponseError("AI Overview item contained no text")

    source_urls = _extract_aio_urls(aio_item)
    return text, source_urls


def _extract_aio_text(aio: dict[str, Any]) -> str:
    """Prefer the top-level markdown; fall back to concatenating sub-item markdown."""
    top_md = aio.get("markdown")
    if isinstance(top_md, str) and top_md.strip():
        return top_md

    parts: list[str] = []
    for sub in aio.get("items") or []:
        if not isinstance(sub, dict):
            continue
        md = sub.get("markdown") or sub.get("text")
        if isinstance(md, str) and md.strip():
            parts.append(md)
    return "\n\n".join(parts)


def _extract_aio_urls(aio: dict[str, Any]) -> list[str]:
    """Collect URLs from the top-level references and any nested element references."""
    urls: list[str] = []

    for ref in aio.get("references") or []:
        if isinstance(ref, dict):
            url = ref.get("url")
            if isinstance(url, str):
                urls.append(url)

    for sub in aio.get("items") or []:
        if not isinstance(sub, dict):
            continue
        for ref in sub.get("references") or []:
            if isinstance(ref, dict):
                url = ref.get("url")
                if isinstance(url, str):
                    urls.append(url)

    return urls


def _dedupe(urls: list[str]) -> list[str]:
    """Dedupe while preserving order (set() would scramble it)."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
