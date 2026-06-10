"""Citation URL normalization + brand-domain matching.

Aggregation keeps subdomains distinct (shop.example.com vs example.com);
brand matching is forgiving (registering example.com matches shop.*)."""

from __future__ import annotations

from urllib.parse import urlparse

from app.models import Brand


def normalize_citation_host(url: str) -> str | None:
    """Return the canonical host for a citation URL, or None if unparseable.

    - lowercased
    - leading `www.` stripped
    - port stripped (urlparse already separates `hostname` from `port`)
    - path / query / fragment dropped — this is a host-only normalization
    """
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    return host.removeprefix("www.")


def normalize_brand_domain(domain: str) -> str:
    """Normalize a Brand.domains entry the same way we normalize hosts.

    Brands are user-entered, so we tolerate `https://example.com/`,
    `www.example.com`, or just `example.com`. The output is always a bare
    lowercased host with no leading `www.`.
    """
    domain = domain.strip().lower()
    if not domain:
        return ""
    # Tolerate users pasting a full URL into the domains field.
    if "://" in domain:
        parsed = urlparse(domain)
        domain = (parsed.hostname or "").lower()
    return domain.removeprefix("www.").rstrip("/")


def build_brand_domain_index(brands: list[Brand]) -> dict[str, Brand]:
    """Map every registered brand domain → Brand for O(1) exact lookups.

    If two brands claim the same domain (shouldn't happen but might in
    dev DBs) the later one wins — this is a "best effort" enrichment,
    not a constraint.
    """
    index: dict[str, Brand] = {}
    for brand in brands:
        for raw in brand.domains or []:
            d = normalize_brand_domain(raw)
            if d:
                index[d] = brand
    return index


def match_brand_for_host(host: str, brand_index: dict[str, Brand]) -> Brand | None:
    """Find the Brand that owns `host`, allowing subdomain matches.

    Tries exact match first, then walks parent suffixes so
    `shop.example.com` matches a brand registered for `example.com`.
    """
    if not host:
        return None
    if host in brand_index:
        return brand_index[host]
    # Walk parent domains: a.b.c.example.com → b.c.example.com → c.example.com → ...
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in brand_index:
            return brand_index[suffix]
    return None
