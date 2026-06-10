"""Shared submit / poll / download for the Bright Data providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.providers.base import (
    ProviderAPIError,
    ProviderAuthError,
    ProviderBadResponseError,
    ProviderRateLimitError,
)

logger = logging.getLogger(__name__)

BD_SCRAPE_ENDPOINT = "https://api.brightdata.com/datasets/v3/scrape"
BD_PROGRESS_ENDPOINT = "https://api.brightdata.com/datasets/v3/progress"
BD_SNAPSHOT_ENDPOINT = "https://api.brightdata.com/datasets/v3/snapshot"

MAX_WAIT_S = 240.0
DEFAULT_POLL_DELAY_S = 10.0
REQUEST_TIMEOUT_S = 120.0

_IN_PROGRESS_STATUSES = frozenset({"running", "building", "collecting", "pending", "starting"})
_TERMINAL_FAILURE_STATUSES = frozenset({"failed", "error", "canceled", "cancelled"})


class _SnapshotEnvelope(BaseModel):
    snapshot_id: str
    model_config = ConfigDict(extra="ignore")


class _ProgressBody(BaseModel):
    status: str = ""
    records: int | None = None
    errors: int | None = None
    model_config = ConfigDict(extra="ignore")


async def submit_and_wait_for_record(
    *,
    api_key: str,
    dataset_id: str,
    body: list[dict[str, Any]],
    provider_label: str,
    start_ts: float,
) -> dict[str, Any]:
    # `start_ts` (from time.perf_counter() pre-submit) is reused as the
    # wait-budget origin so submit time counts toward MAX_WAIT_S.
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
        submit_resp = await _submit(client, api_key=api_key, dataset_id=dataset_id, body=body)
        return await _wait_for_record(
            client,
            submit_resp,
            api_key=api_key,
            provider_label=provider_label,
            start_ts=start_ts,
        )


async def _submit(
    client: httpx.AsyncClient,
    *,
    api_key: str,
    dataset_id: str,
    body: list[dict[str, Any]],
) -> httpx.Response:
    try:
        resp = await client.post(
            BD_SCRAPE_ENDPOINT,
            params={"dataset_id": dataset_id, "format": "json"},
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
    except httpx.TimeoutException as e:
        raise ProviderAPIError(f"Bright Data submit timed out: {e}") from e
    except httpx.HTTPError as e:
        raise ProviderAPIError(f"Bright Data submit failed: {e}") from e

    raise_for_status(resp, context="submit")
    return resp


async def _wait_for_record(
    client: httpx.AsyncClient,
    submit_resp: httpx.Response,
    *,
    api_key: str,
    provider_label: str,
    start_ts: float,
) -> dict[str, Any]:
    # BD returns either HTTP 200 + JSON array (sync, rare here) or
    # HTTP 202 + {snapshot_id, ...} (common; needs polling).
    try:
        payload: Any = submit_resp.json()
    except ValueError as e:
        raise ProviderBadResponseError(f"Bright Data /scrape returned non-JSON: {e}") from e

    if isinstance(payload, list):
        return first_record_or_raise(payload)

    try:
        envelope = _SnapshotEnvelope.model_validate(payload)
    except ValidationError as e:
        raise ProviderBadResponseError(
            f"Bright Data /scrape returned neither array nor snapshot envelope; body={payload!r}"
        ) from e

    initial_delay = parse_retry_after(submit_resp, default=DEFAULT_POLL_DELAY_S)
    logger.info(
        "%s snapshot %s pending; polling every ~%.0fs (timeout %.0fs)",
        provider_label,
        envelope.snapshot_id,
        initial_delay,
        MAX_WAIT_S,
    )

    await _poll_until_ready(
        client,
        envelope.snapshot_id,
        api_key=api_key,
        provider_label=provider_label,
        initial_delay=initial_delay,
        start_ts=start_ts,
    )
    return await _download_snapshot(client, envelope.snapshot_id, api_key=api_key)


async def _poll_until_ready(
    client: httpx.AsyncClient,
    snapshot_id: str,
    *,
    api_key: str,
    provider_label: str,
    initial_delay: float,
    start_ts: float,
) -> None:
    delay = initial_delay
    while True:
        # Budget check BEFORE sleeping so a slow first poll doesn't double-wait.
        elapsed = time.perf_counter() - start_ts
        if elapsed >= MAX_WAIT_S:
            raise ProviderAPIError(
                f"{provider_label} snapshot {snapshot_id} not ready after "
                f"{elapsed:.0f}s (max {MAX_WAIT_S:.0f}s)"
            )

        await asyncio.sleep(min(delay, MAX_WAIT_S - elapsed))

        try:
            resp = await client.get(
                f"{BD_PROGRESS_ENDPOINT}/{snapshot_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        except httpx.HTTPError as e:
            raise ProviderAPIError(f"Bright Data /progress request failed: {e}") from e

        raise_for_status(resp, context="progress")

        try:
            raw_body: Any = resp.json()
        except ValueError as e:
            raise ProviderBadResponseError(f"Bright Data /progress returned non-JSON: {e}") from e
        try:
            body = _ProgressBody.model_validate(raw_body)
        except ValidationError as e:
            raise ProviderBadResponseError(
                f"Bright Data /progress payload had unexpected shape: {raw_body!r}"
            ) from e

        status = body.status.lower()

        if status == "ready":
            logger.info(
                "%s snapshot %s ready: records=%s errors=%s",
                provider_label,
                snapshot_id,
                body.records,
                body.errors,
            )
            return

        if status in _TERMINAL_FAILURE_STATUSES:
            raise ProviderAPIError(
                f"{provider_label} snapshot {snapshot_id} failed with status={status!r}: {raw_body!r}"
            )

        if status and status not in _IN_PROGRESS_STATUSES:
            # Unknown status — log once but keep polling rather than
            # miscategorizing a future BD state name as terminal.
            logger.warning(
                "%s snapshot %s returned unknown status %r — continuing to poll",
                provider_label,
                snapshot_id,
                status,
            )

        delay = parse_retry_after(resp, default=delay)


async def _download_snapshot(
    client: httpx.AsyncClient,
    snapshot_id: str,
    *,
    api_key: str,
) -> dict[str, Any]:
    try:
        resp = await client.get(
            f"{BD_SNAPSHOT_ENDPOINT}/{snapshot_id}",
            params={"format": "json"},
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError as e:
        raise ProviderAPIError(f"Bright Data /snapshot download failed: {e}") from e

    raise_for_status(resp, context="snapshot")

    try:
        payload: Any = resp.json()
    except ValueError as e:
        raise ProviderBadResponseError(f"Bright Data /snapshot returned non-JSON: {e}") from e

    if not isinstance(payload, list):
        raise ProviderBadResponseError(
            f"Bright Data /snapshot payload was not an array: type={type(payload).__name__}"
        )

    return first_record_or_raise(payload)


def raise_for_status(resp: httpx.Response, *, context: str) -> None:
    # 200 (sync data) and 202 (snapshot pending) are both accepted.
    if resp.status_code in (200, 202):
        return
    if resp.status_code in (401, 403):
        raise ProviderAuthError(
            f"Bright Data rejected credentials on {context}: {resp.text}",
            status_code=resp.status_code,
        )
    if resp.status_code == 429:
        raise ProviderRateLimitError(
            f"Bright Data rate limited on {context}: {resp.text}",
            status_code=resp.status_code,
        )
    raise ProviderAPIError(
        f"Bright Data HTTP {resp.status_code} on {context}: {resp.text}",
        status_code=resp.status_code,
    )


def parse_retry_after(resp: httpx.Response, *, default: float) -> float:
    raw = resp.headers.get("retry-after")
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        # HTTP-date form would also land here; default avoids crashing.
        return default


def first_record_or_raise(payload: list[Any]) -> dict[str, Any]:
    # We always submit exactly one input, so a well-formed response is
    # a one-element array. A per-record `error` surfaces BD-side failure.
    if not payload:
        raise ProviderBadResponseError("Bright Data returned an empty array")
    record = payload[0]
    if not isinstance(record, dict):
        raise ProviderBadResponseError(
            f"Bright Data record was not an object: type={type(record).__name__}"
        )
    if record.get("error"):
        raise ProviderBadResponseError(f"Bright Data per-record error: {record['error']}")
    return record


def dedupe(urls: list[str]) -> list[str]:
    # Preserves order; set() would scramble it.
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
