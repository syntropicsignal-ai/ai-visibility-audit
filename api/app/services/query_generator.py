"""Benchmark query generator."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, cast
from urllib.parse import urlparse

from exa_py import Exa
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import ClientProfile as ClientProfileModel
from app.services.dataforseo_labs import (
    DomainKeywordReport,
    RankedKeyword,
    fetch_ranked_keywords,
)

logger = logging.getLogger(__name__)


SITE_PAGES_TO_FETCH = 20
COMPETITORS_TO_FETCH = 8
OVERSAMPLE_TARGET = 70  # Stage 5 candidate count
FINAL_TARGET_DEFAULT = 50  # Stage 6 kept count

INTENT_MIX = {
    "transactional": 0.45,
    "informational": 0.20,
    "comparative": 0.20,
    "brand": 0.10,
    "local": 0.05,
}

VALID_INTENTS = set(INTENT_MIX.keys())
VALID_LENGTH_MODES = {"search_like", "conversational"}
VALID_BUYER_STAGES = {"problem_unaware", "problem_aware", "solution_aware"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SiteInfo:
    domain: str
    pages: list[dict] = field(default_factory=list)  # [{url, title, text}]


@dataclass
class BusinessProfile:
    """Structured profile of the target brand."""

    brand_name: str
    language: str  # e.g. "Polish", "English"
    country: str  # e.g. "Poland", "Germany"
    currency: str  # e.g. "PLN", "EUR"
    product_categories: list[str]
    key_products: list[str]
    distribution: str  # national | local | regional | international
    customer_type: str  # B2C | B2B | mixed
    tone: str  # professional | casual | technical
    domain_terms: list[str]  # industry jargon to use
    seasonal_factors: list[str]  # time-of-year signals
    summary: str = ""  # one-paragraph human-readable


@dataclass
class CompetitorProfile:
    brand_name: str
    domain: str
    categories: list[str] = field(default_factory=list)
    positioning: str = ""


@dataclass
class KeywordSignals:
    """Per-domain organic-search ranking data from DataForSEO Labs.
    `gap_keywords` is the diff: terms competitors rank for that the
    client domain does not."""

    client: DomainKeywordReport
    competitors: list[DomainKeywordReport] = field(default_factory=list)
    gap_keywords: list[RankedKeyword] = field(default_factory=list)


@dataclass
class Persona:
    """One buyer persona synthesized from the category corpus."""

    name: str
    goal: str
    vocabulary_samples: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    typical_intents: list[str] = field(default_factory=list)


@dataclass
class GeneratedQuery:
    text: str
    intent: str  # VALID_INTENTS
    length_mode: str = "conversational"  # VALID_LENGTH_MODES
    buyer_stage: str = "problem_aware"  # VALID_BUYER_STAGES
    shape: int = 0  # 1..9, maps to research shape library
    tags: list[str] = field(default_factory=list)
    # Seed attribution — None on synthetic prompts.
    seed_source: str | None = None  # "brand" | "gap" | "synthetic"
    seed_keyword: str | None = None
    seed_search_volume: int | None = None
    seed_position: int | None = None  # only populated for "brand" source


# ---------------------------------------------------------------------------
# Exa discovery — Stages 0a / 0b
# ---------------------------------------------------------------------------


def _clean_domain(domain: str) -> str:
    d = domain.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return d.removeprefix("www.")


def _domain_to_brand_hint(domain: str) -> str:
    """Best-effort humanization of a bare domain for company-search queries.

    e.g. "acmegardens.com" -> "acmegardens". Exa's company search
    handles fuzzy queries reasonably; we don't try to split compound slugs.
    """
    sld = _clean_domain(domain).split(".", 1)[0]
    return sld.replace("-", " ").strip()


async def discover_company_research(
    exa: Exa, domain: str, brand_hint: str | None = None
) -> str | None:
    """Fetch Exa's structured company-DB entry for the target domain.

    Queries by brand hint and filters results to ones whose URL hostname
    equals the target domain. Returns the structured text on match, or
    None if Exa has no entry for this domain.
    """
    target = _clean_domain(domain).lower()
    hint = (brand_hint or _domain_to_brand_hint(domain)).strip() or target

    def _search():
        return exa.search_and_contents(
            query=hint,
            num_results=5,
            category="company",
            text=True,
        )

    try:
        result = await asyncio.to_thread(_search)
    except Exception:
        logger.exception("Exa company search failed for %s", domain)
        return None

    for r in result.results:
        url = getattr(r, "url", "") or ""
        try:
            host = (urlparse(url).hostname or "").removeprefix("www.").lower()
        except Exception:
            continue
        if host == target:
            text = (getattr(r, "text", "") or "").strip()
            return text or None
    return None


async def discover_site_pages(
    exa: Exa, domain: str, max_pages: int = SITE_PAGES_TO_FETCH
) -> SiteInfo:
    """Fetch the top N pages for the client's own site (Exa-cached content)."""
    clean = _clean_domain(domain)

    def _search():
        return exa.search_and_contents(
            query=f"site:{clean}",
            num_results=max_pages,
            include_domains=[clean],
            text={"max_characters": 3000},
            highlights={"num_sentences": 5},
        )

    result = await asyncio.to_thread(_search)

    pages: list[dict] = []
    for r in result.results:
        pages.append(
            {
                "url": getattr(r, "url", ""),
                "title": r.title or "",
                "text": r.text or "",
            }
        )

    return SiteInfo(domain=clean, pages=pages)


async def discover_competitors(
    exa: Exa, site_info: SiteInfo, max_competitors: int = COMPETITORS_TO_FETCH
) -> list[dict]:
    """Return competitor site snippets via Exa `find_similar_and_contents`."""

    def _similar():
        # Exa-py's type stubs are imprecise here; the call is correct.
        return exa.find_similar_and_contents(  # pyright: ignore[reportCallIssue]
            url=f"https://{site_info.domain}",
            num_results=max_competitors + 4,  # oversample in case of junk
            exclude_domains=[site_info.domain],
            text={"max_characters": 1000},
            highlights={"num_sentences": 3},
        )

    result = await asyncio.to_thread(_similar)

    seen: set[str] = set()
    raw: list[dict] = []
    for r in result.results:
        if len(raw) >= max_competitors:
            break
        url = getattr(r, "url", "")
        try:
            host = (urlparse(url).hostname or "").removeprefix("www.")
        except Exception:
            continue
        if not host or host in seen or host == site_info.domain:
            continue
        seen.add(host)
        raw.append(
            {
                "url": url,
                "domain": host,
                "title": r.title or host,
                "text": (r.text or "")[:1000],
            }
        )
    return raw


# ---------------------------------------------------------------------------
# Persona synthesis
# ---------------------------------------------------------------------------


PERSONA_SYSTEM = """\
You synthesize realistic buyer personas grounded in measured user voice.

You are given:
  - a business profile
  - a category corpus: real questions and conversational samples drawn
    from WildChat-1M (real ChatGPT conversations) and Google PAA in this
    vertical

Your job is to identify the distinct *buyer types* whose voices appear
in the corpus, NOT to invent personas from imagination. Every persona
must have vocabulary samples drawn directly from the corpus. If the
corpus is too thin or off-topic to support a coherent persona, return
fewer personas — never pad with imagined ones.
"""


