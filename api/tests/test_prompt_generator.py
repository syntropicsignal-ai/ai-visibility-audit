from __future__ import annotations

from app.geo_catalog import CountryCode, LanguageCode
from app.services.prompt_generator import (
    DefaultPromptGenerator,
    GenerateRequest,
    GenerateResult,
)


def test_generate_request_carries_no_vendor_specific_fields():
    fields = {f.name for f in GenerateRequest.__dataclass_fields__.values()}
    assert "location_code" not in fields
    for impl_knob in ("max_competitors", "max_pages", "oversample_size", "seed_keywords"):
        assert impl_knob not in fields


def _make_fake_pipeline(result: dict, captured: dict | None = None):
    async def fake(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return result

    return fake


async def test_default_generator_maps_pipeline_output_to_dataclasses():
    captured: dict = {}
    pipeline = _make_fake_pipeline(
        {
            "domain": "example.com",
            "pages_found": 7,
            "client_profile_id": 42,
            "profile": {"brand_name": "Example Co"},
            "competitors": [{"name": "Acme", "domain": "acme.com"}],
            "corpus": {"counts": {"wildchat": 12}},
            "personas": [{"name": "Buyer A"}],
            "keyword_signals": {"client_keywords": [{"keyword": "x"}]},
            "queries": [
                {
                    "text": "q1",
                    "intent": "brand",
                    "length_mode": "search_like",
                    "buyer_stage": "solution_aware",
                    "shape": 3,
                    "tags": ["t1"],
                    "seed_source": "brand",
                    "seed_keyword": "example",
                    "seed_search_volume": 1000,
                    "seed_position": 4,
                },
                {"text": "q2", "intent": "informational"},
            ],
        },
        captured,
    )

    out = await DefaultPromptGenerator(pipeline=pipeline).generate(
        GenerateRequest(
            domain="example.com",
            num_queries=12,
            country_code=CountryCode("PL"),
            language_code=LanguageCode("pl"),
        ),
        db=None,
    )

    assert captured["location_code"] == 2616
    assert captured["language_code"] == "pl"

    assert isinstance(out, GenerateResult)
    assert out.brand_name == "Example Co"
    assert len(out.prompts) == 2
    p1, p2 = out.prompts
    assert (p1.text, p1.intent, p1.length_mode, p1.shape) == (
        "q1",
        "brand",
        "search_like",
        3,
    )
    assert (p2.length_mode, p2.buyer_stage, p2.shape) == (
        "conversational",
        "problem_aware",
        0,
    )
    assert out.meta["client_profile_id"] == 42
    assert out.meta["corpus"]["counts"]["wildchat"] == 12


async def test_default_generator_constructor_knobs_reach_pipeline():
    captured: dict = {}
    pipeline = _make_fake_pipeline({"domain": "x.com", "queries": []}, captured)

    await DefaultPromptGenerator(
        max_competitors=3, max_pages=7, oversample_size=20, pipeline=pipeline
    ).generate(GenerateRequest(domain="x.com"), db=None)

    assert (captured["max_competitors"], captured["max_pages"], captured["oversample_size"]) == (
        3,
        7,
        20,
    )


async def test_default_generator_unknown_country_falls_back_to_us():
    captured: dict = {}
    pipeline = _make_fake_pipeline({"domain": "x.com", "queries": []}, captured)

    await DefaultPromptGenerator(pipeline=pipeline).generate(
        GenerateRequest(domain="x.com", country_code=CountryCode("ZZ")),
        db=None,
    )
    assert captured["location_code"] == 2840
