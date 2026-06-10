"""Category corpus assembly: WildChat similarity-filtered samples +
DataForSEO PAA + suggestions."""

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

_HFLoader = Callable[[str], tuple[list["WildChatSample"], list[list[float]]]]
_PaaFetcher = Callable[..., Awaitable[list[PaaQuestion]]]
_SuggFetcher = Callable[..., Awaitable[list[KeywordSuggestion]]]

logger = logging.getLogger(__name__)


# HF datasets carry WildChat-1M first-turn user prompts pre-filtered to
# info-seeking intent and pre-embedded with text-embedding-3-small
# (L2-normalized). Schema: text, source, intent, length_mode, domain,
# embedding. License: ODC-BY (inherited from allenai/WildChat-1M).
_HF_DATASET_BY_LANG: dict[str, str] = {
    "pl": "syntropicsignal-ai/wildchat-asking-pl-text-embedding-3-small",
    "en": "syntropicsignal-ai/wildchat-asking-en-text-embedding-3-small",
}

EMBEDDING_MODEL = "text-embedding-3-small"


# Structural protocol for the embedding client — avoids importing the
# heavy `openai` module just for a type annotation.


class _EmbeddingItem(Protocol):
    embedding: list[float]


class _EmbeddingResponse(Protocol):
    data: list[_EmbeddingItem]


class _EmbeddingsAPI(Protocol):
    async def create(self, *, model: str, input: list[str]) -> _EmbeddingResponse: ...


class EmbeddingsClient(Protocol):
    # Read-only property so both attribute-style (tests) and
    # property-style (real openai.AsyncOpenAI) impls satisfy it.

    @property
    def embeddings(self) -> _EmbeddingsAPI: ...


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WildChatSample:
    text: str
    source: str
    intent: str | None = None
    length_mode: str | None = None
    domain: str | None = None


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
    # Topic-agnostic register samples drawn from the whole language
    # corpus (not similarity-filtered).
    style_exemplars: dict[str, list[str]] = field(default_factory=dict)

    def by_source(self, source: str) -> list[CorpusSample]:
        return [s for s in self.samples if s.source == source]


# ---------------------------------------------------------------------------
# HF dataset loading (cached in-process, per language)
# ---------------------------------------------------------------------------


_DATASET_CACHE: dict[str, tuple[list[WildChatSample], list[list[float]]]] = {}

# Per-language locks dedupe concurrent first-call loads.
_DATASET_LOAD_LOCKS: dict[str, asyncio.Lock] = {}


def _get_load_lock(key: str) -> asyncio.Lock:
    lock = _DATASET_LOAD_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _DATASET_LOAD_LOCKS[key] = lock
    return lock


def _load_hf_dataset_sync(name: str) -> tuple[list[WildChatSample], list[list[float]]]:
    from datasets import load_dataset

    ds = load_dataset(name, split="train")
    samples: list[WildChatSample] = []
    embeddings: list[list[float]] = []
    for raw in ds:
        # pyright can't narrow row type from Dataset|IterableDataset union.
        row: dict = raw  # type: ignore[assignment]
        samples.append(
            WildChatSample(
                text=row["text"],
                source=row["source"],
                intent=row.get("intent"),
                length_mode=row.get("length_mode"),
                domain=row.get("domain"),
            )
        )
        embeddings.append(row["embedding"])
    return samples, embeddings


async def load_wildchat_for_language(
    language_code: str,
    *,
    loader: _HFLoader | None = None,
) -> tuple[list[WildChatSample], list[list[float]]]:
    # `loader` is the test seam for swapping _load_hf_dataset_sync.
    if not language_code:
        return [], []
    key = language_code.lower()
    if key in _DATASET_CACHE:
        return _DATASET_CACHE[key]

    async with _get_load_lock(key):
        # Re-check inside the lock: a peer task may have populated it.
        if key in _DATASET_CACHE:
            return _DATASET_CACHE[key]

        name = _HF_DATASET_BY_LANG.get(key)
        if not name:
            logger.info(
                "No WildChat dataset published for language=%s; wildchat stream will be empty.",
                language_code,
            )
            _DATASET_CACHE[key] = ([], [])
            return [], []

        logger.info("Loading WildChat dataset %s (first call may download)", name)
        fn = loader or _load_hf_dataset_sync
        try:
            samples, embeddings = await asyncio.to_thread(fn, name)
        except Exception:
            # Don't cache transient failures — let the next call retry.
            logger.exception("Failed to load WildChat dataset %s", name)
            return [], []
        logger.info("Loaded %d WildChat samples for %s", len(samples), language_code)
        _DATASET_CACHE[key] = (samples, embeddings)
        return samples, embeddings


# ---------------------------------------------------------------------------
# Style exemplars — topic-agnostic register samples, bucketed by intent
# ---------------------------------------------------------------------------
#
# These select for *register / shape* (how a real Polish user phrases
# a buying / comparing / asking query), NOT for topic. Bucket overlap
# is allowed — a query can illustrate more than one register.

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