PERSONA_USER_TEMPLATE = """\
## Business profile
Brand: {brand_name}
Country: {country}  ·  Language: {language}
Categories: {categories}
Key products: {key_products}
Customer type: {customer_type}  ·  Distribution: {distribution}

## Category corpus (real user voice)

### People-Also-Ask (Google-measured, n={n_paa})
{paa_block}

### WildChat-1M samples (real ChatGPT conversations, top by topical similarity)
{wildchat_block}

### Google search suggestions (autocomplete, n={n_sugg})
{suggestions_block}

## Task
Synthesize 6–10 distinct buyer personas grounded in this corpus. Each
persona should represent a meaningfully different angle on this category:
different goal, budget, life situation, expertise level, or use case.

Return JSON:

{{
  "personas": [
    {{
      "name": "short label, e.g. 'first-time city-bike commuter'",
      "goal": "one short sentence on what they're trying to accomplish",
      "vocabulary_samples": ["3–5 short phrases this persona would use, drawn from the corpus"],
      "constraints": ["typical constraints: budget, region, season, use-case, exclusion"],
      "typical_intents": ["transactional|informational|comparative|brand|local"]
    }}
  ]
}}

Rules:
- vocabulary_samples MUST come from the corpus above. Don't invent phrasings.
- Never write the same persona twice with a different label. Each persona
  must be functionally distinct.
- If the corpus is sparse (few PAA + few WildChat), return fewer personas
  rather than padding with imagined ones — 4 grounded personas beat 8 hollow ones.
- JSON only, no prose.
"""


def _persona_corpus_block(samples: list, max_lines: int = 25) -> str:
    if not samples:
        return "(none)"
    lines: list[str] = []
    for s in samples[:max_lines]:
        text = getattr(s, "text", str(s))
        seed = getattr(s, "seed", None)
        if seed:
            lines.append(f"  - ({seed}) {text}")
        else:
            lines.append(f"  - {text}")
    return "\n".join(lines)


async def synthesize_personas(
    client: AsyncOpenAI,
    profile: BusinessProfile,
    corpus,  # CategoryCorpus from app.services.corpus
) -> list[Persona]:
    """Synthesize up to 10 buyer personas from the category corpus.
    Returns an empty list on corpus error or empty corpus."""
    paa = corpus.by_source("paa") if corpus else []
    wildchat = corpus.by_source("wildchat") if corpus else []
    suggestions = corpus.by_source("suggestion") if corpus else []

    if not (paa or wildchat or suggestions):
        return []

    user = PERSONA_USER_TEMPLATE.format(
        brand_name=profile.brand_name,
        country=profile.country,
        language=profile.language,
        categories=", ".join(profile.product_categories) or "(none)",
        key_products=", ".join(profile.key_products) or "(none)",
        customer_type=profile.customer_type,
        distribution=profile.distribution,
        paa_block=_persona_corpus_block(paa, max_lines=20),
        wildchat_block=_persona_corpus_block(wildchat, max_lines=25),
        suggestions_block=_persona_corpus_block(suggestions, max_lines=25),
        n_paa=len(paa),
        n_sugg=len(suggestions),
    )

    data = await _llm_json(
        client,
        model=settings.query_profile_model,
        system=PERSONA_SYSTEM,
        user=user,
        temperature=0.7,
    )
    raw = data.get("personas", []) if isinstance(data, dict) else []
    out: list[Persona] = []
    for p in raw:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        out.append(
            Persona(
                name=name,
                goal=str(p.get("goal") or ""),
                vocabulary_samples=[str(v) for v in (p.get("vocabulary_samples") or [])],
                constraints=[str(c) for c in (p.get("constraints") or [])],
                typical_intents=[str(i) for i in (p.get("typical_intents") or [])],
            )
        )
    return out[:10]


# ---------------------------------------------------------------------------
# Stage 4 — Keyword signals (DataForSEO Labs)
# ---------------------------------------------------------------------------


async def fetch_client_ranked_keywords(
    client_domain: str,
    *,
    location_code: int,
    language_code: str,
    limit: int = 100,
) -> DomainKeywordReport:
    """Fetch DataForSEO ranked keywords for the client domain only."""
    return await fetch_ranked_keywords(
        client_domain,
        location_code=location_code,
        language_code=language_code,
        limit=limit,
    )


async def discover_keyword_signals(
    client_domain: str,
    competitor_domains: list[str],
    *,
    location_code: int,
    language_code: str,
    client_limit: int = 100,
    competitor_limit: int = 50,
    client_report: DomainKeywordReport | None = None,
) -> KeywordSignals:
    """Pull ranked keywords for the client + each competitor in parallel.
    Empty per-domain reports are folded in silently. `client_report`
    lets the caller pass a pre-fetched client report to avoid a second
    DataForSEO call."""
    if client_report is None:
        client_task = fetch_ranked_keywords(
            client_domain,
            location_code=location_code,
            language_code=language_code,
            limit=client_limit,
        )
    else:
        # Narrow `client_report` for pyright — we've already excluded None
        # via the `if client_report is None` branch above.
        cached_report: DomainKeywordReport = client_report

        async def _passthrough() -> DomainKeywordReport:
            return cached_report

        client_task = _passthrough()

    comp_tasks = [
        fetch_ranked_keywords(
            d,
            location_code=location_code,
            language_code=language_code,
            limit=competitor_limit,
        )
        for d in competitor_domains
    ]
    client_report, *competitor_reports = await asyncio.gather(client_task, *comp_tasks)

    # Gap = competitor terms the client doesn't rank for, ordered by volume.
    client_terms = {kw.keyword.lower() for kw in client_report.keywords}
    seen_gap: set[str] = set()
    gap: list[RankedKeyword] = []
    for report in competitor_reports:
        for kw in report.keywords:
            key = kw.keyword.lower()
            if key in client_terms or key in seen_gap:
                continue
            seen_gap.add(key)
            gap.append(kw)
    gap.sort(key=lambda k: k.search_volume or 0, reverse=True)

    return KeywordSignals(
        client=client_report,
        competitors=list(competitor_reports),
        gap_keywords=gap,
    )


def _format_keyword_table(keywords: list[RankedKeyword], limit: int) -> str:
    if not keywords:
        return "(none)"
    rows = []
    for kw in keywords[:limit]:
        vol = f"{kw.search_volume:,}/mo" if kw.search_volume else "—"
        rows.append(f"  - {kw.keyword!r}  pos {kw.position}  vol {vol}")
    return "\n".join(rows)


def _stage5_keyword_seed_block(
    signals: KeywordSignals | None,
    client_keyword_limit: int = 40,
    gap_limit: int = 30,
) -> str:
    """Render the keyword-signal block (client-ranks-for + competitor-gap
    tables) for the stage-5 user prompt."""
    if signals is None:
        return ""
    return f"""\

## Real-world keyword signals

These are actual terms users search for, pulled from organic ranking
data. Treat them as inspiration for the *topics and shapes* of queries
to generate — DO NOT copy keywords verbatim, and do not let them dominate
the output. They are seeds, not templates.

### Keywords the client already ranks for (top by volume)
{_format_keyword_table(signals.client.keywords, client_keyword_limit)}

### Keyword gap — competitors rank for these but client doesn't
{_format_keyword_table(signals.gap_keywords, gap_limit)}
"""


# ---------------------------------------------------------------------------
# LLM helper — small wrapper around AsyncOpenAI chat.completions
# ---------------------------------------------------------------------------


def _chat_client() -> AsyncOpenAI:
    """Chat completions run on Gemini's OpenAI-compatible endpoint."""
    return AsyncOpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


def _embeddings_client() -> AsyncOpenAI:
    """Query embeddings run on Gemini's OpenAI-compatible endpoint — the
    WildChat corpus is pre-embedded with gemini-embedding-001."""
    return AsyncOpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


