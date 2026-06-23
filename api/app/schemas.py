from datetime import datetime

from pydantic import BaseModel

from app.models import IntentType, RunStatus, Sentiment
from app.services.prompt_generator.base import (
    BuyerStage,
    IntentName,
    LengthMode,
    SeedSource,
)


# --- Prompts ---


class PromptCreate(BaseModel):
    text: str
    intent: IntentType
    tags: list[str] = []
    enabled: bool = True
    seed_source: SeedSource | None = None
    seed_keyword: str | None = None
    seed_search_volume: int | None = None
    seed_position: int | None = None


class PromptOut(BaseModel):
    id: int
    text: str
    intent: IntentType
    tags: list[str]
    enabled: bool
    created_at: datetime
    seed_source: SeedSource | None = None
    seed_keyword: str | None = None
    seed_search_volume: int | None = None
    seed_position: int | None = None

    model_config = {"from_attributes": True}


# --- Brands ---


class BrandCreate(BaseModel):
    name: str
    domains: list[str] = []
    aliases: list[str] = []
    is_self: bool = False
    country_code: str = "US"
    language_code: str = "en"


class BrandUpdate(BaseModel):
    name: str | None = None
    domains: list[str] | None = None
    aliases: list[str] | None = None
    is_self: bool | None = None
    country_code: str | None = None
    language_code: str | None = None


class BrandOut(BaseModel):
    id: int
    name: str
    domains: list[str]
    aliases: list[str]
    is_self: bool
    country_code: str
    country_name: str
    language_code: str
    language_name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GeoCountryOut(BaseModel):
    country_code: str
    name: str
    default_language_code: str


class GeoLanguageOut(BaseModel):
    code: str
    name: str


class GeoOptionsOut(BaseModel):
    countries: list[GeoCountryOut]
    languages: list[GeoLanguageOut]


# --- Sources ---


class SourceStatus(BaseModel):
    id: str
    display_name: str
    configured: bool
    credential_hint: str


# --- Runs ---


class RunOut(BaseModel):
    id: int
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    total_cost: float | None

    model_config = {"from_attributes": True}


# --- Responses ---


class ResponseOut(BaseModel):
    id: int
    prompt_id: int
    run_id: int
    source: str
    source_name: str
    text: str
    tokens_used: int | None
    latency_ms: int | None
    source_urls: list[str] | None
    search_queries: list[str] | None
    error_kind: str | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Analysis ---


class AnalysisOut(BaseModel):
    id: int
    response_id: int
    brand_id: int
    brand_found: bool
    sentiment: Sentiment
    recommended: bool
    link_present: bool
    competitors: dict | None
    our_pages: dict | None

    model_config = {"from_attributes": True}


# --- Analytics ---


class VisibilityMetrics(BaseModel):
    total_responses: int
    brand_mentioned: int
    visibility_rate: float
    recommendation_rate: float
    citation_rate: float
    link_rate: float


class CompetitorShare(BaseModel):
    brand_id: int
    brand_name: str
    is_self: bool
    mention_count: int
    share_of_voice: float


class CitationStat(BaseModel):
    # citation_count = number of responses citing this host (not raw URLs).

    domain: str
    citation_count: int
    share: float
    brand_id: int | None
    brand_name: str | None
    is_self: bool


class SentimentCounts(BaseModel):
    positive: int
    neutral: int
    negative: int


class RunSummary(BaseModel):
    run_id: int
    started_at: datetime
    completed_at: datetime | None
    status: RunStatus
    total_cost: float | None
    metrics: VisibilityMetrics
    sentiment: SentimentCounts


class SourceBreakdown(BaseModel):
    source: str
    source_name: str
    metrics: VisibilityMetrics
    sentiment: SentimentCounts


class PromptPerformance(BaseModel):
    prompt_id: int
    text: str
    intent: IntentType
    tags: list[str]
    enabled: bool
    total_responses: int
    mentioned_count: int
    recommended_count: int
    hit_rate: float
    last_run_status: str  # "mentioned" | "missing" | "no_data"

    sentiment: SentimentCounts


class PromptSourceStats(BaseModel):
    source: str
    source_name: str
    total_responses: int
    mentioned_count: int
    recommended_count: int
    hit_rate: float


class PromptRunPoint(BaseModel):
    run_id: int
    started_at: datetime
    total_responses: int
    mentioned_count: int
    hit_rate: float


class PromptCompetitorStat(BaseModel):
    brand_id: int
    brand_name: str
    mention_count: int


class PromptRecentResponse(BaseModel):
    response_id: int
    run_id: int
    source: str
    source_name: str
    created_at: datetime
    snippet: str
    mentioned: bool
    recommended: bool
    sentiment: Sentiment
    error_kind: str | None


