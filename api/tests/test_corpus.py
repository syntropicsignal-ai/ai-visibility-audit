from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from app.services import corpus
from app.services.corpus import (
    CategoryCorpus,
    CorpusHit,
    CorpusSample,
    CorpusStore,
    EmbeddingsClient,
    build_category_corpus,
    filter_wildchat_by_relevance,
    select_style_exemplars,
)


@pytest.fixture(autouse=True)
def _reset_style_cache():
    corpus._STYLE_EXEMPLAR_CACHE.clear()
    corpus._STYLE_EXEMPLAR_LOCKS.clear()
    yield
    corpus._STYLE_EXEMPLAR_CACHE.clear()
    corpus._STYLE_EXEMPLAR_LOCKS.clear()


# --- Fakes (no mocks): a real in-memory CorpusStore + embedding client ---


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


@dataclass
class _Row:
    text: str
    embedding: list[float]
    intent: str | None = None
    length_mode: str | None = None


class _FakeStore:
    """Hand-written CorpusStore: substring gate + cosine rank, in memory."""

    def __init__(self, rows_by_lang: dict[str, list[_Row]]):
        self._rows = rows_by_lang

    async def ensure_loaded(self, language_code: str) -> int:
        return len(self._rows.get(language_code.lower(), []))

    async def search(self, language_code, query_vec, token_patterns, top_k) -> list[CorpusHit]:
        hits: list[CorpusHit] = []
        for r in self._rows.get(language_code.lower(), []):
            low = r.text.lower()
            if token_patterns and not any(p.strip("%") in low for p in token_patterns):
                continue
            hits.append(
                CorpusHit(
                    text=r.text,
                    intent=r.intent,
                    length_mode=r.length_mode,
                    score=_cosine(query_vec, r.embedding),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    async def texts(self, language_code: str) -> list[str]:
        return [r.text for r in self._rows.get(language_code.lower(), [])]


def _store(rows_by_lang: dict[str, list[_Row]]) -> CorpusStore:
    return cast(CorpusStore, _FakeStore(rows_by_lang))


class _FakeEmbeddings:
    def __init__(self, vector: list[float]):
        self._vector = vector

    async def create(self, *, model: str, input: list[str], dimensions: int | None = None):
        class _Item:
            def __init__(self, vec):
                self.embedding = vec

        class _Resp:
            def __init__(self, vecs):
                self.data = [_Item(v) for v in vecs]

        return _Resp([self._vector for _ in input])


class _FakeClient:
    def __init__(self, vector: list[float]):
        self.embeddings = _FakeEmbeddings(vector)


def _fake_client(vector: list[float]) -> EmbeddingsClient:
    return cast(EmbeddingsClient, _FakeClient(vector))


class _ExplodingClient:
    """Embeddings client that fails if used — guards the short-circuit."""

    @property
    def embeddings(self):
        raise AssertionError("embedding client must not be called")


async def test_empty_store_short_circuits_before_embedding():
    out = await filter_wildchat_by_relevance(
        _store({}),
        cast(EmbeddingsClient, _ExplodingClient()),
        profile_terms=["foo"],
        language_code="xx",
    )
    assert out == []


async def test_filter_quality_gate_returns_empty_when_too_few_hits():
    rows = [
        _Row("pizza margherita opinie", [1.0, 0.0]),
        _Row("najlepsza pizza w Krakowie", [1.0, 0.0]),
        _Row("rower elektryczny do miasta", [0.0, 1.0]),
    ]
    out = await filter_wildchat_by_relevance(
        _store({"pl": rows}),
        _fake_client([1.0, 0.0]),
        profile_terms=["pizza"],
        language_code="pl",
        min_score=0.5,
        min_quality_count=10,
    )
    assert out == []


async def test_filter_returns_scored_corpus_samples():
    rows = [_Row(f"pizza wariant {i}", [1.0, 0.0]) for i in range(5)]
    out = await filter_wildchat_by_relevance(
        _store({"pl": rows}),
        _fake_client([1.0, 0.0]),
        profile_terms=["pizza"],
        language_code="pl",
        top_k=3,
        min_score=0.5,
        min_quality_count=1,
    )
    assert len(out) == 3
    assert all(isinstance(s, CorpusSample) for s in out)
    assert all(s.source == "wildchat" for s in out)
    assert all(s.score is not None and s.score >= 0.5 for s in out)


async def test_corpus_merges_wildchat_paa_and_suggestions():
    rows = [
        _Row("pizza opinie", [1.0, 0.0]),
        _Row("pizza wegańska", [1.0, 0.0]),
    ]

    from app.services.dataforseo_labs import KeywordSuggestion, PaaQuestion

    async def _fake_paa(*_a, **_kw):
        return [
            PaaQuestion(seed="pizza", question="czy pizza jest zdrowa?"),
            PaaQuestion(seed="pizza", question="ile kalorii ma pizza?"),
        ]

    async def _fake_sugg(*_a, **_kw):
        return [
            KeywordSuggestion(seed="pizza", keyword="pizza Kraków", search_volume=None),
            KeywordSuggestion(seed="pizza", keyword="pizza dostawa", search_volume=None),
            KeywordSuggestion(seed="pizza", keyword="pizza margherita", search_volume=None),
        ]

    out = await build_category_corpus(
        profile_terms=["pizza"],
        seed_terms=["pizza"],
        location_code=2616,
        language_code="pl",
        embeddings_client=_fake_client([1.0, 0.0]),
        store=_store({"pl": rows}),
        wildchat_top_k=10,
        paa_fetcher=_fake_paa,
        sugg_fetcher=_fake_sugg,
    )
    assert isinstance(out, CategoryCorpus)
    # wildchat=0: both rows clear the gate but 2 < min_quality_count(10).
    assert out.counts == {
        "wildchat": 0,
        "paa": 2,
        "suggestion": 3,
        "style_exemplars": 1,
    }
    assert {s.source for s in out.samples} == {"paa", "suggestion"}
    assert out.style_exemplars["brand"] == ["pizza opinie"]


def test_style_exemplars_bucket_filter_and_cap():
    texts = [
        "jaki telefon kupić do 1000 zł ale nie chiński",
        "gdzie kupić dobry ekspres do kawy",
        "Zadanie 8: przedsiębiorstwo Y, cena sprzedaży wyrobu 20 zł, koszty zmienne",
        "def cena(): SELECT price FROM zamowienia",
        "jak wybrać rozmiar butów do biegania",
        "cena?",
    ]

    out = select_style_exemplars(texts, per_intent=2)

    assert out["transactional"] == [
        "jaki telefon kupić do 1000 zł ale nie chiński",
        "gdzie kupić dobry ekspres do kawy",
    ]
    assert out["informational"] == ["jak wybrać rozmiar butów do biegania"]
    flat = [t for xs in out.values() for t in xs]
    assert not any("Zadanie 8" in t or "def cena" in t or t == "cena?" for t in flat)