async def _llm_json(
    client: AsyncOpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float | None = None,
) -> Any:
    """Call the chat API in JSON mode and return parsed content.

    Accepts `temperature=None` for models that don't support the knob.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    try:
        resp = await client.chat.completions.create(**kwargs)
    except Exception as e:
        # Some newer models reject the temperature parameter; retry without it.
        if temperature is not None and "temperature" in str(e).lower():
            kwargs.pop("temperature", None)
            resp = await client.chat.completions.create(**kwargs)
        else:
            raise

    raw = resp.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.error("LLM returned non-JSON output: %s", raw[:300])
        return {}


# ---------------------------------------------------------------------------
# Stage 2 — Business profile extraction
# ---------------------------------------------------------------------------


STAGE2_SYSTEM = """\
You extract structured business profiles from multiple signal sources about
a company. The sources have different reliability characteristics and a
strict trust hierarchy applies — your job is to follow it, not balance them.

Trust hierarchy (most → least reliable):
  1. Exa company-database entry — curated structured data. When present,
     this is authoritative for industry, product_categories, key_products.
  2. DataForSEO ranked keywords — what the domain actually ranks for in
     Google. Ground truth for what the domain is *known for*. Authoritative
     for domain_terms; should anchor product_categories when (1) is missing.
  3. Page text fetched from the site — least reliable. Use only for
     tone, customer_type, distribution, summary — never to override
     (1) or (2) on what the business sells.

When sources conflict on industry/categories/products, trust (1) > (2) > (3).
Never invent facts. If a field has no signal, leave it blank or "unknown".
"""

STAGE2_USER_TEMPLATE = """\
## Domain
{domain}

## Source 1 — Exa company database entry (authoritative for industry/products)
{company_block}

## Source 2 — DataForSEO ranked keywords (authoritative for domain_terms)
{keywords_block}

## Source 3 — Pages fetched from the site (advisory; for tone/distribution/summary only)
{pages_block}

## Task
Extract the business profile. Return a single JSON object with these keys:

{{
  "brand_name":       "the display form of the brand (e.g. 'Acme Gardens', not the domain)",
  "language":         "full English name of the primary site language (e.g. 'Polish', 'German', 'English')",
  "country":          "primary country the business serves",
  "currency":         "3-letter code (PLN, EUR, USD, ...)",
  "product_categories": ["short", "category", "names"],
  "key_products":     ["specific", "notable", "products or product lines"],
  "distribution":     "national | local | regional | international",
  "customer_type":    "B2C | B2B | mixed",
  "tone":             "professional | casual | technical",
  "domain_terms":     ["industry-specific terms in the site's language that a real user would type"],
  "seasonal_factors": ["any time-of-year signals, e.g. 'spring planting', 'Christmas gifts'"],
  "summary":          "one short paragraph describing the business, in English"
}}

Rules:
- brand_name is the HUMAN brand name. Prefer Source 1's brand label; otherwise
  derive from page titles. Never return a bare domain.
- product_categories / key_products: if Source 1 is present, mirror its
  industry/categories/products. If only Sources 2+3 are present, derive
  primarily from Source 2 (the keywords); page text alone is insufficient.
- domain_terms: prefer terms that actually appear in Source 2's keyword
  table (those are demonstrably typed by real users); supplement from
  Source 3 only if Source 2 is sparse.
- distribution: if the site advertises shipping across the whole country,
  that's "national". Single-city / in-person only = "local".
- Return JSON only. No prose, no markdown.
"""


def _pages_block(pages: list[dict], max_chars_per_page: int = 2000) -> str:
    if not pages:
        return "(no pages — site returned empty content)"
    parts = []
    for i, p in enumerate(pages, 1):
        title = p.get("title", "")
        url = p.get("url", "")
        text = (p.get("text") or "")[:max_chars_per_page]
        parts.append(f"--- Page {i} ---\nURL: {url}\nTitle: {title}\nText:\n{text}")
    return "\n\n".join(parts)


def _stage2_company_block(company_research: str | None) -> str:
    if not company_research:
        return "(no Exa company-DB entry for this domain — small/niche brand or new site)"
    # Truncate to keep the prompt bounded; structured Exa entries are typically
    # 1–10KB. Top sections (industry, about, categories) come first, so a hard
    # cut at 6000 chars preserves the high-signal portion.
    return company_research[:6000]


def _stage2_keywords_block(client_keywords: DomainKeywordReport | None) -> str:
    if client_keywords is None or not client_keywords.keywords:
        return "(no DataForSEO ranked keywords — domain has no organic-search history yet)"
    return _format_keyword_table(client_keywords.keywords, limit=40)


class ProfileExtractionError(RuntimeError):
    """All signal sources are empty — cannot synthesize a profile."""


async def extract_business_profile(
    client: AsyncOpenAI,
    site_info: SiteInfo,
    *,
    company_research: str | None = None,
    client_keywords: DomainKeywordReport | None = None,
) -> BusinessProfile:
    """Extract a structured business profile, weighted toward authoritative signals.

    Sources, in trust order:
      1. `company_research` — Exa company-DB entry (structured)
      2. `client_keywords`  — DataForSEO ranked keywords (organic ground truth)
      3. `site_info.pages`  — page text (advisory only; poison-prone)

    Raises `ProfileExtractionError` when all three are effectively empty —
    the pipeline should fail loudly here rather than silently confabulate
    a profile from nothing.
    """
    has_company = bool(company_research and company_research.strip())
    has_keywords = bool(client_keywords and client_keywords.keywords)
    has_pages = any((p.get("text") or "").strip() for p in site_info.pages)
    if not (has_company or has_keywords or has_pages):
        raise ProfileExtractionError(
            f"No usable signal for {site_info.domain}: Exa company-DB had no "
            "entry, DataForSEO returned zero keywords, and the site crawl "
            "yielded no readable text. Cannot synthesize a profile."
        )

    user = STAGE2_USER_TEMPLATE.format(
        domain=site_info.domain,
        company_block=_stage2_company_block(company_research),
        keywords_block=_stage2_keywords_block(client_keywords),
        pages_block=_pages_block(site_info.pages),
    )
    data = await _llm_json(
        client,
        model=settings.query_profile_model,
        system=STAGE2_SYSTEM,
        user=user,
    )
    if not isinstance(data, dict):
        data = {}

    return BusinessProfile(
        brand_name=str(data.get("brand_name") or site_info.domain),
        language=str(data.get("language") or "English"),
        country=str(data.get("country") or "unknown"),
        currency=str(data.get("currency") or "USD"),
        product_categories=list(data.get("product_categories") or []),
        key_products=list(data.get("key_products") or []),
        distribution=str(data.get("distribution") or "national"),
        customer_type=str(data.get("customer_type") or "B2C"),
        tone=str(data.get("tone") or "professional"),
        domain_terms=list(data.get("domain_terms") or []),
        seasonal_factors=list(data.get("seasonal_factors") or []),
        summary=str(data.get("summary") or ""),
    )


# ---------------------------------------------------------------------------
# Stage 3 — Competitor profile extraction
# ---------------------------------------------------------------------------


STAGE3_SYSTEM = """\
You clean up noisy competitor lists. Given a set of sites returned by a
similarity-search engine (Exa), you produce structured competitor profiles.
Drop any site that is clearly not a real competitor (directories, aggregators,
Wikipedia, generic marketplaces, unrelated topics). Never invent facts.
"""

STAGE3_USER_TEMPLATE = """\
## Reference business
Brand: {brand}
Domain: {domain}
Country: {country}
Categories: {categories}
Summary: {summary}

## Candidate competitors (from similarity search)
{candidates_block}

## Task
Return up to {target} genuine competitors as a JSON object:

{{
  "competitors": [
    {{
      "brand_name":  "human brand name",
      "domain":      "bare domain, no scheme",
      "categories":  ["short", "categories"],
      "positioning": "one short sentence describing how they position themselves"
    }}
  ]
}}