# School / code / accounting noise that contains commerce words but is
# not a real consumer query.
_STYLE_JUNK = re.compile(
    r"(\bzadanie\s*\d|\bwyrob(u|ów|ow)\b|przedsiębiorstw|przedsiebiorstw|"
    r"koszt(y|ów|ow)? (zmienn|stał|stal|jednostk)|\bimport \w|\bfunc \w|"
    r"package main|\bdef \w+\(|\bclass \w+[:(]|#include|SELECT .+ FROM|"
    r"napisz (wypracowanie|rozprawk|esej|opowiadanie|list|wiersz)|"
    r"przetłumacz|przetlumacz|\bkod[ezм]\b)",
    re.IGNORECASE,
)


def select_style_exemplars(
    samples: list[WildChatSample],
    per_intent: int = 5,
) -> dict[str, list[str]]:
    """Topic-agnostic register samples bucketed by intent, drawn from
    the full corpus so a niche vertical still gets few-shot texture."""
    out: dict[str, list[str]] = {}
    for intent, rx in _STYLE_PATTERNS.items():
        candidates: list[str] = []
        seen: set[str] = set()
        for s in samples:
            text = " ".join((s.text or "").split())
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
        # Instructive-first: digit-bearing (likely stacked constraint),
        # then longer.
        candidates.sort(
            key=lambda t: (any(c.isdigit() for c in t), len(t.split())),
            reverse=True,
        )
        out[intent] = candidates[:per_intent]
    return out


# ---------------------------------------------------------------------------
# Embedding similarity
# ---------------------------------------------------------------------------


async def _embed_query(client: EmbeddingsClient, text: str) -> list[float]:
    resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=[text])
    return resp.data[0].embedding


def _cosine(a: list[float], b: list[float]) -> float:
    # text-embedding-3 outputs are L2-normalized so this reduces to a
    # dot product, but the full formula stays safe for swapped models.
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


def _term_token_set(profile_terms: list[str]) -> set[str]:
    # Substring match catches most morphological inflections without a
    # per-language stemmer; 4-char minimum avoids stopwords.
    tokens: set[str] = set()
    for term in profile_terms:
        for tok in term.lower().split():
            tok = tok.strip(",.!?;:()[]\"'")
            if len(tok) >= 4:
                tokens.add(tok)
    return tokens


def _contains_any_token(text: str, tokens: set[str]) -> bool:
    if not tokens:
        return True
    lower = text.lower()
    return any(tok in lower for tok in tokens)


async def filter_wildchat_by_relevance(
    client: EmbeddingsClient,
    profile_terms: list[str],
    *,
    language_code: str,
    top_k: int = 150,
    min_score: float = 0.40,
    min_quality_count: int = 10,
) -> list[CorpusSample]:
    # Substring sanity gate first (embedding similarity alone produces
    # spurious near-neighbors), then cosine >= min_score. Below
    # min_quality_count returns empty.
    if not profile_terms:
        return []

    samples, embeddings = await load_wildchat_for_language(language_code)
    if not samples:
        return []

    query = ", ".join(t for t in profile_terms if t and t.strip())[:1000]
    if not query:
        return []

    tokens = _term_token_set(profile_terms)
    query_vec = await _embed_query(client, query)

    scored: list[tuple[float, WildChatSample]] = []
    for sample, vec in zip(samples, embeddings):
        if not _contains_any_token(sample.text, tokens):
            continue
        score = _cosine(query_vec, vec)
        if score >= min_score:
            scored.append((score, sample))
    scored.sort(key=lambda x: x[0], reverse=True)

    if len(scored) < min_quality_count:
        logger.info(
            "WildChat: only %d samples passed filters (need %d) — returning empty",
            len(scored),
            min_quality_count,
        )
        return []

    return [
        CorpusSample(
            text=s.text,
            source="wildchat",
            intent=s.intent,
            length_mode=s.length_mode,
            score=score,
        )
        for score, s in scored[:top_k]
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
    openai_client: EmbeddingsClient,
    wildchat_top_k: int = 150,
    paa_max_seeds: int = 10,
    suggestions_max_seeds: int = 10,
    suggestions_per_seed: int = 30,
    paa_fetcher: _PaaFetcher | None = None,
    sugg_fetcher: _SuggFetcher | None = None,
) -> CategoryCorpus:
    # `profile_terms` drives the WildChat similarity filter; `seed_terms`
    # drives the PAA + suggestion fetches. Passed separately so callers
    # can rank seeds before spending DFS budget.
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
        openai_client,
        profile_terms,
        language_code=language_code,
        top_k=wildchat_top_k,
    )

    paa, suggestions, wildchat = await asyncio.gather(paa_task, sugg_task, wildchat_task)

    samples: list[CorpusSample] = []
    samples.extend(wildchat)
    samples.extend(_paa_to_samples(paa))
    samples.extend(_suggestions_to_samples(suggestions))

    # Style exemplars are topic-agnostic — pulled from the full (cached)
    # language corpus, not the similarity-filtered `wildchat` stream, so
    # they're populated even when the vertical is off-distribution.
    all_wildchat, _ = await load_wildchat_for_language(language_code)
    style_exemplars = select_style_exemplars(all_wildchat)

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
        if language_code and language_code.lower() not in _HF_DATASET_BY_LANG:
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
