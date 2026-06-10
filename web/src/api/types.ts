// Mirrors api/app/schemas.py — keep in sync.

export interface ConfigStatus {
  setup_required: boolean;
  required_keys: string[];
  configurable_keys: string[];
  configured: Record<string, boolean>;
}

export type RunStatus = "pending" | "running" | "completed" | "failed";

export type Sentiment = "positive" | "neutral" | "negative" | "not_mentioned";

export interface SentimentCounts {
  positive: number;
  neutral: number;
  negative: number;
}

export type IntentType =
  | "transactional"
  | "informational"
  | "comparative"
  | "brand"
  | "local";

export interface VisibilityMetrics {
  total_responses: number;
  brand_mentioned: number;
  visibility_rate: number;
  recommendation_rate: number;
  citation_rate: number;
  link_rate: number;
}

export interface RunSummary {
  run_id: number;
  started_at: string;
  completed_at: string | null;
  status: RunStatus;
  // Estimated USD cost based on per-response token counts × the rates
  // in api/app/services/pricing.py at the moment the run finalized.
  // null for older runs that ran before token-breakdown was captured.
  total_cost: number | null;
  metrics: VisibilityMetrics;
  sentiment: SentimentCounts;
}

export interface SourceBreakdown {
  source: string;       // source_id, e.g. "brightdata_chatgpt"
  source_name: string;  // human-readable, e.g. "ChatGPT"
  metrics: VisibilityMetrics;
  sentiment: SentimentCounts;
}

export interface PromptPerformance {
  prompt_id: number;
  text: string;
  intent: IntentType;
  tags: string[];
  enabled: boolean;
  total_responses: number;
  mentioned_count: number;
  recommended_count: number;
  hit_rate: number;
  last_run_status: "mentioned" | "missing" | "no_data";
  sentiment: SentimentCounts;
}

export interface CompetitorShare {
  brand_id: number;
  brand_name: string;
  is_self: boolean;
  mention_count: number;
  share_of_voice: number;
}

export interface BrandComparisonEntry {
  brand_id: number;
  brand_name: string;
  is_self: boolean;
  metrics: VisibilityMetrics;
  sentiment: SentimentCounts;
}

export interface BrandComparison {
  run_id: number | null;
  total_responses: number;
  brands: BrandComparisonEntry[];
}

export interface CitationStat {
  domain: string;
  citation_count: number;
  share: number;
  brand_id: number | null;
  brand_name: string | null;
  is_self: boolean;
}

export interface BrandAnalysis {
  brand_id: number;
  brand_name: string;
  is_self: boolean;
  brand_found: boolean;
  sentiment: Sentiment;
  recommended: boolean;
  link_present: boolean;
  our_pages: string[] | null;
  competitors: { name: string; url: string }[] | null;
}

export interface ResponseDetail {
  id: number;
  run_id: number;
  prompt_id: number;
  prompt_text: string;
  prompt_intent: IntentType;
  source: string;
  source_name: string;
  text: string;
  tokens_used: number | null;
  latency_ms: number | null;
  source_urls: string[] | null;
  search_queries: string[] | null;
  error_kind: string | null;
  error_message: string | null;
  created_at: string;
  analyses: BrandAnalysis[];
}

export interface Run {
  id: number;
  started_at: string;
  completed_at: string | null;
  status: RunStatus;
  total_cost: number | null;
}

export interface Prompt {
  id: number;
  text: string;
  intent: IntentType;
  tags: string[];
  enabled: boolean;
  created_at: string;
  // Seed-attribution metadata. Optional + nullable — manually-authored
  // prompts skip them. Populated when the prompt came from the
  // generation pipeline.
  seed_source?: SeedSource | null;
  seed_keyword?: string | null;
  seed_search_volume?: number | null;
  seed_position?: number | null;
}

export type SeedSource = "brand" | "gap" | "synthetic";