Rules:
- Drop aggregators, marketplaces, directories, Wikipedia, news sites, and any
  site in a different country/language unless cross-border competition is
  obvious.
- If fewer than {target} valid competitors exist, return fewer.
- JSON only, no prose.
"""


def _competitors_block(candidates: list[dict]) -> str:
    parts = []
    for i, c in enumerate(candidates, 1):
        parts.append(
            f"--- Candidate {i} ---\n"
            f"Domain: {c.get('domain', '')}\n"
            f"Title:  {c.get('title', '')}\n"
            f"Text:   {c.get('text', '')}"
        )
    return "\n\n".join(parts)


async def extract_competitor_profiles(
    client: AsyncOpenAI,
    profile: BusinessProfile,
    candidates: list[dict],
    target: int = COMPETITORS_TO_FETCH,
) -> list[CompetitorProfile]:
    if not candidates:
        return []

    user = STAGE3_USER_TEMPLATE.format(
        brand=profile.brand_name,
        domain="(see candidates)",
        country=profile.country,
        categories=", ".join(profile.product_categories) or "unknown",
        summary=profile.summary or "(no summary)",
        candidates_block=_competitors_block(candidates),
        target=target,
    )
    data = await _llm_json(
        client,
        model=settings.query_profile_model,
        system=STAGE3_SYSTEM,
        user=user,
    )
    raw_list = data.get("competitors", []) if isinstance(data, dict) else []
    out: list[CompetitorProfile] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        dom = _clean_domain(str(item.get("domain") or ""))
        if not dom:
            continue
        out.append(
            CompetitorProfile(
                brand_name=str(item.get("brand_name") or dom),
                domain=dom,
                categories=list(item.get("categories") or []),
                positioning=str(item.get("positioning") or ""),
            )
        )
    return out[:target]


# ---------------------------------------------------------------------------
# Stage 5 — Oversample query generation
# ---------------------------------------------------------------------------

# Shape library: the 9 shapes + verbatim examples below come from real
# Polish shopping queries harvested from WildChat-1M. Kept verbatim
# because realism depends on the model internalising the shape of
# actual user queries, not paraphrases of them.
#
# The shape library and WildChat seeds below are tuned for Polish
# consumer ecommerce.

STAGE5_SYSTEM = """\
You generate realistic benchmark queries for GEO (Generative Engine
Optimization) monitoring. Clients use these queries to measure how often
their brand appears in AI assistant responses.

Every query you emit MUST be:
- a query a real user would actually type, verbatim
- in Asking mode (seeking information), NEVER Doing mode ("write me…",
  "plan a…", "help me design…"), NEVER Expressing mode ("I feel…")
- written in the business's language, never mixed languages

Noun-phrase queries ("iPhone 15", "hortensja ogrodowa mrozoodporna") are
legitimate and encouraged for the search_like length mode.
"""


def _stage5_shape_library() -> str:
    """Return the 9-shape few-shot block with verbatim WildChat-PL seeds."""
    return """\
## Shape library (distribute queries evenly across all applicable shapes)

Shape 1 — Model/product-number + specific question
  Real WildChat-PL examples:
    "predator triton 500 z i7 9750 ile max ram można dołożyć"
    "Podaj mi liste kompatybilnych wentylatorów z lenovo ideapad s340-15iil"
    "Znajdź odpowiedniki układu scalonego SDC9300"
    "PrimaDonna Class ECAM550.85.MS podaj mi modele filtrow ktore pasuja"

Shape 2 — Product A vs product B (bare comparison)
  Real examples:
    "Sharp KC-A40EU-B czy Sharp KC-G50EU-H"
    "jaki sprzęt audio jest lepszy yamaha czy technics?"
    "grusza konferencja czy faworytka"
    "Zarówka H7 150% czy 200%"

Shape 3 — Constraint-stacked search (THE workhorse shape)
  Real examples:
    "znajdź trampki rozmiar 39 czarne do 300zł"
    "jaki telefon kupic do 1000zl ale nie chinski"
    "Jakie auta klasyczne do 20 000zł najszybciej zyskują na wartości"
    "Jaki ruter dobrać do domku jednorodzinnego, pietrowego"

Shape 4 — Best/top X (category comparative)
  Real examples:
    "Jaki operator internetowy jest najlepszy?"
    "top 3 najlepsze auta"
    "najlepsze ustawienie sieciowe ps5"
    "Jaki telefon kupić za 2000zł?"

Shape 5 — "Is X worth it / does X work with Y"
  Real examples:
    "Czy opalarka nitro jest dobrym urządzeniem"
    "Mam iPhone 13 pro czy warto go wymienić na 14 plus?"
    "Czy ładowarka będzie współpracowała z moim urządzeniem?"

Shape 6 — How-to / problem-aware practical
  Real examples:
    "hej jak ugotowac ryrz"
    "Jak wymienić filtr powietrza w opel astra j 1.6 benzyna"
    "Czym konserwować pasek urządzeń w samochodzie osobowym"
    "Jak dobrać rozmiar rolety rzymskiej?"

Shape 7 — Local intent
  Real examples:
    "Poleć mi najlepsze pizzerie w Mediolanie"
    "Który kebab przy al lotników jest dobry?"

Shape 8 — Gift / occasion
  Real example:
    "Jaki prezent na Boże Narodzenie sprezentować babci, która rzadko
     wychodzi z domu, ale jest w nienajgorszym stanie"

Shape 9 — Replacement / spare parts / compatibility
  Real examples:
    "popularne tarcze tnące do Robot Coupe"
    "części zamienne dla gastronomii"
    "Dostępność części zamiennych do pieców Rational"
"""


def _stage5_distribution_targets(profile: BusinessProfile, total: int) -> str:
    """Return the distribution block, adjusted for local-vs-national clients."""
    # Local share swaps with informational depending on geo footprint.
    if profile.distribution.lower() in {"national", "international", "regional"}:
        intents = "transactional 45%, informational 20%, comparative 20%, brand 10%, local 5%"
        local_rule = "Drop local almost entirely — the business sells nationally."
    else:
        intents = "transactional 45%, informational 10%, comparative 20%, brand 10%, local 15%"
        local_rule = "Local is meaningful — include city/region anchors."

    return f"""\
## Distribution targets (exactly {total} queries total)

Intent mix:          {intents}
Length mix:          60% search_like (≤8 words, often noun phrase, no punctuation)
                     40% conversational (12–25 words, full sentence, stacked constraints)
Buyer-stage mix:     15% problem_unaware, 55% problem_aware, 30% solution_aware
Grammar realism:     70% grammatically clean
                     20% missing diacritics (realistic typing)
                     10% light typos / casual phone-typing style
Constraint stacking: ≥50% of non-brand queries must stack 2+ explicit
                     constraints drawn from: price/budget (in {{currency}}),
                     size/dimension, region, season/time, use-case, exclusion.
Local rule:          {local_rule}
"""


STAGE5_USER_TEMPLATE = """\
{distribution_block}

## Hard rules (apply to every query)
1. Every query is Asking mode. Never Doing ("write…", "plan…", "create…"),
   never Expressing ("I feel…").
2. Noun-phrase queries are legitimate — "sadzonki borówki", "hortensja
   ogrodowa mrozoodporna" — and should make up a chunk of the search_like set.
3. Model/part numbers, price anchors (in {currency}), and seasonal anchors
   are HIGH-SIGNAL. Use them when the business sells products where they apply.
4. Brand names MUST use the display form ("{brand_name}"). Never use the
   bare domain as a brand name.
5. No near-duplicates. Vary the angle, not just the wording.
6. Write in {language}. Never mix languages.
7. Use the business's domain terms where natural: {domain_terms}

