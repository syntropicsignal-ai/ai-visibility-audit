import re
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Analysis, Brand, Response, Sentiment
from app.services.sentiment import classify_brand_mentions


def detect_brand_in_text(text: str, brand: Brand) -> dict:
    # Recommendation is decided downstream by the LLM classifier —
    # regex was too brittle to catch soft endorsements.
    text_lower = text.lower()
    first_offset: int | None = None

    # Check brand name, domains, and aliases. We scan ALL terms and keep
    # the earliest match offset so a later alias doesn't get shadowed by
    # an earlier weaker term.
    search_terms = [brand.name.lower()]
    search_terms.extend(d.lower() for d in (brand.domains or []))
    search_terms.extend(a.lower() for a in (brand.aliases or []))

    for term in search_terms:
        # Word-boundary anchors avoid e.g. "sadowniczy" matching inside
        # "sadowniczych". Python 3's \b is Unicode-aware.
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        match = pattern.search(text)
        if match and (first_offset is None or match.start() < first_offset):
            first_offset = match.start()

    # Check if a link to the brand's domain is present
    link_present = False
    for domain in brand.domains or []:
        if domain.lower() in text_lower:
            # Look for URL-like patterns
            url_pattern = re.compile(
                rf"https?://[^\s]*{re.escape(domain.lower())}[^\s]*", re.IGNORECASE
            )
            if url_pattern.search(text):
                link_present = True
                break

    return {
        "found": first_offset is not None,
        "first_offset": first_offset,
        "link_present": link_present,
    }


def classify_source_urls(
    source_urls: list[str], self_brand: Brand, competitors: list[Brand]
) -> tuple[list[str], list[dict]]:
    # Returns (our_pages, competitor_mentions).
    our_pages = []
    competitor_mentions = []

    self_domains = {d.lower() for d in (self_brand.domains or [])}
    competitor_domain_map: dict[str, str] = {}
    for comp in competitors:
        for d in comp.domains or []:
            competitor_domain_map[d.lower()] = comp.name

    for url in source_urls:
        try:
            parsed = urlparse(url)
        except ValueError:
            continue
        domain = (parsed.hostname or "").removeprefix("www.")

        if any(self_d in domain for self_d in self_domains):
            our_pages.append(url)
        else:
            for comp_domain, comp_name in competitor_domain_map.items():
                if comp_domain in domain:
                    competitor_mentions.append({"name": comp_name, "url": url})
                    break

    return our_pages, competitor_mentions


async def analyze_response(
    db: AsyncSession, response: Response, brands: list[Brand]
) -> list[Analysis]:
    competitors = [b for b in brands if not b.is_self]
    source_urls = response.source_urls or []

    detections: dict[int, dict] = {}
    found_brand_names: list[str] = []
    for brand in brands:
        d = detect_brand_in_text(response.text, brand)
        detections[brand.id] = d
        if d["found"]:
            found_brand_names.append(brand.name)

    classifications = {}
    if found_brand_names:
        classifications = await classify_brand_mentions(response.text, found_brand_names)

    # Pass 3: build and persist the Analysis rows.
    analyses = []
    for brand in brands:
        detection = detections[brand.id]

        our_pages: list[str] = []
        competitor_data: list[dict] = []
        if brand.is_self and isinstance(source_urls, list):
            our_pages, competitor_data = classify_source_urls(source_urls, brand, competitors)

        if detection["found"]:
            classification = classifications.get(brand.name)
            if classification is not None:
                sentiment = classification["sentiment"]
                recommended = classification["recommended"]
            else:
                sentiment = Sentiment.neutral
                recommended = False
        else:
            sentiment = Sentiment.not_mentioned
            recommended = False

        analysis = Analysis(
            response_id=response.id,
            brand_id=brand.id,
            brand_found=detection["found"],
            recommended=recommended,
            link_present=detection["link_present"],
            sentiment=sentiment,
            our_pages=our_pages if our_pages else None,
            competitors=competitor_data if competitor_data else None,
        )
        db.add(analysis)
        analyses.append(analysis)

    await db.commit()
    return analyses
