from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import Brand
from app.providers.base import ShoppingProduct
from app.providers.brightdata_chatgpt import _extract_fields
from app.services.shopping import compute_shopping_stats, match_product_brand

FIXTURE = Path(__file__).parent / "fixtures" / "brightdata_chatgpt_shopping.json"


def _record() -> dict:
    return json.loads(FIXTURE.read_text())


def test_extract_parses_shopping_carousel():
    ex = _extract_fields(_record())
    assert [p.title for p in ex.shopping] == [
        "TREBLAB X4 Wireless Earbuds with Earhooks",
        "Blupebble TuneFlow Lite Wireless Bluetooth Earbuds",
        "PRO80 Dual-Ear Wireless TWS Bluetooth Earphone",
    ]
    first = ex.shopping[0]
    assert first.position == 1
    assert first.rating == 4.5
    assert first.price == "MX$866.22"


def test_link_backfilled_from_purchasing_options():
    # Product 0 has no link and no buy_link/website -> stays None.
    # Product 1's purchasing option carries a website -> used as the link.
    ex = _extract_fields(_record())
    assert ex.shopping[0].link is None
    assert ex.shopping[1].link == "https://shop.example.com/blupebble"


def test_recommendations_field_is_ignored():
    # Live ChatGPT data always returns recommendations=null and puts the
    # real carousel in `shopping`. Guard against a future "fix" that reads
    # the wrong field.
    record = _record()
    record["shopping"] = []
    record["recommendations"] = [{"title": "Ghost Product"}]
    ex = _extract_fields(record)
    assert ex.shopping == []


def test_match_product_brand_prefers_self_on_overlap():
    self_brand = Brand(id=1, name="TREBLAB", is_self=True)
    competitor = Brand(id=2, name="TREBLAB", is_self=False)
    product = ShoppingProduct(position=1, title="TREBLAB X4 Wireless Earbuds")
    # Competitor listed first, but the self brand must win the tie.
    assert match_product_brand(product, [competitor, self_brand]) is self_brand


def test_compute_shopping_stats():
    self_brand = Brand(id=1, name="TREBLAB", is_self=True)
    competitor = Brand(id=2, name="Blupebble", is_self=False)
    brands = [self_brand, competitor]

    carousels = [
        [
            ShoppingProduct(position=1, title="TREBLAB X4 Wireless Earbuds"),
            ShoppingProduct(position=2, title="Blupebble TuneFlow Lite"),
            ShoppingProduct(position=3, title="Sony WF-1000XM5"),
        ],
        [
            ShoppingProduct(position=1, title="Blupebble TuneFlow Lite"),
            ShoppingProduct(position=2, title="Anker Soundcore"),
        ],
        [ShoppingProduct(position=1, title="TREBLAB X4 Wireless Earbuds")],
    ]

    stats = compute_shopping_stats(carousels, total_responses=5, brands=brands)

    assert stats.carousel_responses == 3
    assert stats.carousel_rate == pytest.approx(0.6)
    # Self appears as a product in carousels 0 and 2.
    assert stats.self_appearances == 2
    assert stats.self_appearance_rate == pytest.approx(2 / 3)
    # 2 self slots / 4 tracked-brand slots.
    assert stats.share_of_voice == pytest.approx(0.5)
    assert stats.avg_self_position == pytest.approx(1.0)

    assert len(stats.competitors) == 1
    blupebble = stats.competitors[0]
    assert blupebble.brand_id == 2
    assert blupebble.appearances == 2
    assert blupebble.share_of_voice == pytest.approx(0.5)

    # Untracked sellers still surface in the catalog (competitive intel).
    titles = {p.title for p in stats.products}
    assert "Sony WF-1000XM5" in titles
    treblab = next(p for p in stats.products if p.title == "TREBLAB X4 Wireless Earbuds")
    assert treblab.appearances == 2
    assert treblab.is_self is True
    assert treblab.best_position == 1