class PromptDetail(BaseModel):
    id: int
    text: str
    intent: IntentType
    tags: list[str]
    enabled: bool
    created_at: datetime
    metrics: VisibilityMetrics
    per_source: list[PromptSourceStats]
    trend: list[PromptRunPoint]
    competitors: list[PromptCompetitorStat]
    recent_responses: list[PromptRecentResponse]


class TopicCompetitor(BaseModel):
    brand_id: int
    brand_name: str
    mention_count: int


class GraphNode(BaseModel):
    id: str  # e.g. "topic:balcony" / "brand:42"
    kind: str  # "topic" | "brand"
    label: str
    weight: int  # > 0 means rendered
    is_self: bool = False  # only meaningful for kind="brand"


class GraphEdge(BaseModel):
    # Logically undirected; source/target satisfy graph-library expectations.
    source: str
    target: str
    kind: str  # "topic_brand"
    weight: int


class TopicGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class TopicStat(BaseModel):
    # share_of_voice = self / total_brand_mentions (within cluster);
    # hit_rate = mentioned / responses. The two diverge intentionally.

    topic: str
    prompt_count: int
    total_responses: int
    mentioned_count: int  # self brand mention count
    recommended_count: int
    hit_rate: float  # mentioned_count / total_responses
    recommendation_rate: float
    sentiment: SentimentCounts
    share_of_voice: float  # mentioned_count / total_brand_mentions
    total_brand_mentions: int  # across all tracked brands
    top_competitor: TopicCompetitor | None


class BrandAnalysis(BaseModel):
    brand_id: int
    brand_name: str
    is_self: bool
    brand_found: bool
    sentiment: Sentiment
    recommended: bool
    link_present: bool
    our_pages: list[str] | None
    competitors: list[dict] | None

    model_config = {"from_attributes": True}


class ShoppingProductOut(BaseModel):
    position: int
    title: str
    price: str | None = None
    rating: float | None = None
    reviews: int | None = None
    image: str | None = None
    link: str | None = None
    description: str | None = None
    tag: str | None = None
    brand_id: int | None = None
    brand_name: str | None = None
    is_self: bool = False


class ResponseDetail(BaseModel):
    id: int
    run_id: int
    prompt_id: int
    prompt_text: str
    prompt_intent: IntentType
    source: str
    source_name: str
    text: str
    tokens_used: int | None
    latency_ms: int | None
    source_urls: list[str] | None
    search_queries: list[str] | None
    shopping_products: list[ShoppingProductOut] | None = None
    error_kind: str | None
    error_message: str | None
    created_at: datetime
    analyses: list[BrandAnalysis]


class ShoppingProductStat(BaseModel):
    title: str
    brand_id: int | None
    brand_name: str | None
    is_self: bool
    appearances: int
    avg_position: float
    best_position: int
    avg_rating: float | None
    sample_price: str | None


class ShoppingCompetitorShare(BaseModel):
    brand_id: int
    brand_name: str
    appearances: int
    share_of_voice: float


class ShoppingVisibility(BaseModel):
    # carousel_rate = how often a shopping carousel rendered at all;
    # share_of_voice = self product slots / all tracked-brand slots.
    total_responses: int
    carousel_responses: int
    carousel_rate: float
    self_appearances: int
    self_appearance_rate: float
    share_of_voice: float
    avg_self_position: float | None
    competitors: list[ShoppingCompetitorShare]
    products: list[ShoppingProductStat]


# --- Query Generation ---


class BrandComparisonEntry(BaseModel):
    brand_id: int
    brand_name: str
    is_self: bool
    metrics: VisibilityMetrics
    sentiment: SentimentCounts


class BrandComparison(BaseModel):
    # Brand-intent prompts excluded — everyone gets their own branded boost.
    run_id: int | None
    total_responses: int
    brands: list[BrandComparisonEntry]


class FunnelStage(BaseModel):
    # Stages don't strictly nest; `rate` is independent count/total.
    label: str
    count: int
    rate: float


class RunScheduleOut(BaseModel):
    brand_id: int
    enabled: bool
    interval_hours: int
    last_triggered_at: datetime | None
    next_run_at: datetime | None


class RunScheduleUpdate(BaseModel):
    enabled: bool | None = None
    interval_hours: int | None = None


class SearchTermStat(BaseModel):
    # term: lower-cased, whitespace-collapsed grounding query.
    # prompt_count: distinct prompts that triggered it.
    term: str
    count: int
    prompt_count: int
    source_count: int


class CompetitorOpportunity(BaseModel):
    brand_id: int
    brand_name: str
    mention_count: int
    recommended_count: int


