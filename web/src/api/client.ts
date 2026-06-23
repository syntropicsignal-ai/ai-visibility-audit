/** Typed API client for the AI Visibility Audit backend. */

import type {
  Brand,
  BrandComparison,
  CitationStat,
  CompetitorShare,
  ConfigStatus,
  FunnelMetrics,
  GenerateResult,
  PromptRecommendation,
  RunSchedule,
  RunScheduleUpdate,
  SearchTermStat,
  GeoOptions,
  IntentType,
  Prompt,
  PromptDetail,
  PromptPerformance,
  ReportPayload,
  ReportRequestParams,
  ResponseDetail,
  Run,
  RunSummary,
  ShoppingVisibility,
  SourceBreakdown,
  SourceStatus,
  TopicGraph,
  TopicStat,
  VisibilityMetrics,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    let detail: string | undefined;
    try {
      const body = await res.json();
      detail = typeof body?.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      detail = await res.text().catch(() => undefined);
    }
    throw new ApiError(`${res.status} ${res.statusText}`, res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== null && v !== undefined && v !== "",
  );
  if (entries.length === 0) return "";
  return "?" + entries.map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
}

export const api = {
  // ----- Analytics -----
  visibility: (opts: { runId?: number; brandId?: number; excludeIntent?: IntentType } = {}) =>
    request<VisibilityMetrics>(
      `/analytics/visibility${qs({ run_id: opts.runId, brand_id: opts.brandId, exclude_intent: opts.excludeIntent })}`,
    ),

  runsSummary: (
    limit = 20,
    opts: { brandId?: number; excludeIntent?: IntentType; source?: string } = {},
  ) =>
    request<RunSummary[]>(
      `/analytics/runs/summary${qs({ limit, brand_id: opts.brandId, exclude_intent: opts.excludeIntent, source: opts.source })}`,
    ),

  runSummary: (runId: number, opts: { brandId?: number; excludeIntent?: IntentType } = {}) =>
    request<RunSummary>(
      `/analytics/runs/${runId}/summary${qs({ brand_id: opts.brandId, exclude_intent: opts.excludeIntent })}`,
    ),

  bySource: (opts: { runId?: number; brandId?: number; excludeIntent?: IntentType } = {}) =>
    request<SourceBreakdown[]>(
      `/analytics/by-source${qs({ run_id: opts.runId, brand_id: opts.brandId, exclude_intent: opts.excludeIntent })}`,
    ),

  citations: (
    opts: {
      run_id?: number;
      intent?: IntentType;
      days?: number;
      limit?: number;
      source?: string;
    } = {},
  ) => request<CitationStat[]>(`/analytics/citations${qs(opts)}`),

  citationGap: (
    opts: { run_id?: number; days?: number; limit?: number; source?: string } = {},
  ) => request<CitationStat[]>(`/analytics/citation-gap${qs(opts)}`),

  searchTerms: (
    opts: { run_id?: number; days?: number; limit?: number; min_count?: number } = {},
  ) => request<SearchTermStat[]>(`/analytics/search-terms${qs(opts)}`),

  promptPerformance: (opts: { source?: string } = {}) =>
    request<PromptPerformance[]>(`/analytics/prompts${qs(opts)}`),

  topics: (opts: { dimension?: "tag" | "intent"; source?: string } = {}) =>
    request<TopicStat[]>(`/analytics/topics${qs(opts)}`),

  topicsGraph: (
    opts: {
      dimension?: "tag" | "intent";
      source?: string;
      top_topics?: number;
      min_edge_weight?: number;
    } = {},
  ) => request<TopicGraph>(`/analytics/topics/graph${qs(opts)}`),

  competitors: (runId?: number, includeSelf = false, excludeIntent?: IntentType) =>
    request<CompetitorShare[]>(
      `/analytics/competitors${qs({ run_id: runId, include_self: includeSelf, exclude_intent: excludeIntent })}`,
    ),

  comparison: (opts: { runId?: number; source?: string } = {}) =>
    request<BrandComparison>(
      `/analytics/comparison${qs({ run_id: opts.runId, source: opts.source })}`,
    ),

  funnel: (
    opts: { runId?: number; brandId?: number; excludeIntent?: IntentType; source?: string } = {},
  ) =>
    request<FunnelMetrics>(
      `/analytics/funnel${qs({ run_id: opts.runId, brand_id: opts.brandId, exclude_intent: opts.excludeIntent, source: opts.source })}`,
    ),

  recommendations: (opts: { threshold?: number; limit?: number; source?: string } = {}) =>
    request<PromptRecommendation[]>(
      `/analytics/recommendations${qs({ threshold: opts.threshold, limit: opts.limit, source: opts.source })}`,
    ),

  shoppingVisibility: (
    opts: { runId?: number; source?: string; excludeIntent?: IntentType } = {},
  ) =>
    request<ShoppingVisibility>(
      `/analytics/shopping${qs({ run_id: opts.runId, source: opts.source, exclude_intent: opts.excludeIntent })}`,
    ),

  // ----- Schedule -----
  getSchedule: () => request<RunSchedule>(`/schedule`),
  updateSchedule: (body: RunScheduleUpdate) =>
    request<RunSchedule>(`/schedule`, { method: "PUT", body: JSON.stringify(body) }),

  // ----- Runs -----
  listRuns: () => request<Run[]>(`/runs`),

  triggerRun: (brandId: number) =>
    request<Run>(`/runs`, {
      method: "POST",
      body: JSON.stringify({ brand_id: brandId }),
    }),

  responsesForRun: (
    runId: number,
    filters: {
      source?: string;
      intent?: IntentType;
      mentioned?: boolean;
      failed?: boolean;
      q?: string;
    } = {},
  ) => request<ResponseDetail[]>(`/runs/${runId}/responses${qs(filters)}`),

  // ----- Prompts -----
  listPrompts: () => request<Prompt[]>(`/prompts`),
  getPromptDetail: (id: number) => request<PromptDetail>(`/prompts/${id}/detail`),
  createPrompt: (body: Omit<Prompt, "id" | "created_at">) =>
    request<Prompt>(`/prompts`, { method: "POST", body: JSON.stringify(body) }),
  deletePrompt: (id: number) =>
    request<void>(`/prompts/${id}`, { method: "DELETE" }),
  generatePrompts: (url: string) =>
    request<GenerateResult>(`/prompts/generate`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  // ----- Config (first-run setup) -----
  configStatus: () => request<ConfigStatus>(`/config/status`),
  saveConfigKeys: (body: Partial<Record<string, string>>) =>
    request<ConfigStatus>(`/config/keys`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ----- Demo dataset (first-run "try without keys") -----
  demoStatus: () =>
    request<{ has_data: boolean; is_demo: boolean; self_domain: string }>(`/demo/status`),
  demoSeed: () =>
    request<{
      seeded: boolean;
      brands: number;
      prompts: number;
      runs: number;
      responses: number;
      analyses: number;
    }>(`/demo/seed`, { method: "POST" }),
  demoClear: () =>
    request<{ cleared: boolean; reason?: string }>(`/demo/clear`, { method: "POST" }),

  // ----- Sources -----
  listSources: () => request<SourceStatus[]>(`/sources`),

  // ----- Brands -----
  listBrands: () => request<Brand[]>(`/brands`),
  geoOptions: () => request<GeoOptions>(`/brands/geo-options`),
  createBrand: (body: {
    name: string;
    domains: string[];
    aliases: string[];
    is_self: boolean;
    country_code: string;
    language_code: string;
  }) => request<Brand>(`/brands`, { method: "POST", body: JSON.stringify(body) }),
  updateBrand: (
    id: number,
    body: Partial<{
      name: string;
      domains: string[];
      aliases: string[];
      is_self: boolean;
      country_code: string;
      language_code: string;
    }>,
  ) => request<Brand>(`/brands/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteBrand: (id: number) => request<void>(`/brands/${id}`, { method: "DELETE" }),

  // ----- Report -----
  report: (params: ReportRequestParams = {}) => {
    const search = new URLSearchParams();
    if (params.run_id !== undefined) search.set("run_id", String(params.run_id));
    if (params.from_date) search.set("from_date", params.from_date);
    if (params.to_date) search.set("to_date", params.to_date);
    if (params.sample_count !== undefined)
      search.set("sample_count", String(params.sample_count));
    if (params.language) search.set("language", params.language);
    if (params.tier) search.set("tier", params.tier);
    for (const id of params.competitor_ids ?? []) {
      search.append("competitor_ids", String(id));
    }
    const qstr = search.toString();
    return request<ReportPayload>(`/report${qstr ? `?${qstr}` : ""}`);
  },
};
