"""DataForSEO Labs client + PAA / suggestions SERP helpers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

LABS_ENDPOINT = "https://api.dataforseo.com/v3/dataforseo_labs/google/ranked_keywords/live"
SERP_ORGANIC_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
KEYWORD_SUGGESTIONS_ENDPOINT = (
    "https://api.dataforseo.com/v3/dataforseo_labs/google/keyword_suggestions/live"
)
REQUEST_TIMEOUT_S = 60.0


@dataclass
class RankedKeyword:
    keyword: str
    position: int  # 1..100
    search_volume: int | None  # monthly searches; None when DFS doesn't have it
    keyword_difficulty: int | None  # 0..100
    cpc: float | None  # USD; None when missing
    url: str | None  # the ranking URL on the target domain


@dataclass
class DomainKeywordReport:
    """Result of one ranked_keywords call for one domain."""

    domain: str
    location_code: int
    language_code: str
    keywords: list[RankedKeyword] = field(default_factory=list)


def _clean_domain(domain: str) -> str:
    d = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return d.removeprefix("www.")


async def fetch_ranked_keywords(
    domain: str,
    *,
    location_code: int = 2840,
    language_code: str = "en",
    limit: int = 100,
    min_position: int = 1,
    max_position: int = 50,
) -> DomainKeywordReport:
    """Fetch the keywords a domain ranks for, sorted by descending search volume.

    `min_position` / `max_position` filter to ranks worth seeding from.
    `limit` is post-filter, so we can still return up to `limit` rows
    even if some get filtered out by position.

    Returns an empty report on auth/HTTP error rather than raising — the
    caller treats missing keyword signals as "fall back to the synthetic
    pipeline" rather than failing the whole prompt generation run.
    """
    if not (settings.dataforseo_login and settings.dataforseo_password):
        logger.warning("DataForSEO Labs not configured — returning empty report")
        return DomainKeywordReport(
            domain=_clean_domain(domain),
            location_code=location_code,
            language_code=language_code,
        )

    clean = _clean_domain(domain)
    body = [
        {
            "target": clean,
            "location_code": location_code,
            "language_code": language_code,
            "limit": limit,
            "filters": [
                ["ranked_serp_element.serp_item.rank_absolute", ">=", min_position],
                "and",
                ["ranked_serp_element.serp_item.rank_absolute", "<=", max_position],
            ],
            "order_by": ["keyword_data.keyword_info.search_volume,desc"],
        }
    ]

    auth = (settings.dataforseo_login, settings.dataforseo_password)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.post(LABS_ENDPOINT, json=body, auth=auth)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("DataForSEO Labs call failed for %s: %s", clean, e)
        return DomainKeywordReport(
            domain=clean, location_code=location_code, language_code=language_code
        )

    return _parse_ranked_keywords_response(
        data, domain=clean, location_code=location_code, language_code=language_code
    )


def _parse_ranked_keywords_response(
    payload: Any, *, domain: str, location_code: int, language_code: str
) -> DomainKeywordReport:
    """Walk the DFS Labs `tasks[].result[].items[]` shape into a flat list.

    DFS nests its useful payload three levels deep. We tolerate missing
    keys and return an empty report rather than crashing — the upstream
    pipeline must not be brought down by an upstream schema drift.
    """
    report = DomainKeywordReport(
        domain=domain, location_code=location_code, language_code=language_code
    )

    if not isinstance(payload, dict):
        return report

    tasks = payload.get("tasks") or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        results = task.get("result") or []
        for result in results:
            if not isinstance(result, dict):
                continue
            items = result.get("items") or []
            for item in items:
                kw = _extract_ranked_keyword(item)
                if kw is not None:
                    report.keywords.append(kw)
    return report


def _extract_ranked_keyword(item: Any) -> RankedKeyword | None:
    """Pull (keyword, position, volume, difficulty, cpc, url) out of one DFS item.

    Returns None if the item is missing the bare minimum (keyword + position).
    """
    if not isinstance(item, dict):
        return None

    keyword_data = item.get("keyword_data") or {}
    keyword = keyword_data.get("keyword")

    keyword_info = keyword_data.get("keyword_info") or {}
    search_volume = keyword_info.get("search_volume")
    cpc = keyword_info.get("cpc")

    keyword_properties = keyword_data.get("keyword_properties") or {}
    difficulty = keyword_properties.get("keyword_difficulty")

    serp_element = item.get("ranked_serp_element") or {}
    serp_item = serp_element.get("serp_item") or {}
    position = serp_item.get("rank_absolute")
    url = serp_item.get("url")

    if not keyword or position is None:
        return None

    return RankedKeyword(
        keyword=str(keyword),
        position=int(position),
        search_volume=int(search_volume) if isinstance(search_volume, (int, float)) else None,
        keyword_difficulty=int(difficulty) if isinstance(difficulty, (int, float)) else None,
        cpc=float(cpc) if isinstance(cpc, (int, float)) else None,
        url=str(url) if url else None,
    )


# ---------------------------------------------------------------------------
# Corpus signals — People-Also-Ask + Google keyword suggestions
# ---------------------------------------------------------------------------


@dataclass
class PaaQuestion:
    """One People-Also-Ask question from a Google SERP, plus its
    seed (which of the client's domain_terms surfaced this PAA box)."""

    seed: str
    question: str


@dataclass
class KeywordSuggestion:
    """One Google keyword-suggestion (autocomplete-style) for a seed term."""

    seed: str
    keyword: str
    search_volume: int | None


async def _post_dfs(endpoint: str, body: list[dict]) -> dict | None:
    """Shared DFS POST helper. Returns parsed JSON or None on any error.
    Callers treat None as "no signal from this source"."""
    if not (settings.dataforseo_login and settings.dataforseo_password):
        logger.warning("DataForSEO not configured — skipping %s", endpoint)
        return None
    auth = (settings.dataforseo_login, settings.dataforseo_password)
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S) as client:
            resp = await client.post(endpoint, json=body, auth=auth)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("DataForSEO call failed for %s: %s", endpoint, e)
        return None