class PromptRecommendation(BaseModel):
    # opportunity_score = competitor_visibility * (1 - self_hit_rate).

    prompt_id: int
    prompt_text: str
    intent: IntentType
    self_hit_rate: float
    self_mentioned_count: int
    self_total_responses: int
    top_competitor: CompetitorOpportunity
    other_competitors: list[CompetitorOpportunity]
    cited_domains: list[str]
    triggered_search_queries: list[str]
    opportunity_score: float
    recommendation_kind: (
        str  # "get_cited" | "publish_comparison" | "target_query" | "publish_content"
    )
    recommendation_text: str


class FunnelMetrics(BaseModel):
    # discovery → citation → mention → recommendation → link.
    # Brand-intent prompts excluded by default (they'd fire every stage).

    total_responses: int
    discovery: FunnelStage
    citation: FunnelStage
    mention: FunnelStage
    recommendation: FunnelStage
    link: FunnelStage


# --- Query Generation ---


class GeneratePromptsRequest(BaseModel):
    url: str
    num_queries: int = 50
    # ISO 3166-1 alpha-2 country code and ISO 639-1 language code. If
    # omitted, the endpoint resolves them by matching the URL against
    # an existing Brand row, then falls back to ("US", "en").
    country_code: str | None = None
    language_code: str | None = None


class GeneratedCompetitor(BaseModel):
    name: str
    domain: str


class GeneratedQueryOut(BaseModel):
    text: str
    intent: IntentName
    tags: list[str] = []
    # Generator metadata. All optional — persisted prompts may predate
    # these fields.
    length_mode: LengthMode | None = None
    buyer_stage: BuyerStage | None = None
    shape: int | None = None
    seed_source: SeedSource | None = None
    seed_keyword: str | None = None
    seed_search_volume: int | None = None
    seed_position: int | None = None


class GeneratedClientProfile(BaseModel):
    brand_name: str
    language: str
    country: str
    currency: str
    distribution: str
    customer_type: str
    product_categories: list[str] = []
    summary: str = ""


class GeneratePromptsResponse(BaseModel):
    domain: str
    pages_found: int
    client_profile_id: int | None = None
    profile: GeneratedClientProfile | None = None
    competitors: list[GeneratedCompetitor]
    queries: list[GeneratedQueryOut]


# --- Audit report ---


class ReportPeriod(BaseModel):
    kind: str  # "run" | "range"
    run_id: int | None
    from_date: datetime
    to_date: datetime
    run_count: int


class ReportBrand(BaseModel):
    id: int
    name: str
    domain: str | None
    is_self: bool


class ReportBrandRow(BaseModel):
    brand_id: int
    brand_name: str
    is_self: bool
    metrics: VisibilityMetrics
    sentiment: SentimentCounts


class ReportPromptSentimentRow(BaseModel):
    # dominant_sentiment: worst-tone-wins.
    prompt_id: int
    text: str
    dominant_sentiment: str  # "positive" | "neutral" | "negative" | "not_mentioned"
    recommended_count: int
    total_responses: int
    sentiment_counts: SentimentCounts


class ReportBrandAwareness(BaseModel):
    total_brand_prompts: int
    total_responses: int
    sentiment_counts: SentimentCounts
    recommendation_rate: float
    negative: list[ReportPromptSentimentRow]
    neutral: list[ReportPromptSentimentRow]
    positive: list[ReportPromptSentimentRow]
    not_mentioned: list[ReportPromptSentimentRow]


class ReportSampleResponse(BaseModel):
    # Selection prioritises one negative + one recommendation + one
    # citation-rich sample when available.

    response_id: int
    run_id: int
    source: str
    source_name: str
    prompt_text: str
    prompt_intent: IntentType
    response_text: str  # full text — the report renders a clamp/truncation
    brand_found: bool
    sentiment: Sentiment
    recommended: bool
    cited_domains: list[str]


class ReportPayload(BaseModel):
    # tier "simple": KPIs + brand awareness + per-source + citations +
    # competitor visibility + samples. tier "advanced": adds prompt
    # recommendations, citation gap, search-term analysis.

    period: ReportPeriod
    self_brand: ReportBrand
    competitors: list[ReportBrand]
    language: str  # ISO 639-1 ("en", "pl", ...)
    tier: str  # "simple" | "advanced"

    # Headline KPIs (over the window) + delta vs prior window of same length
    metrics: VisibilityMetrics
    sentiment: SentimentCounts
    metrics_prior: VisibilityMetrics | None
    sentiment_prior: SentimentCounts | None

    # Simple-tier sections — always populated.
    brand_awareness: ReportBrandAwareness
    by_source: list[SourceBreakdown]
    citations: list[CitationStat]
    competitor_visibility: list[ReportBrandRow]
    samples: list[ReportSampleResponse]

    # Advanced-tier sections — populated only when tier == "advanced".
    # Empty / None on simple tier so the schema stays uniform.
    recommendations: list[PromptRecommendation] = []
    citation_gap: list[CitationStat] = []
    search_terms: list[SearchTermStat] = []
