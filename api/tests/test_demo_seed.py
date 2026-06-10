from __future__ import annotations

from collections import Counter

from app.services.demo_seed import (
    DEMO_BRAND_DOMAINS,
    DEMO_SELF_DOMAIN,
    _BRANDS,
    _PROMPTS,
    _SOURCES,
)
from app.sources import all_source_ids


def test_demo_brand_domains_match_brand_catalog():
    catalog_domains = {b.domain for b in _BRANDS}
    assert catalog_domains == set(DEMO_BRAND_DOMAINS)


def test_exactly_one_self_brand_and_it_owns_the_self_domain():
    selves = [b for b in _BRANDS if b.is_self]
    assert len(selves) == 1
    assert selves[0].domain == DEMO_SELF_DOMAIN


def test_demo_sources_are_real_source_ids():
    valid = set(all_source_ids())
    assert set(_SOURCES) <= valid


def test_demo_intent_mix_tracks_product_targets():
    counts = Counter(p.intent.value for p in _PROMPTS)
    total = sum(counts.values())
    assert counts["transactional"] / total >= 0.4
    assert counts["transactional"] == max(counts.values())
    assert counts["informational"] <= counts["transactional"]