export interface Brand {
  id: number;
  name: string;
  domains: string[];
  aliases: string[];
  is_self: boolean;
  // ISO 3166-1 alpha-2, e.g. "US" / "PL". The vendor-neutral identifier
  // used everywhere outside the DataForSEO adapter.
  country_code: string;
  country_name: string;
  language_code: string;
  language_name: string;
  created_at: string;
}

export interface GeoCountry {
  country_code: string;
  name: string;
  default_language_code: string;
}

export interface GeoLanguage {
  code: string;
  name: string;
}

export interface GeoOptions {
  countries: GeoCountry[];
  languages: GeoLanguage[];
}

export interface SourceStatus {
  id: string;               // source_id (e.g. "brightdata_chatgpt")
  display_name: string;
  configured: boolean;      // are this source's credentials present in env?
  credential_hint: string;  // which env var(s) to set, e.g. "BRIGHTDATA_API_KEY"
}

export interface TopicCompetitor {
  brand_id: number;
  brand_name: string;
  mention_count: number;
}

export interface TopicStat {
  topic: string;
  prompt_count: number;
  total_responses: number;
  mentioned_count: number;
  recommended_count: number;
  hit_rate: number;
  recommendation_rate: number;
  sentiment: SentimentCounts;
  share_of_voice: number;        // self mentions / total brand mentions
  total_brand_mentions: number;  // SOV denominator (across all tracked brands)
  top_competitor: TopicCompetitor | null;
}

export type TopicNodeKind = "topic" | "brand";
export type TopicEdgeKind = "topic_brand";

export interface GraphNode {
  id: string;
  kind: TopicNodeKind;
  label: string;
  weight: number;
  is_self: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: TopicEdgeKind;
  weight: number;
}

export interface TopicGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface PromptSourceStats {
  source: string;
  source_name: string;
  total_responses: number;
  mentioned_count: number;
  recommended_count: number;
  hit_rate: number;
}

export interface PromptRunPoint {
  run_id: number;
  started_at: string;
  total_responses: number;
  mentioned_count: number;
  hit_rate: number;
}

export interface PromptCompetitorStat {
  brand_id: number;
  brand_name: string;
  mention_count: number;
}

export interface PromptRecentResponse {
  response_id: number;
  run_id: number;
  source: string;
  source_name: string;
  created_at: string;
  snippet: string;
  mentioned: boolean;
  recommended: boolean;
  sentiment: Sentiment;
  error_kind: string | null;
}

export interface PromptDetail {
  id: number;
  text: string;
  intent: IntentType;
  tags: string[];
  enabled: boolean;
  created_at: string;
  metrics: VisibilityMetrics;
  per_source: PromptSourceStats[];
  trend: PromptRunPoint[];
  competitors: PromptCompetitorStat[];
  recent_responses: PromptRecentResponse[];
}

export interface GeneratedQuery {
  text: string;
  intent: string;
  tags: string[];
  length_mode?: string | null;
  buyer_stage?: string | null;
  shape?: number | null;
  seed_source?: SeedSource | null;
  seed_keyword?: string | null;
  seed_search_volume?: number | null;
  seed_position?: number | null;
}

export interface GenerateResult {
  domain: string;
  pages_found: number;
  competitors: { name: string; domain: string }[];
  queries: GeneratedQuery[];
  keyword_signals: KeywordSignalsPayload;
  profile?: GeneratedProfile;
}

export interface GeneratedProfile {
  brand_name: string;
  language: string;
  country: string;
  currency: string;
  distribution: string;
  customer_type: string;
  product_categories: string[];
  summary: string;
}

export interface KeywordSignalsPayload {
  client_domain: string;
  location_code: number;
  language_code: string;
  client_keywords: RankedKeywordPayload[];
  gap_keywords: RankedKeywordPayload[];
  competitor_summary: { domain: string; keywords_found: number }[];
}

