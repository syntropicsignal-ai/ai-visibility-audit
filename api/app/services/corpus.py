"""Category corpus assembly: WildChat (Postgres/pgvector) + DataForSEO PAA + suggestions."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.services.dataforseo_labs import (
    KeywordSuggestion,
    PaaQuestion,
    fetch_keyword_suggestions_for_seeds,
    fetch_paa_for_seeds,
)

_PaaFetcher = Callable[..., Awaitable[list[PaaQuestion]]]
_SuggFetcher = Callable[..., Awaitable[list[KeywordSuggestion]]]

logger = logging.getLogger(__name__)

HF_DATASET_BY_LANG: dict[str, str] = {
    "pl": "syntropicsignal-ai/wildchat-asking-pl-gemini-embedding-001",
    "en": "syntropicsignal-ai/wildchat-asking-en-gemini-embedding-001",
}

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 1536


class _EmbeddingItem(Protocol):
    embedding: list[float]


class _EmbeddingResponse(Protocol):
    data: list[_EmbeddingItem]


class _EmbeddingsAPI(Protocol):
    async def create(
        self, *, model: str, input: list[str], dimensions: int
    ) -> _EmbeddingResponse: ...


class EmbeddingsClient(Protocol):
    @property
    def embeddings(self) -> _EmbeddingsAPI: ...


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CorpusSample:
    text: str
    source: str  # "wildchat" | "paa" | "suggestion"
    seed: str | None = None
    intent: str | None = None
    length_mode: str | None = None
    score: float | None = None  # cosine similarity, wildchat-only


@dataclass
class CategoryCorpus:
    samples: list[CorpusSample] = field(default_factory=list)
    seed_terms: list[str] = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    style_exemplars: dict[str, list[str]] = field(default_factory=dict)

    def by_source(self, source: str) -> list[CorpusSample]:
        return [s for s in self.samples if s.source == source]


@dataclass
class CorpusHit:
    text: str
    intent: str | None
    length_mode: str | None
    score: float  # cosine similarity


class CorpusStore(Protocol):
    async def ensure_loaded(self, language_code: str) -> int:
        """Ingest the language's dataset if absent; return its row count (0 if unsupported)."""
        ...

    async def search(
        self,
        language_code: str,
        query_vec: list[float],
        token_patterns: list[str],
        top_k: int,
    ) -> list[CorpusHit]:
        """Top-k by cosine to query_vec, gated to texts matching any pattern (empty = no gate)."""
        ...

    async def texts(self, language_code: str) -> list[str]: ...


# ---------------------------------------------------------------------------
# Style exemplars — topic-agnostic register samples, bucketed by intent
# ---------------------------------------------------------------------------

_STYLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "transactional": re.compile(
        r"\b(kupić|kupic|zamów|zamow|cena|ceny|kosztuj|tani[oei]?|"
        r"gdzie kupić|gdzie kupic|w jakim sklepie|polec(asz|cie|acie)|"
        r"najtaniej|budżet|budzet|do \d+\s*(zł|zl|pln))\b",
        re.IGNORECASE,
    ),
    "comparative": re.compile(
        r"(\b\w+\s+(czy|vs|albo)\s+\w+\b|lepsz[ey]|różnic[aey] (między|miedzy)|"
        r"w porównaniu|który (lepszy|wybrać|wybrac)|która (lepsza|opcja))",
        re.IGNORECASE,
    ),
    "brand": re.compile(
        r"\b(opinie|recenzj|czy warto|warto (kupić|kupic|wziąć|brać|brac|robić|robic)|"
        r"jak (działa|dziala|sprawdza się|sprawdza sie)|doświadczeni|doswiadczeni|"
        r"polecacie)\b",
        re.IGNORECASE,
    ),
    "informational": re.compile(
        r"^\s*(jak\s|co to|czym (jest|są|sa)|dlaczego|czemu|ile\s|jakie\s|"
        r"na czym polega|wyjaśnij|wyjasnij|opisz)",
        re.IGNORECASE,
    ),
}