## Constraint-stacking quota (NON-NEGOTIABLE)
≥50% of non-brand queries must stack 2+ explicit constraints. Constraints
include: price/budget in {currency} (e.g. "do 50 zł"), size/dimension
(height, pot size), region/climate, season/time of year, use-case
(balcony, hedge, courtyard), exclusion ("bez chemii", "bez kolców"). Count
yourself before submitting — if you have <50% you have failed this rule.

## Brand-intent slot rules
Brand-intent queries (intent="brand") probe the *experience* of buying
from / using "{brand_name}". Each brand query should target a different
facet — pick from: opinions/reviews, delivery & shipping, packaging,
warranty / plant-takes-root guarantee, returns, payment, in-store pickup,
seasonality of dispatch, international shipping, voucher / gift card.
Do NOT make every brand query "{brand_name} opinie" or "{brand_name} X" —
spread the facets. Brand queries are NOT seeded by the keyword signals
below; the keyword signals are organic terms, not brand-experience probes.

{shape_library}

## Inputs

### Business profile
{profile_json}

### Buyer personas (draw query VOICE from these)
{personas_block}

### Category corpus — real user voice (draw query TOPICS from these)
{corpus_block}

### Competitors
{competitor_block}
{keyword_seed_block}

## Output format
Return a single JSON object:

{{
  "queries": [
    {{
      "text": "the user query verbatim",
      "intent": "transactional|informational|comparative|brand|local",
      "length_mode": "search_like|conversational",
      "buyer_stage": "problem_unaware|problem_aware|solution_aware",
      "shape": 1,
      "tags": ["1-3", "short", "tags"],
      "seed_source": "brand|gap|synthetic",
      "seed_keyword": "the literal keyword from the tables above that inspired this query, or null"
    }}
  ]
}}

Seed attribution rules:
- If you anchored this query to a row in "Keywords the client already
  ranks for", set seed_source="brand" and seed_keyword to that exact
  keyword string.
- If you anchored it to a row in "Keyword gap", set seed_source="gap"
  and seed_keyword accordingly.
- If you generated it from the business profile / shape library without
  anchoring to a specific keyword (e.g. brand-intent queries, generic
  shape-library variations), set seed_source="synthetic" and
  seed_keyword=null.
- Be honest about attribution — "synthetic" is the right answer when
  no specific keyword inspired the query. Don't manufacture a link.