export interface RankedKeywordPayload {
  keyword: string;
  position: number;
  search_volume: number | null;
  keyword_difficulty: number | null;
  url: string | null;
}

export interface FunnelStage {
  label: string;
  count: number;
  rate: number;
}

export interface FunnelMetrics {
  total_responses: number;
  discovery: FunnelStage;
  citation: FunnelStage;
  mention: FunnelStage;
  recommendation: FunnelStage;
  link: FunnelStage;
}

export interface SearchTermStat {
  term: string;
  count: number;
  prompt_count: number;
  source_count: number;
}

export interface CompetitorOpportunity {
  brand_id: number;
  brand_name: string;
  mention_count: number;
  recommended_count: number;
}

export interface RunSchedule {
  brand_id: number;
  enabled: boolean;
  interval_hours: number;
  last_triggered_at: string | null;
  next_run_at: string | null;
}

export interface RunScheduleUpdate {
  enabled?: boolean;
  interval_hours?: number;
}

export interface PromptRecommendation {
  prompt_id: number;
  prompt_text: string;
  intent: IntentType;
  self_hit_rate: number;
  self_mentioned_count: number;
  self_total_responses: number;
  top_competitor: CompetitorOpportunity;
  other_competitors: CompetitorOpportunity[];
  cited_domains: string[];
  triggered_search_queries: string[];
  opportunity_score: number;
  recommendation_kind:
    | "get_cited"
    | "publish_comparison"
    | "target_query"
    | "publish_content";
  recommendation_text: string;
}

// ----- Audit report -----

export interface ReportPeriod {
  kind: "run" | "range";
  run_id: number | null;
  from_date: string;
  to_date: string;
  run_count: number;
}

export interface ReportBrand {
  id: number;
  name: string;
  domain: string | null;
  is_self: boolean;
}

export interface ReportBrandRow {
  brand_id: number;
  brand_name: string;
  is_self: boolean;
  metrics: VisibilityMetrics;
  sentiment: SentimentCounts;
}

export interface ReportPromptSentimentRow {
  prompt_id: number;
  text: string;
  dominant_sentiment: "positive" | "neutral" | "negative" | "not_mentioned";
  recommended_count: number;
  total_responses: number;
  sentiment_counts: SentimentCounts;
}

export interface ReportBrandAwareness {
  total_brand_prompts: number;
  total_responses: number;
  sentiment_counts: SentimentCounts;
  recommendation_rate: number;
  negative: ReportPromptSentimentRow[];
  neutral: ReportPromptSentimentRow[];
  positive: ReportPromptSentimentRow[];
  not_mentioned: ReportPromptSentimentRow[];
}

export interface ReportSampleResponse {
  response_id: number;
  run_id: number;
  source: string;
  source_name: string;
  prompt_text: string;
  prompt_intent: IntentType;
  response_text: string;
  brand_found: boolean;
  sentiment: Sentiment;
  recommended: boolean;
  cited_domains: string[];
}

export type ReportTier = "simple" | "advanced";

export interface ReportPayload {
  period: ReportPeriod;
  self_brand: ReportBrand;
  competitors: ReportBrand[];
  language: string;
  tier: ReportTier;
  metrics: VisibilityMetrics;
  sentiment: SentimentCounts;
  metrics_prior: VisibilityMetrics | null;
  sentiment_prior: SentimentCounts | null;
  brand_awareness: ReportBrandAwareness;
  by_source: SourceBreakdown[];
  citations: CitationStat[];
  competitor_visibility: ReportBrandRow[];
  samples: ReportSampleResponse[];
  // Advanced-tier extras — empty arrays / null on simple tier.
  recommendations: PromptRecommendation[];
  citation_gap: CitationStat[];
  search_terms: SearchTermStat[];
}

export interface ReportRequestParams {
  run_id?: number;
  from_date?: string;
  to_date?: string;
  competitor_ids?: number[];
  sample_count?: number;
  language?: string;
  tier?: ReportTier;
}
