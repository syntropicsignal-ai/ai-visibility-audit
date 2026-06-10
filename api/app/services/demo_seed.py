"""Deterministic fictional dataset for first-run exploration without
API keys. Guard rails in seed_demo / clear_demo prevent merging into
or deleting real data."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Analysis,
    Brand,
    ClientProfile,
    GeneratorRun,
    IntentType,
    PipelineRun,
    Prompt,
    Response,
    Run,
    RunSchedule,
    RunStatus,
    Sentiment,
)

# `clear_demo` keys off these: if every Brand.domains entry is in
# DEMO_BRAND_DOMAINS we know the DB is demo-only and safe to wipe.
DEMO_SELF_DOMAIN = "vellar.com"
DEMO_BRAND_DOMAINS = frozenset(
    {
        "vellar.com",
        "frostpeak.com",
        "aerowool.com",
        "basecampmerino.com",
        "tundrathread.com",
    }
)

_SEED = 4071


@dataclass(frozen=True, slots=True)
class _BrandSpec:
    name: str
    domain: str
    aliases: tuple[str, ...]
    is_self: bool
    # Baseline share of non-brand responses that mention this brand, in
    # the FIRST run. Self brand trends upward run-over-run; competitors
    # stay roughly flat. Tuned so the competitor leaderboard + share-of-
    # voice read like a real market (one strong rival, a long tail).
    base_visibility: float


_BRANDS: tuple[_BrandSpec, ...] = (
    _BrandSpec("Vellar", "vellar.com", ("Vellar", "Vellar Wool"), True, 0.38),
    _BrandSpec("Frostpeak", "frostpeak.com", ("Frostpeak",), False, 0.55),
    _BrandSpec("Aerowool", "aerowool.com", ("Aerowool",), False, 0.34),
    _BrandSpec(
        "Basecamp Merino", "basecampmerino.com", ("Basecamp Merino", "Basecamp"), False, 0.22
    ),
    _BrandSpec("Tundra Thread", "tundrathread.com", ("Tundra Thread", "Tundra"), False, 0.13),
)


@dataclass(frozen=True, slots=True)
class _PromptSpec:
    text: str
    intent: IntentType
    tags: tuple[str, ...]


# Demo prompts, grouped by intent.
_PROMPTS: tuple[_PromptSpec, ...] = (
    # transactional (7)
    _PromptSpec(
        "merino wool base layer men medium under $90",
        IntentType.transactional,
        ("base-layer", "mens"),
    ),
    _PromptSpec(
        "best merino running socks for marathon training",
        IntentType.transactional,
        ("socks", "running"),
    ),
    _PromptSpec(
        "lightweight merino hoodie for travel", IntentType.transactional, ("hoodie", "travel")
    ),
    _PromptSpec(
        "merino wool t-shirt anti odor for hiking", IntentType.transactional, ("tshirt", "hiking")
    ),
    _PromptSpec("women's merino leggings 250gsm", IntentType.transactional, ("leggings", "womens")),
    _PromptSpec(
        "merino beanie mulesing-free wool",
        IntentType.transactional,
        ("accessories", "sustainability"),
    ),
    _PromptSpec(
        "buy merino long sleeve crew black large", IntentType.transactional, ("base-layer", "mens")
    ),
    # informational (3)
    _PromptSpec("how to wash merino wool without shrinking", IntentType.informational, ("care",)),
    _PromptSpec(
        "is merino wool good for hot weather", IntentType.informational, ("fabric", "education")
    ),
    _PromptSpec(
        "what gsm merino is best for everyday wear",
        IntentType.informational,
        ("fabric", "education"),
    ),
    # comparative (3)
    _PromptSpec(
        "vellar vs frostpeak merino base layer",
        IntentType.comparative,
        ("comparison", "base-layer"),
    ),
    _PromptSpec(
        "merino vs synthetic for trail running", IntentType.comparative, ("comparison", "running")
    ),
    _PromptSpec("best merino activewear brands compared", IntentType.comparative, ("comparison",)),
    # brand (2)
    _PromptSpec("vellar merino reviews", IntentType.brand, ("reputation",)),
    _PromptSpec(
        "is vellar wool ethically sourced", IntentType.brand, ("reputation", "sustainability")
    ),
    # local (1)
    _PromptSpec("merino wool store portland", IntentType.local, ("retail", "local")),
)

_SOURCES = ("dataforseo", "brightdata_chatgpt", "brightdata_google_ai_mode")

_NEUTRAL_CITATIONS = (
    "outdoorgearlab.com",
    "wirecutter.com",
    "reddit.com",
    "switchbacktravel.com",
    "rei.com",
)

_SOURCE_FLAVOUR = {
    "dataforseo": "Based on top sources, ",
    "brightdata_chatgpt": "Here's a quick rundown — ",
    "brightdata_google_ai_mode": "",
}


def _answer_text(prompt: _PromptSpec, source: str, mentioned: list[str], top: str | None) -> str:
    lead = _SOURCE_FLAVOUR.get(source, "")
    names = mentioned or ["several merino brands"]
    joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" and {names[-1]}"
    if prompt.intent is IntentType.comparative:
        body = (
            f"for {prompt.text}, {joined} come up most often. "
            f"{top or names[0]} tends to win on next-to-skin softness and "
            f"odour resistance, while the others compete on price and weight."
        )
    elif prompt.intent is IntentType.informational:
        body = (
            f"{prompt.text.capitalize()}? The short answer: yes, with care. "
            f"Guides from {joined} cover wash temperature, GSM choice and "
            f"layering — merino regulates temperature across a wide range."
        )
    elif prompt.intent is IntentType.brand:
        body = (
            f"{names[0]} is generally well regarded — reviewers highlight "
            f"durability and traceable, mulesing-free wool, with occasional "
            f"notes on price and limited size availability."
        )
    elif prompt.intent is IntentType.local:
        body = (
            f"For {prompt.text}, a few specialty outdoor retailers stock "
            f"{joined}; {top or names[0]} also ships direct with free returns."
        )
    else:  # transactional
        body = (
            f'For "{prompt.text}", strong picks include {joined}. '
            f"{top or names[0]} is the most recommended for value and a "
            f"100-day return window; check current sizing before ordering."
        )
    return (lead + body).strip()


def _grounding_queries(prompt: _PromptSpec, mention_self: bool) -> list[str]:
    qs = [prompt.text]
    if prompt.intent is IntentType.transactional:
        qs.append(prompt.text + " review")
    if mention_self:
        qs.append("Vellar merino " + prompt.tags[0])
    return qs[:3]


@dataclass(frozen=True, slots=True)
class SeedSummary:
    brands: int
    prompts: int
    runs: int
    responses: int
    analyses: int


async def _count(session: AsyncSession, model) -> int:
    return int((await session.execute(select(func.count()).select_from(model))).scalar() or 0)


async def has_any_data(session: AsyncSession) -> bool:
    return (await _count(session, Brand)) > 0 or (await _count(session, Run)) > 0


async def is_demo_data(session: AsyncSession) -> bool:
    # clear_demo's safety interlock: refuses unless every brand carries
    # a known demo domain.
    brands = list((await session.execute(select(Brand))).scalars().all())
    if not brands:
        return False
    for b in brands:
        for d in b.domains or []:
            if d not in DEMO_BRAND_DOMAINS:
                return False
    return any(b.is_self and DEMO_SELF_DOMAIN in (b.domains or []) for b in brands)


async def demo_status(session: AsyncSession) -> dict:
    has_data = await has_any_data(session)
    return {
        "has_data": has_data,
        "is_demo": await is_demo_data(session) if has_data else False,
        "self_domain": DEMO_SELF_DOMAIN,
    }


async def seed_demo(session: AsyncSession) -> SeedSummary:
    # Refuses if any brand/run exists; the demo only ever lands in a
    # pristine DB.
    if await has_any_data(session):
        raise ValueError(
            "Database already has brands or runs — refusing to seed demo data. "
            "Use the clear endpoint first if this is a demo install."
        )

    rng = random.Random(_SEED)
    now = datetime.now(timezone.utc)

    # --- Brands ---
    brands: dict[str, Brand] = {}
    for spec in _BRANDS:
        b = Brand(
            name=spec.name,
            domains=[spec.domain],
            aliases=list(spec.aliases),
            is_self=spec.is_self,
            country_code="US",
            country_name="United States",
            language_code="en",
            language_name="English",
        )
        session.add(b)
        brands[spec.name] = b
    await session.flush()

    prompts: list[Prompt] = []
    for spec in _PROMPTS:
        p = Prompt(text=spec.text, intent=spec.intent, tags=list(spec.tags), enabled=True)
        session.add(p)
        prompts.append(p)
    await session.flush()

    # Self-visibility trends upward across the 3 runs; competitors flat.
    run_offsets_days = (42, 21, 3)
    self_trend = (0.0, 0.08, 0.16)
    runs: list[Run] = []
    for off in run_offsets_days:
        started = now - timedelta(days=off, hours=2)
        r = Run(
            status=RunStatus.completed,
            started_at=started,
            completed_at=started + timedelta(minutes=7),
            total_cost=round(rng.uniform(0.9, 1.6), 4),
        )
        session.add(r)
        runs.append(r)
    await session.flush()

    n_responses = 0
    n_analyses = 0

    for run_idx, run in enumerate(runs):
        lift = self_trend[run_idx]
        for spec_idx, (spec, prompt) in enumerate(zip(_PROMPTS, prompts)):
            is_brand_intent = spec.intent is IntentType.brand
            for source in _SOURCES:
                # ~4% failure rate to keep error states non-empty.
                roll = rng.random()
                if roll < 0.04:
                    err_kind, err_msg = (
                        ("no_ai_overview", "Google did not render an AI Overview")
                        if source == "dataforseo"
                        else ("rate_limited", "Provider rate limited the request")
                    )
                    resp = Response(
                        prompt_id=prompt.id,
                        run_id=run.id,
                        source=source,
                        text="",
                        error_kind=err_kind,
                        error_message=err_msg,
                        created_at=run.started_at + timedelta(seconds=spec_idx * 5),
                    )
                    session.add(resp)
                    n_responses += 1
                    continue

                # Brand-intent prompts always mention the self brand.
                mentioned: list[str] = []
                for bspec in _BRANDS:
                    if bspec.is_self:
                        prob = min(0.95, bspec.base_visibility + lift)
                        if is_brand_intent:
                            prob = 0.98
                    else:
                        prob = bspec.base_visibility + rng.uniform(-0.08, 0.08)
                    if rng.random() < prob:
                        mentioned.append(bspec.name)
                if not mentioned:
                    mentioned.append("Frostpeak")

                rng.shuffle(mentioned)
                top = mentioned[0]
                self_mentioned = "Vellar" in mentioned

                cited: list[str] = []
                for nm in mentioned:
                    dom = next(b.domain for b in _BRANDS if b.name == nm)
                    cited.append(f"https://www.{dom}/collections/merino")
                for nd in rng.sample(_NEUTRAL_CITATIONS, k=rng.randint(1, 3)):
                    cited.append(f"https://{nd}/best-merino-base-layers")

                resp = Response(
                    prompt_id=prompt.id,
                    run_id=run.id,
                    source=source,
                    text=_answer_text(spec, source, mentioned, top),
                    tokens_used=rng.randint(420, 1300),
                    input_tokens=rng.randint(120, 380),
                    output_tokens=rng.randint(260, 950),
                    latency_ms=rng.randint(2200, 9000),
                    source_urls=cited,
                    search_queries=_grounding_queries(spec, self_mentioned),
                    created_at=run.started_at + timedelta(seconds=spec_idx * 5),
                )
                session.add(resp)
                await session.flush()
                n_responses += 1

                for pos, bspec in enumerate(_BRANDS):
                    found = bspec.name in mentioned
                    if found:
                        rank = mentioned.index(bspec.name) + 1
                        if bspec.is_self:
                            sent = rng.choices(
                                [Sentiment.positive, Sentiment.neutral, Sentiment.negative],
                                weights=[0.62, 0.28, 0.10],
                            )[0]
                            recommended = rank == 1 and rng.random() < 0.7
                            link = rng.random() < 0.45
                            our_pages = (
                                [f"https://www.{DEMO_SELF_DOMAIN}/collections/merino"]
                                if rng.random() < 0.5
                                else None
                            )
                        else:
                            sent = rng.choices(
                                [Sentiment.positive, Sentiment.neutral, Sentiment.negative],
                                weights=[0.5, 0.42, 0.08],
                            )[0]
                            recommended = rank == 1 and rng.random() < 0.5
                            link = rng.random() < 0.3
                            our_pages = None
                    else:
                        sent = Sentiment.not_mentioned
                        recommended = False
                        link = False
                        our_pages = None

                    competitors_blob = [
                        {
                            "name": m,
                            "url": f"https://www.{next(b.domain for b in _BRANDS if b.name == m)}",
                        }
                        for m in mentioned
                        if m != bspec.name
                    ] or None

                    session.add(
                        Analysis(
                            response_id=resp.id,
                            brand_id=brands[bspec.name].id,
                            brand_found=found,
                            sentiment=sent,
                            recommended=recommended,
                            link_present=link,
                            competitors=competitors_blob,
                            our_pages=our_pages,
                        )
                    )
                    n_analyses += 1

    await session.commit()
    return SeedSummary(
        brands=len(_BRANDS),
        prompts=len(_PROMPTS),
        runs=len(runs),
        responses=n_responses,
        analyses=n_analyses,
    )


async def clear_demo(session: AsyncSession) -> dict:
    # Refuses unless every brand is a known demo brand.
    if not await has_any_data(session):
        return {"cleared": False, "reason": "database is already empty"}
    if not await is_demo_data(session):
        raise ValueError(
            "Database contains non-demo brands — refusing to clear. "
            "Delete real data manually if this is intentional."
        )

    # FK-safe order: analyses → responses → runs/prompts → schedules → brands.
    for model in (
        Analysis,
        Response,
        RunSchedule,
        Run,
        Prompt,
        Brand,
        GeneratorRun,
        PipelineRun,
        ClientProfile,
    ):
        for row in (await session.execute(select(model))).scalars().all():
            await session.delete(row)
    await session.commit()
    return {"cleared": True}