Output EXACTLY {total} objects. No prose, no markdown, no code fences.
"""


def _competitor_block_for_prompt(competitors: list[CompetitorProfile]) -> str:
    if not competitors:
        return "(no known competitors)"
    lines = []
    for c in competitors:
        cats = ", ".join(c.categories) if c.categories else "—"
        lines.append(f"- {c.brand_name} ({c.domain}) — {cats} — {c.positioning}")
    return "\n".join(lines)


def _stage5_personas_block(personas: list[Persona]) -> str:
    """Render the personas block for the oversample-stage user prompt."""
    if not personas:
        return (
            "(no personas available — corpus was too sparse to ground them; "
            "falling back to profile-only voice)"
        )
    lines: list[str] = []
    for i, p in enumerate(personas, 1):
        vocab = "; ".join(f'"{v}"' for v in p.vocabulary_samples[:5]) or "(none)"
        cons = ", ".join(p.constraints[:5]) or "(none)"
        intents = ", ".join(p.typical_intents) or "(any)"
        lines.append(
            f"P{i}. {p.name}\n"
            f"    goal: {p.goal}\n"
            f"    voice samples: {vocab}\n"
            f"    typical constraints: {cons}\n"
            f"    typical intents: {intents}"
        )
    return "\n\n".join(lines)


def _stage5_corpus_block(corpus, max_per_source: int = 18) -> str:
    """Render the category-corpus block (WildChat, PAA, keyword
    suggestions) for the oversample-stage user prompt."""
    if corpus is None:
        return "(no category corpus — falling back to profile-only topic source)"

    paa = corpus.by_source("paa")
    wildchat = corpus.by_source("wildchat")
    suggestions = corpus.by_source("suggestion")

    parts: list[str] = []
    if wildchat:
        lines = [f"  - {s.text}" for s in wildchat[:max_per_source]]
        parts.append(
            "WildChat-1M samples (real ChatGPT conversations, n="
            f"{len(wildchat)}; showing top {len(lines)}):\n" + "\n".join(lines)
        )
    if paa:
        lines = [f"  - ({s.seed}) {s.text}" for s in paa[:max_per_source]]
        parts.append(
            f"People-Also-Ask (Google-measured questions, n={len(paa)}):\n" + "\n".join(lines)
        )
    if suggestions:
        lines = [f"  - {s.text}" for s in suggestions[:max_per_source]]
        parts.append(
            f"Search suggestions (Google autocomplete, n={len(suggestions)}; "
            f"showing top {len(lines)}):\n" + "\n".join(lines)
        )
    topical = (
        "\n\n".join(parts)
        if parts
        else "(no topical corpus for this vertical — draw topics from the "
        "profile + competitor signal instead)"
    )

    style_block = _stage5_style_exemplars_block(corpus)

    return (
        topical + "\n\nGuidance: draw query TOPICS from the samples above (what real "
        "users in this category ask), but DO NOT copy them verbatim. Apply "
        "the 9-shape library to remix corpus topics into well-formed queries." + style_block
    )


def _stage5_style_exemplars_block(corpus) -> str:
    """Render the topic-agnostic register exemplars, bucketed by intent.

    Distinct from the topical block above: these are real Polish user
    queries about *unrelated* subjects, included purely so the model
    imitates authentic register (casing, dropped diacritics, stacked
    constraints) rather than producing sterile textbook phrasing. The
    instruction is emphatic about NOT borrowing their topic, because the
    brand bucket in particular skews to whatever's popular in the raw
    corpus (often tech) and would otherwise contaminate the vertical.
    """
    exemplars = getattr(corpus, "style_exemplars", None) or {}
    buckets = [
        (intent, exemplars.get(intent) or [])
        for intent in ("transactional", "informational", "comparative", "brand")
    ]
    buckets = [(i, xs) for i, xs in buckets if xs]
    if not buckets:
        return ""

    lines: list[str] = [
        "\n\n## Style exemplars by intent (REAL user voice — copy texture, NOT topic)",
        "These are real user queries on UNRELATED subjects. Mimic their "
        "register: casual casing, dropped Polish diacritics, run-on phrasing, "
        "2+ stacked constraints (price/size/use-case). Do NOT borrow their "
        "subject matter — the topic must stay this brand's category.",
    ]
    for intent, xs in buckets:
        lines.append(f"\n{intent} register:")
        lines.extend(f"  - {t}" for t in xs)
    return "\n".join(lines)


async def generate_oversample(
    client: AsyncOpenAI,
    profile: BusinessProfile,
    competitors: list[CompetitorProfile],
    total: int = OVERSAMPLE_TARGET,
    keyword_signals: KeywordSignals | None = None,
    corpus=None,  # CategoryCorpus | None
    personas: list[Persona] | None = None,
) -> list[GeneratedQuery]:
    profile_json = json.dumps(
        {k: v for k, v in asdict(profile).items() if k != "summary"},
        ensure_ascii=False,
        indent=2,
    )
    user = STAGE5_USER_TEMPLATE.format(
        profile_json=profile_json,
        competitor_block=_competitor_block_for_prompt(competitors),
        keyword_seed_block=_stage5_keyword_seed_block(keyword_signals),
        personas_block=_stage5_personas_block(personas or []),
        corpus_block=_stage5_corpus_block(corpus),
        distribution_block=_stage5_distribution_targets(profile, total),
        currency=profile.currency,
        brand_name=profile.brand_name,
        language=profile.language,
        domain_terms=", ".join(profile.domain_terms) or "(none)",
        shape_library=_stage5_shape_library(),
        total=total,
    )

    data = await _llm_json(
        client,
        model=settings.query_gen_model,
        system=STAGE5_SYSTEM,
        user=user,
        temperature=0.85,
    )
    raw_list = data.get("queries", []) if isinstance(data, dict) else []
    return _coerce_queries(raw_list)


VALID_SEED_SOURCES = {"brand", "gap", "synthetic"}


def _intent_distribution(queries: list) -> dict:
    """Count generated queries by intent — small helper for tracker telemetry."""
    out: dict[str, int] = {}
    for q in queries:
        intent = getattr(q, "intent", None) or "unknown"
        out[intent] = out.get(intent, 0) + 1
    return out


def _coerce_queries(raw_list: Any) -> list[GeneratedQuery]:
    if not isinstance(raw_list, list):
        return []
    out: list[GeneratedQuery] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        intent = str(item.get("intent") or "informational").lower()
        if intent not in VALID_INTENTS:
            intent = "informational"
        length_mode = str(item.get("length_mode") or "conversational").lower()
        if length_mode not in VALID_LENGTH_MODES:
            length_mode = "conversational"
        buyer_stage = str(item.get("buyer_stage") or "problem_aware").lower()
        if buyer_stage not in VALID_BUYER_STAGES:
            buyer_stage = "problem_aware"
        try:
            shape = int(item.get("shape") or 0)
        except (TypeError, ValueError):
            shape = 0
        shape = max(0, min(9, shape))
        tags_raw = item.get("tags") or []
        tags = [str(t) for t in tags_raw if isinstance(t, (str, int))]

        # Seed attribution. Default to "synthetic" when missing or invalid —
        # the LLM occasionally drops the field. Volume/position get filled
        # in later by `_enrich_seed_metadata` against the run's keyword
        # signals; we can't look them up here without that context.
        raw_seed_source = item.get("seed_source")
        seed_source: str | None = None
        if isinstance(raw_seed_source, str):
            normalized = raw_seed_source.strip().lower()
            if normalized in VALID_SEED_SOURCES:
                seed_source = normalized
        seed_keyword = item.get("seed_keyword")
        seed_keyword = (
            str(seed_keyword).strip()
            if isinstance(seed_keyword, str) and seed_keyword.strip()
            else None
        )
        # Coerce contradictions: if the LLM said "brand"/"gap" but didn't
        # supply a keyword, drop to "synthetic". The seed bucket is only
        # meaningful when the keyword is identifiable.
        if seed_source in {"brand", "gap"} and not seed_keyword:
            seed_source = "synthetic"
            seed_keyword = None
        # And the inverse: a keyword without a source gets dropped — we
        # can't trust it without the bucket label.
        if seed_keyword and seed_source not in {"brand", "gap"}:
            seed_keyword = None

        out.append(
            GeneratedQuery(
                text=text,
                intent=intent,
                length_mode=length_mode,
                buyer_stage=buyer_stage,
                shape=shape,
                tags=tags[:3],
                seed_source=seed_source,
                seed_keyword=seed_keyword,
            )
        )
    return out


def _enrich_seed_metadata(queries: list[GeneratedQuery], signals: KeywordSignals) -> None:
    """Fill `seed_search_volume` and `seed_position` per query in place.

    Looked up by case-insensitive keyword match against the run's
    KeywordSignals — `client.keywords` for source="brand" (gives us the
    client's organic position too), `gap_keywords` for source="gap"
    (volume only; client doesn't rank). Unmatched references — typos,
    paraphrases, hallucinated keywords — leave the volume/position
    fields NULL but keep the source tag. The source bucket is the
    primary signal; volume/position are nice-to-haves for analytics.
    """
    brand_index: dict[str, RankedKeyword] = {
        kw.keyword.lower(): kw for kw in signals.client.keywords
    }
    gap_index: dict[str, RankedKeyword] = {kw.keyword.lower(): kw for kw in signals.gap_keywords}

    for q in queries:
        if not q.seed_keyword:
            continue
        key = q.seed_keyword.lower()
        if q.seed_source == "brand":
            kw = brand_index.get(key)
            if kw is not None:
                q.seed_search_volume = kw.search_volume
                q.seed_position = kw.position
        elif q.seed_source == "gap":
            kw = gap_index.get(key)
            if kw is not None:
                q.seed_search_volume = kw.search_volume
                # No position — it's a competitor's, not the client's.


def _reattach_seed_metadata(kept: list[GeneratedQuery], candidates: list[GeneratedQuery]) -> None:
    """Copy seed_* attribution from each candidate back onto the matching
    kept query by exact text match (the critique LLM may drop these
    fields when reformatting). Any
    kept query that doesn't appear in candidates (e.g. the LLM
    paraphrased mid-critique) keeps whatever seed_* the LLM happened to
    emit, falling back to whatever the coercer produced.
    """
    by_text = {c.text.strip().lower(): c for c in candidates}
    for q in kept:
        match = by_text.get(q.text.strip().lower())
        if match is None:
            continue
        q.seed_source = match.seed_source
        q.seed_keyword = match.seed_keyword
        q.seed_search_volume = match.seed_search_volume
        q.seed_position = match.seed_position


# ---------------------------------------------------------------------------
# Stage 6 — Critique & prune
# ---------------------------------------------------------------------------


STAGE6_SYSTEM = """\
You are a ruthless editor of GEO benchmark query sets. Given an oversampled
candidate list, you return the best subset that matches the requested
distribution targets exactly and contains no near-duplicates.
"""

STAGE6_USER_TEMPLATE = """\
## Business profile
{profile_json}

## Candidate queries (oversample)
{candidates_json}

## Task
Score each candidate on four axes (1-5):
  a) Realism — would a real {country} user actually type this in {language}?
  b) Relevance — does it genuinely probe this business's space?
  c) Distinctiveness — does it differ from every other kept query?
  d) Intent/shape fit — does it match its declared intent & shape?

Return the best {final} queries meeting these rules:
  - reject any with average score < 3.5
  - reject near-duplicates (pick the best phrasing)
  - enforce distribution targets as closely as possible:
      intent:        45% transactional / 20% informational / 20% comparative /
                     10% brand / 5% local (demote local to ~0% if national)
      length_mode:   60% search_like / 40% conversational
      buyer_stage:   15% problem_unaware / 55% problem_aware / 30% solution_aware
  - if the input falls short of a target bucket, keep the best from that
    bucket even at lower scores.

## Output
Return a single JSON object:

{{
  "kept": [
    {{
      "text": "...",
      "intent": "...",
      "length_mode": "...",
      "buyer_stage": "...",
      "shape": 1,
      "tags": ["..."]
    }}
  ],
  "rejected_count": <int>
}}