# Commerce-word noise that isn't a real consumer query (homework, code, accounting).
_STYLE_JUNK = re.compile(
    r"(\bzadanie\s*\d|\bwyrob(u|ów|ow)\b|przedsiębiorstw|przedsiebiorstw|"
    r"koszt(y|ów|ow)? (zmienn|stał|stal|jednostk)|\bimport \w|\bfunc \w|"
    r"package main|\bdef \w+\(|\bclass \w+[:(]|#include|SELECT .+ FROM|"
    r"napisz (wypracowanie|rozprawk|esej|opowiadanie|list|wiersz)|"
    r"przetłumacz|przetlumacz|\bkod[ezм]\b)",
    re.IGNORECASE,
)


def select_style_exemplars(texts: list[str], per_intent: int = 5) -> dict[str, list[str]]:
    """Register exemplars bucketed by intent — topic-agnostic, for few-shot texture."""
    out: dict[str, list[str]] = {}
    for intent, rx in _STYLE_PATTERNS.items():
        candidates: list[str] = []
        seen: set[str] = set()
        for raw in texts:
            text = " ".join((raw or "").split())
            if not (12 <= len(text) <= 240):
                continue
            key = text.lower()
            if key in seen:
                continue
            if _STYLE_JUNK.search(text):
                continue
            if rx.search(text):
                seen.add(key)
                candidates.append(text)
        # digit-bearing first (likely stacked constraints), then longer
        candidates.sort(
            key=lambda t: (any(c.isdigit() for c in t), len(t.split())),
            reverse=True,
        )
        out[intent] = candidates[:per_intent]
    return out


# Deterministic per language → cache the result rather than re-scan the full corpus.
_STYLE_EXEMPLAR_CACHE: dict[str, dict[str, list[str]]] = {}
_STYLE_EXEMPLAR_LOCKS: dict[str, asyncio.Lock] = {}


def _style_lock(key: str) -> asyncio.Lock:
    lock = _STYLE_EXEMPLAR_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _STYLE_EXEMPLAR_LOCKS[key] = lock
    return lock


async def load_style_exemplars(store: CorpusStore, language_code: str) -> dict[str, list[str]]:
    key = language_code.lower()
    cached = _STYLE_EXEMPLAR_CACHE.get(key)
    if cached is not None:
        return cached
    async with _style_lock(key):
        cached = _STYLE_EXEMPLAR_CACHE.get(key)
        if cached is not None:
            return cached
        exemplars = select_style_exemplars(await store.texts(language_code))
        _STYLE_EXEMPLAR_CACHE[key] = exemplars
        return exemplars


# ---------------------------------------------------------------------------
# Embedding similarity
# ---------------------------------------------------------------------------


async def _embed_query(client: EmbeddingsClient, text: str) -> list[float]:
    resp = await client.embeddings.create(
        model=EMBEDDING_MODEL, input=[text], dimensions=EMBEDDING_DIM
    )
    return resp.data[0].embedding


def _term_token_set(profile_terms: list[str]) -> set[str]:
    # Substring tokens catch inflections without a stemmer; 4-char floor skips stopwords.
    tokens: set[str] = set()
    for term in profile_terms:
        for tok in term.lower().split():
            tok = tok.strip(",.!?;:()[]\"'")
            if len(tok) >= 4:
                tokens.add(tok)
    return tokens


