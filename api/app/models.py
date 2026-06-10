import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class IntentType(str, enum.Enum):
    transactional = "transactional"
    informational = "informational"
    comparative = "comparative"
    brand = "brand"
    local = "local"


class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Sentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    not_mentioned = "not_mentioned"


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[IntentType] = mapped_column(Enum(IntentType), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # seed_source: 'brand' | 'gap' | 'synthetic'.
    # seed_position is populated only for seed_source == 'brand'.
    seed_source: Mapped[str | None] = mapped_column(String, nullable=True)
    seed_keyword: Mapped[str | None] = mapped_column(String, nullable=True)
    seed_search_volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seed_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    responses: Mapped[list["Response"]] = relationship(back_populates="prompt")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(Enum(RunStatus), default=RunStatus.pending)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    responses: Mapped[list["Response"]] = relationship(back_populates="run")


class Response(Base):
    __tablename__ = "responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("prompts.id"), nullable=False)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"), nullable=False)
    # source = source_id from app.sources.SOURCES. Unknown source ids
    # (from a removed provider) are tolerated downstream.
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_urls: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    search_queries: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prompt: Mapped["Prompt"] = relationship(back_populates="responses")
    run: Mapped["Run"] = relationship(back_populates="responses")
    analyses: Mapped[list["Analysis"]] = relationship(back_populates="response")


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domains: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    is_self: Mapped[bool] = mapped_column(Boolean, default=False)
    # One brand per market — to track the same product in multiple
    # markets, create one `is_self` brand per market.
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="US")
    country_name: Mapped[str] = mapped_column(String(100), nullable=False, default="United States")
    language_code: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    language_name: Mapped[str] = mapped_column(String(50), nullable=False, default="English")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analyses: Mapped[list["Analysis"]] = relationship(back_populates="brand")


class ClientProfile(Base):
    """Business/competitor profile for a client domain. Keyed by bare
    domain (no scheme, no www); refreshed on every /generate call."""

    __tablename__ = "client_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)

    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    language: Mapped[str] = mapped_column(String(64), nullable=False, default="English")
    country: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    distribution: Mapped[str] = mapped_column(String(32), nullable=False, default="national")
    customer_type: Mapped[str] = mapped_column(String(32), nullable=False, default="B2C")
    tone: Mapped[str] = mapped_column(String(32), nullable=False, default="professional")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")

    product_categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    key_products: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    domain_terms: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    seasonal_factors: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)

    # JSONB list of {brand_name, domain, categories, positioning}.
    competitors: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("responses.id"), nullable=False)
    brand_id: Mapped[int] = mapped_column(ForeignKey("brands.id"), nullable=False)
    brand_found: Mapped[bool] = mapped_column(Boolean, default=False)
    sentiment: Mapped[Sentiment] = mapped_column(Enum(Sentiment), default=Sentiment.not_mentioned)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    link_present: Mapped[bool] = mapped_column(Boolean, default=False)
    competitors: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    our_pages: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    response: Mapped["Response"] = relationship(back_populates="analyses")
    brand: Mapped["Brand"] = relationship(back_populates="analyses")


class RunSchedule(Base):
    """One row per tracked self-brand; interval-based (no cron yet)."""

    __tablename__ = "run_schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    brand_id: Mapped[int] = mapped_column(
        ForeignKey("brands.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, default=168, nullable=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PipelineRun(Base):
    """Live runtime timeline of an in-flight prompt-generator run.
    Decoupled from GeneratorRun (which holds the final artifact)."""

    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Each entry: {stage, started_at, completed_at, status, summary, details, warnings}.
    stages: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)

    generator_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class GeneratorRun(Base):
    """Verbatim snapshot of one prompt-generator pipeline run."""

    __tablename__ = "generator_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sources_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    profile: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    competitors: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    corpus: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    personas: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    keyword_signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    queries: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