Exactly {final} objects in "kept". No prose, no markdown.
"""


async def critique_and_prune(
    client: AsyncOpenAI,
    profile: BusinessProfile,
    candidates: list[GeneratedQuery],
    final: int = FINAL_TARGET_DEFAULT,
) -> list[GeneratedQuery]:
    if not candidates:
        return []

    profile_json = json.dumps(
        {k: v for k, v in asdict(profile).items() if k != "summary"},
        ensure_ascii=False,
        indent=2,
    )
    candidates_json = json.dumps(
        [asdict(q) for q in candidates],
        ensure_ascii=False,
        indent=2,
    )

    user = STAGE6_USER_TEMPLATE.format(
        profile_json=profile_json,
        candidates_json=candidates_json,
        country=profile.country,
        language=profile.language,
        final=final,
    )

    data = await _llm_json(
        client,
        model=settings.query_gen_model,
        system=STAGE6_SYSTEM,
        user=user,
        temperature=0.2,
    )
    kept_raw = data.get("kept", []) if isinstance(data, dict) else []
    kept = _coerce_queries(kept_raw)
    rejected_count = data.get("rejected_count") if isinstance(data, dict) else None
    logger.info(
        "Stage 6 kept=%d (target=%d) rejected_count=%s",
        len(kept),
        final,
        rejected_count,
    )
    return kept[:final]


# ---------------------------------------------------------------------------
# Persistence — upsert the Stage 2/3 output into client_profiles
# ---------------------------------------------------------------------------


async def persist_client_profile(
    db: AsyncSession,
    profile: BusinessProfile,
    competitors: list[CompetitorProfile],
    domain: str,
) -> ClientProfileModel:
    """Upsert the profile + competitors into `client_profiles`.

    Keyed by bare domain. On re-run the row is updated in place so
    `updated_at` reflects the most recent extraction. The profile is a
    "build once, reuse forever" artifact.
    """
    clean = _clean_domain(domain)
    existing = (
        await db.execute(select(ClientProfileModel).where(ClientProfileModel.domain == clean))
    ).scalar_one_or_none()

    competitors_json = [
        {
            "brand_name": c.brand_name,
            "domain": c.domain,
            "categories": c.categories,
            "positioning": c.positioning,
        }
        for c in competitors
    ]

    if existing is None:
        row = ClientProfileModel(
            domain=clean,
            brand_name=profile.brand_name,
            language=profile.language,
            country=profile.country,
            currency=profile.currency,
            distribution=profile.distribution,
            customer_type=profile.customer_type,
            tone=profile.tone,
            summary=profile.summary,
            product_categories=profile.product_categories,
            key_products=profile.key_products,
            domain_terms=profile.domain_terms,
            seasonal_factors=profile.seasonal_factors,
            competitors=competitors_json,
        )
        db.add(row)
    else:
        existing.brand_name = profile.brand_name
        existing.language = profile.language
        existing.country = profile.country
        existing.currency = profile.currency
        existing.distribution = profile.distribution
        existing.customer_type = profile.customer_type
        existing.tone = profile.tone
        existing.summary = profile.summary
        existing.product_categories = profile.product_categories
        existing.key_products = profile.key_products
        existing.domain_terms = profile.domain_terms
        existing.seasonal_factors = profile.seasonal_factors
        existing.competitors = competitors_json
        row = existing

    await db.commit()
    await db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Orchestrator — the single entry point used by the API route
# ---------------------------------------------------------------------------


async def generate_prompt_set(
    domain: str,
    num_queries: int = FINAL_TARGET_DEFAULT,
    max_competitors: int = COMPETITORS_TO_FETCH,
    max_pages: int = SITE_PAGES_TO_FETCH,
    oversample_size: int | None = None,
    db: AsyncSession | None = None,
    location_code: int = 2840,
    language_code: str = "en",
    tracker=None,  # PipelineTracker | NoopTracker | None
) -> dict:
    """Run the full pipeline and return a serialisable dict.

    `location_code` / `language_code` drive the DataForSEO Labs lookup.
    When `db` is provided, the extracted profile is upserted into the
    `client_profiles` table.
    """
    exa = Exa(api_key=settings.exa_api_key)
    client = _chat_client()
    clean = _clean_domain(domain)

    if tracker is None:
        from app.services.pipeline_tracker import NoopTracker

        tracker = NoopTracker()

    # ---- Stage 1 — Discovery (Exa pages + Exa company DB + DFS keywords) ----
    async with tracker.stage(
        "stage_1.discovery",
        "Fetching site pages, Exa company-DB entry, and DataForSEO ranked keywords in parallel",
    ) as ev:
        site_task = discover_site_pages(exa, domain, max_pages=max_pages)
        company_task = discover_company_research(exa, clean)
        client_kw_task = fetch_client_ranked_keywords(
            clean, location_code=location_code, language_code=language_code
        )
        site_info, company_research, client_kw_report = await asyncio.gather(
            site_task, company_task, client_kw_task
        )
        company_hit = bool(company_research)
        ev.summary = (
            f"pages={len(site_info.pages)}, "
            f"company-DB={'hit' if company_hit else 'miss'}, "
            f"keywords={len(client_kw_report.keywords)}"
        )
        ev.details = {
            "pages": len(site_info.pages),
            "company_db_hit": company_hit,
            "company_text_length": len(company_research or "") if company_research else 0,
            "client_keywords_count": len(client_kw_report.keywords),
            "top_5_keywords": [
                {"keyword": k.keyword, "position": k.position, "search_volume": k.search_volume}
                for k in client_kw_report.keywords[:5]
            ],
        }
        warnings: list[str] = []
        if not company_hit and not client_kw_report.keywords:
            warnings.append(
                "Both Exa company-DB and DataForSEO came back empty — "
                "profile extraction will rely on page text only"
            )
        if not site_info.pages:
            warnings.append("Exa returned 0 pages")
        ev.warnings = warnings
    logger.info("Stage 1: %s", ev.summary)

    async with tracker.stage(
        "stage_1.competitors",
        "Discovering competitor candidates via Exa find_similar",
    ) as ev:
        comp_candidates = await discover_competitors(
            exa, site_info, max_competitors=max_competitors
        )
        ev.summary = f"{len(comp_candidates)} candidate domains from Exa"
        ev.details = {
            "candidates": [
                {"domain": c.get("domain"), "title": c.get("title", "")[:80]}
                for c in comp_candidates[:8]
            ],
        }
    logger.info("Stage 1: %s", ev.summary)

    # ---- Stage 2 — Business profile extraction (LLM) ----
    # Trust hierarchy enforced in prompt: company_research > client_keywords > pages.
    async with tracker.stage(
        "stage_2.profile",
        "Synthesizing structured profile via LLM with flipped trust hierarchy",
    ) as ev:
        profile = await extract_business_profile(
            client,
            site_info,
            company_research=company_research,
            client_keywords=client_kw_report,
        )
        ev.summary = (
            f"brand={profile.brand_name}, language={profile.language}, "
            f"country={profile.country}, categories={len(profile.product_categories)}"
        )
        ev.details = {
            "brand_name": profile.brand_name,
            "language": profile.language,
            "country": profile.country,
            "distribution": profile.distribution,
            "customer_type": profile.customer_type,
            "categories_count": len(profile.product_categories),
            "domain_terms_count": len(profile.domain_terms),
            "product_categories": profile.product_categories[:8],
        }
    logger.info("Stage 2: %s", ev.summary)

    # ---- Stage 3 — Competitor profile extraction (LLM) ----
    async with tracker.stage(
        "stage_3.competitors_llm",
        "Filtering and structuring competitor list via LLM",
    ) as ev:
        competitors = await extract_competitor_profiles(
            client, profile, comp_candidates, target=max_competitors
        )
        ev.summary = f"kept {len(competitors)} competitors after LLM cleanup"
        ev.details = {
            "competitors": [{"name": c.brand_name, "domain": c.domain} for c in competitors],
        }
    logger.info("Stage 3: %s", ev.summary)

    # Persist the profile + competitors immediately so the artifact
    # survives even if later stages fail.
    persisted_id: int | None = None
    if db is not None:
        try:
            row = await persist_client_profile(db, profile, competitors, site_info.domain)
            persisted_id = row.id
            logger.info("Persisted client_profile id=%s", persisted_id)
        except Exception:
            logger.exception("Failed to persist client_profile; continuing")

    # ---- Stage 4 — Keyword signals (DataForSEO Labs) ----
    from app.database import async_session
    from app.services.corpus import EmbeddingsClient, build_category_corpus
    from app.services.corpus_store import PgCorpusStore

    # Pick seed terms for PAA + suggestions: prefer ranked-keyword text
    # (real Google demand) over profile.domain_terms (LLM-extracted),
    # falling back to profile when DFS has nothing.
    if client_kw_report.keywords:
        corpus_seeds = [k.keyword for k in client_kw_report.keywords[:10]]
    else:
        corpus_seeds = (profile.domain_terms or profile.product_categories)[:10]

    profile_terms_for_filter = (
        profile.domain_terms + profile.product_categories + profile.key_products
    )

    keyword_signals_task = discover_keyword_signals(
        site_info.domain,
        [c.domain for c in competitors],
        location_code=location_code,
        language_code=language_code,
        client_report=client_kw_report,
    )
    corpus_task = build_category_corpus(
        profile_terms=profile_terms_for_filter,
        seed_terms=corpus_seeds,
        location_code=location_code,
        language_code=language_code,
        embeddings_client=cast(EmbeddingsClient, _embeddings_client()),
        store=PgCorpusStore(async_session),
    )
    async with tracker.stage(
        "stage_4.signals_and_corpus",
        "Fetching competitor keyword data + building category corpus (WildChat + PAA + suggestions) in parallel",
    ) as ev:
        keyword_signals, corpus = await asyncio.gather(keyword_signals_task, corpus_task)
        ev.summary = (
            f"keyword_signals: client={len(keyword_signals.client.keywords)} "
            f"competitors={len(keyword_signals.competitors)} "
            f"gap={len(keyword_signals.gap_keywords)}"
            f"  ·  corpus: wildchat={corpus.counts.get('wildchat', 0)} "
            f"paa={corpus.counts.get('paa', 0)} suggestion={corpus.counts.get('suggestion', 0)}"
        )
        ev.details = {
            "keyword_signals": {
                "client_keywords_count": len(keyword_signals.client.keywords),
                "competitor_count": len(keyword_signals.competitors),
                "gap_keywords_count": len(keyword_signals.gap_keywords),
            },
            "corpus": {
                "counts": corpus.counts,
                "seed_terms": corpus.seed_terms,
            },
        }
        ev.warnings = list(corpus.warnings)
    logger.info("Stage 4 + Stage 2 corpus: %s", ev.summary)

    # ---- Persona synthesis from corpus ----
    async with tracker.stage(
        "stage_5.personas",
        "Synthesizing buyer personas grounded in category corpus",
    ) as ev:
        personas = await synthesize_personas(client, profile, corpus)
        ev.summary = f"{len(personas)} personas synthesized"
        ev.details = {
            "personas": [
                {
                    "name": p.name,
                    "goal": p.goal,
                    "vocabulary_samples_count": len(p.vocabulary_samples),
                }
                for p in personas
            ],
        }
        if not personas:
            ev.warnings = [
                "No personas synthesized — corpus may have been too sparse "
                "for the LLM to ground them."
            ]
    logger.info("Stage 5 personas: %s", ev.summary)
    logger.info(
        "Stage 4: client_kws=%d gap_kws=%d (across %d competitors)",
        len(keyword_signals.client.keywords),
        len(keyword_signals.gap_keywords),
        len(keyword_signals.competitors),
    )

    # ---- Stage 5 — Query oversample (LLM) ----
    # Scale oversample to the requested final count: full target for
    # large runs, proportional shrink for small ones.
    if oversample_size is None:
        if num_queries >= 40:
            oversample_size = max(OVERSAMPLE_TARGET, num_queries + 20)
        else:
            oversample_size = max(num_queries + 3, num_queries * 2)
    async with tracker.stage(
        "stage_6.oversample",
        f"Generating {oversample_size} candidate queries (LLM, temp=0.85)",
    ) as ev:
        candidates = await generate_oversample(
            client,
            profile,
            competitors,
            total=oversample_size,
            keyword_signals=keyword_signals,
            corpus=corpus,
            personas=personas,
        )
        # Join seed_keyword volume/position back from KeywordSignals.
        _enrich_seed_metadata(candidates, keyword_signals)
        ev.summary = f"{len(candidates)} candidate queries generated"
        ev.details = {
            "candidate_count": len(candidates),
            "intent_distribution": _intent_distribution(candidates),
        }
    logger.info("Stage 6 oversample: %s", ev.summary)

    # ---- Stage 6 — Critique & prune (LLM) ----
    async with tracker.stage(
        "stage_7.critique",
        f"Critiquing and pruning to top {num_queries} queries (LLM, temp=0.20)",
    ) as ev:
        final_queries = await critique_and_prune(client, profile, candidates, final=num_queries)
        _reattach_seed_metadata(final_queries, candidates)
        ev.summary = f"kept {len(final_queries)} final queries"
        ev.details = {
            "final_count": len(final_queries),
            "intent_distribution": _intent_distribution(final_queries),
            "rejected_count": len(candidates) - len(final_queries),
        }
    logger.info("Stage 7 critique: %s", ev.summary)

    # If critique returns fewer than requested, top up from the oversample.
    if len(final_queries) < num_queries and candidates:
        seen = {q.text for q in final_queries}
        for q in candidates:
            if len(final_queries) >= num_queries:
                break
            if q.text not in seen:
                final_queries.append(q)
                seen.add(q.text)

    return {
        "domain": site_info.domain,
        "pages_found": len(site_info.pages),
        "client_profile_id": persisted_id,
        "profile": {
            "brand_name": profile.brand_name,
            "language": profile.language,
            "country": profile.country,
            "currency": profile.currency,
            "distribution": profile.distribution,
            "customer_type": profile.customer_type,
            "tone": profile.tone,
            "product_categories": profile.product_categories,
            "key_products": profile.key_products,
            "domain_terms": profile.domain_terms,
            "seasonal_factors": profile.seasonal_factors,
            "summary": profile.summary,
        },
        "competitors": [{"name": c.brand_name, "domain": c.domain} for c in competitors],
        "personas": [
            {
                "name": p.name,
                "goal": p.goal,
                "vocabulary_samples": p.vocabulary_samples,
                "constraints": p.constraints,
                "typical_intents": p.typical_intents,
            }
            for p in personas
        ],
        "corpus": {
            "counts": corpus.counts,
            "seed_terms": corpus.seed_terms,
            "warnings": corpus.warnings,
            "samples": [
                {
                    "text": s.text,
                    "source": s.source,
                    "seed": s.seed,
                    "intent": s.intent,
                    "length_mode": s.length_mode,
                    "score": s.score,
                }
                for s in corpus.samples
            ],
        },
        "keyword_signals": _serialize_keyword_signals(keyword_signals),
        "queries": [
            {
                "text": q.text,
                "intent": q.intent,
                "length_mode": q.length_mode,
                "buyer_stage": q.buyer_stage,
                "shape": q.shape,
                "tags": q.tags,
                "seed_source": q.seed_source,
                "seed_keyword": q.seed_keyword,
                "seed_search_volume": q.seed_search_volume,
                "seed_position": q.seed_position,
            }
            for q in final_queries
        ],
    }


def _serialize_keyword_signals(s: KeywordSignals) -> dict:
    def _kw_dict(k: RankedKeyword) -> dict:
        return {
            "keyword": k.keyword,
            "position": k.position,
            "search_volume": k.search_volume,
            "keyword_difficulty": k.keyword_difficulty,
            "url": k.url,
        }

    return {
        "client_domain": s.client.domain,
        "location_code": s.client.location_code,
        "language_code": s.client.language_code,
        "client_keywords": [_kw_dict(k) for k in s.client.keywords],
        "gap_keywords": [_kw_dict(k) for k in s.gap_keywords],
        "competitor_summary": [
            {"domain": r.domain, "keywords_found": len(r.keywords)} for r in s.competitors
        ],
    }