async def filter_wildchat_by_relevance(
    store: CorpusStore,
    client: EmbeddingsClient,
    profile_terms: list[str],
    *,
    language_code: str,
    top_k: int = 150,
    min_score: float = 0.50,
    min_quality_count: int = 10,
) -> list[CorpusSample]:
    # min_score is a soft floor (gemini cosine sits high ~0.5); the substring gate does
    # the topical filtering. Below min_quality_count, return nothing rather than feed a
    # thin corpus downstream.
    if not profile_terms:
        return []
    query = ", ".join(t for t in profile_terms if t and t.strip())[:1000]
    if not query:
        return []
    if not await store.ensure_loaded(language_code):
        return []

    patterns = [f"%{tok}%" for tok in _term_token_set(profile_terms)]
    query_vec = await _embed_query(client, query)
    hits = await store.search(language_code, query_vec, patterns, top_k)

    scored = [h for h in hits if h.score >= min_score]
    if len(scored) < min_quality_count:
        logger.info(
            "WildChat: only %d samples passed filters (need %d) — returning empty",
            len(scored),
            min_quality_count,
        )
        return []

    return [
        CorpusSample(
            text=h.text,
            source="wildchat",
            intent=h.intent,
            length_mode=h.length_mode,
            score=h.score,
        )
        for h in scored
    ]


# ---------------------------------------------------------------------------
# Corpus orchestration
# ---------------------------------------------------------------------------


async def build_category_corpus(
    profile_terms: list[str],
    seed_terms: list[str],
    *,
    location_code: int,
    language_code: str,
    embeddings_client: EmbeddingsClient,
    store: CorpusStore,
    wildchat_top_k: int = 150,
    paa_max_seeds: int = 10,
    suggestions_max_seeds: int = 10,
    suggestions_per_seed: int = 30,
    paa_fetcher: _PaaFetcher | None = None,
    sugg_fetcher: _SuggFetcher | None = None,
) -> CategoryCorpus:
    # profile_terms drives the WildChat filter; seed_terms the PAA/suggestion fetches.
    paa_fn = paa_fetcher or fetch_paa_for_seeds
    sugg_fn = sugg_fetcher or fetch_keyword_suggestions_for_seeds
    paa_task = paa_fn(
        seed_terms,
        location_code=location_code,
        language_code=language_code,
        max_seeds=paa_max_seeds,
    )
    sugg_task = sugg_fn(
        seed_terms,
        location_code=location_code,
        language_code=language_code,
        max_seeds=suggestions_max_seeds,
        per_seed_limit=suggestions_per_seed,
    )
    wildchat_task = filter_wildchat_by_relevance(
        store,
        embeddings_client,
        profile_terms,
        language_code=language_code,
        top_k=wildchat_top_k,
    )

    paa, suggestions, wildchat = await asyncio.gather(paa_task, sugg_task, wildchat_task)

    samples: list[CorpusSample] = []
    samples.extend(wildchat)
    samples.extend(_paa_to_samples(paa))
    samples.extend(_suggestions_to_samples(suggestions))

    style_exemplars = await load_style_exemplars(store, language_code)

    counts = {
        "wildchat": len(wildchat),
        "paa": len(paa),
        "suggestion": len(suggestions),
        "style_exemplars": sum(len(v) for v in style_exemplars.values()),
    }
    warnings: list[str] = []
    total = sum(counts.values())
    if total < 30:
        warnings.append(f"sparse corpus: only {total} samples across all sources")
    if not wildchat:
        if language_code and language_code.lower() not in HF_DATASET_BY_LANG:
            warnings.append(f"no WildChat dataset published for language={language_code!r}")
        else:
            warnings.append("WildChat returned 0 samples above similarity threshold")

    logger.info(
        "Stage 2: corpus assembled — wildchat=%d paa=%d suggestion=%d",
        counts["wildchat"],
        counts["paa"],
        counts["suggestion"],
    )

    return CategoryCorpus(
        samples=samples,
        seed_terms=seed_terms,
        counts=counts,
        warnings=warnings,
        style_exemplars=style_exemplars,
    )


def _paa_to_samples(paa: list[PaaQuestion]) -> list[CorpusSample]:
    return [CorpusSample(text=p.question, source="paa", seed=p.seed) for p in paa]


def _suggestions_to_samples(
    suggestions: list[KeywordSuggestion],
) -> list[CorpusSample]:
    return [
        CorpusSample(text=s.keyword, source="suggestion", seed=s.seed, length_mode="search_like")
        for s in suggestions
    ]
