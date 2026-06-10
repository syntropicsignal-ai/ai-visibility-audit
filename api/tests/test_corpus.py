from __future__ import annotations

from typing import cast

import pytest

from app.services import corpus
from app.services.corpus import (
    CategoryCorpus,
    CorpusSample,
    EmbeddingsClient,
    WildChatSample,
    build_category_corpus,
    filter_wildchat_by_relevance,
    load_wildchat_for_language,
    select_style_exemplars,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    corpus._DATASET_CACHE.clear()
    corpus._DATASET_LOAD_LOCKS.clear()
    yield
    corpus._DATASET_CACHE.clear()
    corpus._DATASET_LOAD_LOCKS.clear()


class _FakeEmbeddings:
    def __init__(self, vector: list[float]):
        self._vector = vector

    async def create(self, *, model: str, input: list[str]):
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


async def test_unmapped_language_returns_empty_without_network():
    samples, embeddings = await load_wildchat_for_language("xx")
    assert samples == [] and embeddings == []
    assert "xx" in corpus._DATASET_CACHE


async def test_transient_load_failure_is_not_cached():
    calls = {"n": 0}

    def fake_sync(name: str) -> tuple[list[WildChatSample], list[list[float]]]:
        calls["n"] += 1
        raise RuntimeError("network glitch")

    await load_wildchat_for_language("pl", loader=fake_sync)
    await load_wildchat_for_language("pl", loader=fake_sync)
    assert calls["n"] == 2
    assert "pl" not in corpus._DATASET_CACHE


async def test_filter_short_circuits_before_embedding_for_unmapped_language():
    client = _fake_client([1.0, 0.0])
    out = await filter_wildchat_by_relevance(client, profile_terms=["foo"], language_code="xx")
    assert out == []


async def test_filter_quality_gate_returns_empty_when_too_few_hits():
    samples = [
        WildChatSample(text="pizza margherita opinie", source="raw"),
        WildChatSample(text="najlepsza pizza w Krakowie", source="raw"),
        WildChatSample(text="rower elektryczny do miasta", source="raw"),
    ]
    embeddings = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
    corpus._DATASET_CACHE["pl"] = (samples, embeddings)

    out = await filter_wildchat_by_relevance(
        _fake_client([1.0, 0.0]),
        profile_terms=["pizza"],
        language_code="pl",
        min_score=0.5,
        min_quality_count=10,
    )
    assert out == []


async def test_filter_returns_scored_corpus_samples():
    samples = [
        WildChatSample(text="pizza margherita opinie", source="raw"),
        WildChatSample(text="najlepsza pizza w Krakowie", source="raw"),
        WildChatSample(text="restauracja pizzeria menu", source="raw"),
        WildChatSample(text="kuchnia włoska przepisy", source="raw"),
        WildChatSample(text="domowa pizza na cienkim cieście", source="raw"),
    ]
    embeddings = [[1.0, 0.0] for _ in samples]
    corpus._DATASET_CACHE["pl"] = (samples, embeddings)

    out = await filter_wildchat_by_relevance(
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
    samples = [
        WildChatSample(text="pizza opinie", source="raw"),
        WildChatSample(text="pizza wegańska", source="raw"),
    ]
    corpus._DATASET_CACHE["pl"] = (samples, [[1.0, 0.0], [1.0, 0.0]])

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
        openai_client=_fake_client([1.0, 0.0]),
        wildchat_top_k=10,
        paa_fetcher=_fake_paa,
        sugg_fetcher=_fake_sugg,
    )
    assert isinstance(out, CategoryCorpus)
    assert out.counts == {
        "wildchat": 0,
        "paa": 2,
        "suggestion": 3,
        "style_exemplars": 1,
    }
    assert {s.source for s in out.samples} == {"paa", "suggestion"}
    assert out.style_exemplars["brand"] == ["pizza opinie"]


def test_style_exemplars_bucket_filter_and_cap():
    samples = [
        WildChatSample(text="jaki telefon kupić do 1000 zł ale nie chiński", source="raw"),
        WildChatSample(text="gdzie kupić dobry ekspres do kawy", source="raw"),
        WildChatSample(
            text="Zadanie 8: przedsiębiorstwo Y, cena sprzedaży wyrobu 20 zł, koszty zmienne",
            source="raw",
        ),
        WildChatSample(text="def cena(): SELECT price FROM zamowienia", source="raw"),
        WildChatSample(text="jak wybrać rozmiar butów do biegania", source="raw"),
        WildChatSample(text="cena?", source="raw"),
    ]

    out = select_style_exemplars(samples, per_intent=2)

    assert out["transactional"] == [
        "jaki telefon kupić do 1000 zł ale nie chiński",
        "gdzie kupić dobry ekspres do kawy",
    ]
    assert out["informational"] == ["jak wybrać rozmiar butów do biegania"]
    flat = [t for xs in out.values() for t in xs]
    assert not any("Zadanie 8" in t or "def cena" in t or t == "cena?" for t in flat)