async def fetch_paa_for_seed(
    seed: str,
    *,
    location_code: int,
    language_code: str,
) -> list[PaaQuestion]:
    """Pull PAA items from the SERP for one seed keyword.

    PAA boxes ("People also ask") expose Google's measured natural-language
    questions for a topic — exactly the conversational shape we want in
    the category corpus. Each call is one SERP fetch; cost ~$0.0006 on
    the lowest DFS tier.
    """
    body = [
        {
            "keyword": seed,
            "location_code": location_code,
            "language_code": language_code,
            "device": "desktop",
            "depth": 10,
        }
    ]
    payload = await _post_dfs(SERP_ORGANIC_ENDPOINT, body)
    if payload is None:
        return []

    out: list[PaaQuestion] = []
    seen: set[str] = set()
    for task in payload.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "people_also_ask":
                    continue
                # The PAA element has nested `items` with each question
                # as `.title`. The questions can also expand to additional
                # related questions but we just take the visible ones.
                for paa in item.get("items") or []:
                    if not isinstance(paa, dict):
                        continue
                    q = paa.get("title")
                    if isinstance(q, str) and q.strip():
                        norm = q.strip()
                        if norm.lower() in seen:
                            continue
                        seen.add(norm.lower())
                        out.append(PaaQuestion(seed=seed, question=norm))
    return out


async def fetch_paa_for_seeds(
    seeds: list[str],
    *,
    location_code: int,
    language_code: str,
    max_seeds: int = 10,
) -> list[PaaQuestion]:
    """Pull PAA items for up to `max_seeds` seed keywords in parallel.

    `max_seeds` caps cost — for a 40-keyword profile we only run PAA
    against the top 10 by relevance. The caller is expected to pre-rank
    seeds (e.g. by search volume).
    """
    seeds = [s for s in seeds if s and s.strip()][:max_seeds]
    if not seeds:
        return []
    results = await asyncio.gather(
        *(
            fetch_paa_for_seed(s, location_code=location_code, language_code=language_code)
            for s in seeds
        ),
        return_exceptions=True,
    )
    flat: list[PaaQuestion] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, BaseException):
            continue
        for q in r:
            key = q.question.lower()
            if key in seen:
                continue
            seen.add(key)
            flat.append(q)
    return flat


async def fetch_keyword_suggestions_for_seed(
    seed: str,
    *,
    location_code: int,
    language_code: str,
    limit: int = 30,
) -> list[KeywordSuggestion]:
    """Google keyword suggestions for one seed (autocomplete-shaped).

    Uses the DFS Labs `keyword_suggestions` endpoint, which returns the
    keyword variations Google's auto-suggest surfaces — the short
    "search_like" forms in our 9-shape taxonomy. Sorted by descending
    search volume.
    """
    body = [
        {
            "keyword": seed,
            "location_code": location_code,
            "language_code": language_code,
            "limit": limit,
            "include_seed_keyword": False,
            "order_by": ["keyword_info.search_volume,desc"],
        }
    ]
    payload = await _post_dfs(KEYWORD_SUGGESTIONS_ENDPOINT, body)
    if payload is None:
        return []

    out: list[KeywordSuggestion] = []
    seen: set[str] = set()
    for task in payload.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        for result in task.get("result") or []:
            if not isinstance(result, dict):
                continue
            for item in result.get("items") or []:
                if not isinstance(item, dict):
                    continue
                kw = item.get("keyword")
                if not isinstance(kw, str) or not kw.strip():
                    continue
                norm = kw.strip()
                if norm.lower() in seen:
                    continue
                seen.add(norm.lower())
                ki = item.get("keyword_info") or {}
                vol = ki.get("search_volume")
                out.append(
                    KeywordSuggestion(
                        seed=seed,
                        keyword=norm,
                        search_volume=int(vol) if isinstance(vol, (int, float)) else None,
                    )
                )
    return out


async def fetch_keyword_suggestions_for_seeds(
    seeds: list[str],
    *,
    location_code: int,
    language_code: str,
    max_seeds: int = 10,
    per_seed_limit: int = 30,
) -> list[KeywordSuggestion]:
    """Pull keyword suggestions for up to `max_seeds` seeds in parallel."""
    seeds = [s for s in seeds if s and s.strip()][:max_seeds]
    if not seeds:
        return []
    results = await asyncio.gather(
        *(
            fetch_keyword_suggestions_for_seed(
                s,
                location_code=location_code,
                language_code=language_code,
                limit=per_seed_limit,
            )
            for s in seeds
        ),
        return_exceptions=True,
    )
    flat: list[KeywordSuggestion] = []
    seen: set[str] = set()
    for r in results:
        if isinstance(r, BaseException):
            continue
        for s in r:
            key = s.keyword.lower()
            if key in seen:
                continue
            seen.add(key)
            flat.append(s)
    return flat
