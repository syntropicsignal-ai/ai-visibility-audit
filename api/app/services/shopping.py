from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass

from app.models import Brand
from app.providers.base import ShoppingProduct
from app.schemas import ShoppingCompetitorShare, ShoppingProductStat, ShoppingVisibility
from app.services.analysis import detect_brand_in_text


def product_to_row(product: ShoppingProduct) -> dict:
    return asdict(product)


def product_from_row(row: dict) -> ShoppingProduct:
    return ShoppingProduct(
        position=row.get("position") or 0,
        title=row.get("title") or "",
        price=row.get("price"),
        rating=row.get("rating"),
        reviews=row.get("reviews"),
        image=row.get("image"),
        link=row.get("link"),
        description=row.get("description"),
        tag=row.get("tag"),
    )


def match_product_brand(product: ShoppingProduct, brands: list[Brand]) -> Brand | None:
    # Self brand wins ties so our own products aren't labelled as a competitor.
    haystack = product.title
    if product.description:
        haystack = f"{haystack} {product.description}"
    for brand in sorted(brands, key=lambda b: not b.is_self):
        if detect_brand_in_text(haystack, brand)["found"]:
            return brand
    return None


@dataclass
class _ProductAccum:
    title: str
    brand_id: int | None
    brand_name: str | None
    is_self: bool
    positions: list[int]
    ratings: list[float]
    sample_price: str | None


def compute_shopping_stats(
    carousels: list[list[ShoppingProduct]],
    total_responses: int,
    brands: list[Brand],
    *,
    top_products: int = 50,
) -> ShoppingVisibility:
    # `total_responses` counts every response in scope, carousel or not, so
    # carousel_rate reflects how often shopping shows up at all.
    self_ids = {b.id for b in brands if b.is_self}
    self_slots = 0
    tracked_slots = 0
    self_positions: list[int] = []
    self_response_hits = 0
    brand_slots: dict[int, int] = defaultdict(int)
    brand_response_hits: dict[int, int] = defaultdict(int)
    brand_names: dict[int, str] = {}
    catalog: dict[str, _ProductAccum] = {}

    for products in carousels:
        brands_in_this: set[int] = set()
        self_in_this = False
        for product in products:
            matched = match_product_brand(product, brands)

            if matched is not None:
                tracked_slots += 1
                brand_slots[matched.id] += 1
                brand_names[matched.id] = matched.name
                brands_in_this.add(matched.id)
                if matched.is_self:
                    self_slots += 1
                    self_positions.append(product.position)
                    self_in_this = True

            key = product.title.strip().lower()
            acc = catalog.get(key)
            if acc is None:
                acc = _ProductAccum(
                    title=product.title.strip(),
                    brand_id=matched.id if matched is not None else None,
                    brand_name=matched.name if matched is not None else None,
                    is_self=matched.is_self if matched is not None else False,
                    positions=[],
                    ratings=[],
                    sample_price=None,
                )
                catalog[key] = acc
            acc.positions.append(product.position)
            if product.rating is not None:
                acc.ratings.append(product.rating)
            if acc.sample_price is None and product.price:
                acc.sample_price = product.price

        if self_in_this:
            self_response_hits += 1
        for bid in brands_in_this:
            brand_response_hits[bid] += 1

    competitors = [
        ShoppingCompetitorShare(
            brand_id=bid,
            brand_name=brand_names[bid],
            appearances=brand_response_hits[bid],
            share_of_voice=(brand_slots[bid] / tracked_slots) if tracked_slots else 0.0,
        )
        for bid in brand_slots
        if bid not in self_ids
    ]
    competitors.sort(key=lambda c: (-c.appearances, -c.share_of_voice))

    products = [
        ShoppingProductStat(
            title=acc.title,
            brand_id=acc.brand_id,
            brand_name=acc.brand_name,
            is_self=acc.is_self,
            appearances=len(acc.positions),
            avg_position=sum(acc.positions) / len(acc.positions),
            best_position=min(acc.positions),
            avg_rating=(sum(acc.ratings) / len(acc.ratings)) if acc.ratings else None,
            sample_price=acc.sample_price,
        )
        for acc in catalog.values()
    ]
    products.sort(key=lambda p: (-p.appearances, p.avg_position))

    carousel_responses = len(carousels)
    return ShoppingVisibility(
        total_responses=total_responses,
        carousel_responses=carousel_responses,
        carousel_rate=(carousel_responses / total_responses) if total_responses else 0.0,
        self_appearances=self_response_hits,
        self_appearance_rate=(self_response_hits / carousel_responses)
        if carousel_responses
        else 0.0,
        share_of_voice=(self_slots / tracked_slots) if tracked_slots else 0.0,
        avg_self_position=(sum(self_positions) / len(self_positions)) if self_positions else None,
        competitors=competitors,
        products=products[:top_products],
    )
