<script setup lang="ts">
/**
 * Dashboard — functional SaaS layout.
 *
 * Reading order top → bottom:
 *   1. Page head    — title + dek + range picker + actions
 *   2. Summary      — amber callout when there's a "biggest leak"
 *      callout       finding worth surfacing; otherwise hidden
 *   3. KPI strip    — visibility / recommendation / citation / SoV
 *   4. Trend + Sentiment (3-2 grid)
 *   5. Per-source breakdown (wide)
 *   6. Leaderboard + GEO funnel (3-2 grid)
 *   7. Best & worst prompts (wide)
 *
 * Voice: declarative but neutral. The summary callout names the actual
 * story; everything else is data the reader can audit themselves.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Loader2,
  Play,
  FileText,
  RefreshCw,
  AlertTriangle,
  Sparkles,
} from "lucide-vue-next";

import LineChart from "@/components/LineChart.vue";
import Sparkline from "@/components/Sparkline.vue";
import FunnelChart from "@/components/FunnelChart.vue";
import Donut from "@/components/Donut.vue";
import ReportConfigDialog from "@/components/ReportConfigDialog.vue";

import { api, ApiError } from "@/api/client";
import type {
  BrandComparison,
  CitationStat,
  FunnelMetrics,
  PromptPerformance,
  PromptRecommendation,
  RunSummary,
  SourceBreakdown,
} from "@/api/types";
import { pct, num, shortDate, timeAgo } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();
const router = useRouter();
const route = useRoute();

// Source filter. When set, every panel except the per-source
// breakdown itself filters to this source id (e.g. "brightdata_chatgpt").
// The per-source panel always shows all four sources so it can act as
// the picker. URL-synced via ?source= so deep links + back-button work.
const selectedSource = ref<string | null>(
  typeof route.query.source === "string" ? route.query.source : null,
);

function setSelectedSource(source: string | null) {
  selectedSource.value = source;
  router.replace({
    query: { ...route.query, source: source ?? undefined },
  });
}

function toggleSourceFilter(source: string) {
  setSelectedSource(selectedSource.value === source ? null : source);
}

const selectedSourceName = computed(() => {
  if (!selectedSource.value) return null;
  const row = bySource.value.find((s) => s.source === selectedSource.value);
  return row?.source_name ?? selectedSource.value;
});

const reportDialogOpen = ref(false);
const range = ref<"7d" | "14d" | "30d" | "90d">("30d");

const loading = ref(true);
const refreshing = ref(false);
const summaries = ref<RunSummary[]>([]);
const bySource = ref<SourceBreakdown[]>([]);
const comparison = ref<BrandComparison | null>(null);
const promptsPerf = ref<PromptPerformance[]>([]);
const citations = ref<CitationStat[]>([]);
const citationGap = ref<CitationStat[]>([]);
const funnel = ref<FunnelMetrics | null>(null);
const recommendations = ref<PromptRecommendation[]>([]);

const latest = computed(() => summaries.value[0] ?? null);
const previous = computed(() => summaries.value[1] ?? null);

async function loadAll(opts: { silent?: boolean } = {}) {
  if (!opts.silent) loading.value = true;
  refreshing.value = !!opts.silent;
  // Snapshot at call time so concurrent reloads don't cross-pollute.
  const src = selectedSource.value ?? undefined;
  try {
    const [s, l, comp, p, cit, fn, rec, gap] = await Promise.all([
      api.runsSummary(20, { excludeIntent: "brand", source: src }),
      // bySource is the picker — never filter it by selected source.
      api.bySource({ excludeIntent: "brand" }),
      api.comparison({ source: src }),
      api.promptPerformance({ source: src }),
      api.citations({ days: 30, limit: 8, source: src }),
      api.funnel({ excludeIntent: "brand", source: src }),
      api.recommendations({ limit: 8, source: src }),
      api.citationGap({ days: 30, limit: 8, source: src }),
    ]);
    summaries.value = s;
    bySource.value = l;
    comparison.value = comp;
    promptsPerf.value = p;
    citations.value = cit;
    funnel.value = fn;
    recommendations.value = rec;
    citationGap.value = gap;
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : t("dashboard.toast.load_failed"));
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

// Reload everything when the source filter changes (clicking a per-source
// panel row, hitting the "show all" pill, or hitting back/forward in the
// browser to a different ?source= URL).
watch(selectedSource, () => {
  loadAll({ silent: true });
});

function goToRuns() {
  router.push("/runs");
}

// ---- Demo dataset (first-run "try without keys") ----------------
const demo = ref<{ has_data: boolean; is_demo: boolean }>({
  has_data: true, // assume data until status resolves — avoids CTA flash
  is_demo: false,
});
const demoBusy = ref(false);

async function loadDemoStatus() {
  try {
    const s = await api.demoStatus();
    demo.value = { has_data: s.has_data, is_demo: s.is_demo };
  } catch {
    /* non-fatal — the CTA just won't show */
  }
}

async function seedDemo() {
  demoBusy.value = true;
  try {
    await api.demoSeed();
    toasts.success("Sample data loaded — exploring demo brand “Vellar”");
    await Promise.all([loadDemoStatus(), loadAll()]);
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load sample data");
  } finally {
    demoBusy.value = false;
  }
}

async function clearDemo() {
  if (!confirm("Clear the sample dataset? This wipes the demo brand and runs so you can start tracking your own brand.")) {
    return;
  }
  demoBusy.value = true;
  try {
    await api.demoClear();
    toasts.success("Sample data cleared — add your brand to start tracking");
    await Promise.all([loadDemoStatus(), loadAll()]);
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to clear sample data");
  } finally {
    demoBusy.value = false;
  }
}

// ---- KPI strip --------------------------------------------------

interface Kpi {
  label: string;
  value: string;
  delta: number | null;
  spark: number[];
  color: string;
  hint: string;
}

function delta(curr: number | null | undefined, prev: number | null | undefined): number | null {
  if (curr === null || curr === undefined || prev === null || prev === undefined) return null;
  return (curr - prev) * 100;
}

const reverseSummaries = computed(() => [...summaries.value].reverse());
const sparkVis = computed(() => reverseSummaries.value.map((s) => s.metrics.visibility_rate * 100));
const sparkRec = computed(() => reverseSummaries.value.map((s) => s.metrics.recommendation_rate * 100));
const sparkCit = computed(() => reverseSummaries.value.map((s) => s.metrics.citation_rate * 100));

const sov = computed<{ rate: number | null }>(() => {
  const c = comparison.value;
  if (!c || c.brands.length === 0) return { rate: null };
  const totalMentions = c.brands.reduce((s, b) => s + b.metrics.brand_mentioned, 0);
  const selfMentions = c.brands
    .filter((b) => b.is_self)
    .reduce((s, b) => s + b.metrics.brand_mentioned, 0);
  return { rate: totalMentions > 0 ? selfMentions / totalMentions : null };
});

const sparkSov = computed(() =>
  reverseSummaries.value.map((s) => s.metrics.visibility_rate * 100),
);

const kpis = computed<Kpi[]>(() => {
  if (!latest.value) return [];
  const m = latest.value.metrics;
  const mp = previous.value?.metrics;
  return [
    {
      label: t("dashboard.kpi.visibility"),
      value: pct(m.visibility_rate, 0),
      delta: delta(m.visibility_rate, mp?.visibility_rate),
      spark: sparkVis.value,
      color: "var(--color-accent)",
      hint: t("dashboard.kpi.visibility_hint_full"),
    },
    {
      label: t("dashboard.kpi.recommendation"),
      value: pct(m.recommendation_rate, 0),
      delta: delta(m.recommendation_rate, mp?.recommendation_rate),
      spark: sparkRec.value,
      color: "var(--color-fg)",
      hint: t("dashboard.kpi.recommendation_hint_full"),
    },
    {
      label: t("dashboard.kpi.citation"),
      value: pct(m.citation_rate, 0),
      delta: delta(m.citation_rate, mp?.citation_rate),
      spark: sparkCit.value,
      color: "var(--color-fg)",
      hint: t("dashboard.kpi.citation_hint_full"),
    },
    {
      label: t("dashboard.kpi.share_of_voice"),
      value: sov.value.rate !== null ? pct(sov.value.rate, 0) : "—",
      delta: null,
      spark: sparkSov.value,
      color: "var(--color-highlight)",
      hint: t("dashboard.kpi.sov_hint_full"),
    },
  ];
});

function deltaInfo(d: number | null): { cls: string; arrow: string; text: string } | null {
  if (d === null) return null;
  if (Math.abs(d) < 0.05) return { cls: "text-[var(--color-fg-muted)]", arrow: "—", text: "0.0" };
  const up = d > 0;
  return {
    cls: up ? "text-[var(--color-success)]" : "text-[var(--color-danger)]",
    arrow: up ? "↑" : "↓",
    text: Math.abs(d).toFixed(1),
  };
}

// ---- Funnel stages ----------------------------------------------

interface FunnelUiStage {
  label: string;
  tag: string;
  count: number;
  rate: number;
}

const funnelStages = computed<FunnelUiStage[]>(() => {
  const f = funnel.value;
  if (!f) return [];
  return [
    { label: t("dashboard.funnel.discovery"), tag: t("dashboard.funnel.discovery_tag"), count: f.discovery.count, rate: f.discovery.rate },
    { label: t("dashboard.funnel.citation"), tag: t("dashboard.funnel.citation_tag"), count: f.citation.count, rate: f.citation.rate },
    { label: t("dashboard.funnel.mention"), tag: t("dashboard.funnel.mention_tag"), count: f.mention.count, rate: f.mention.rate },
    { label: t("dashboard.funnel.recommendation"), tag: t("dashboard.funnel.recommendation_tag"), count: f.recommendation.count, rate: f.recommendation.rate },
    { label: t("dashboard.funnel.link"), tag: t("dashboard.funnel.link_tag"), count: f.link.count, rate: f.link.rate },
  ];
});

const funnelLeak = computed<{ stage: string; drop: number } | null>(() => {
  const stages = funnelStages.value;
  let leakIdx = -1;
  let leakValue = 0;
  for (let i = 1; i < stages.length; i++) {
    const prev = stages[i - 1].rate;
    const curr = stages[i].rate;
    if (prev <= 0) continue;
    const change = (curr - prev) / prev;
    if (change < leakValue) {
      leakValue = change;
      leakIdx = i;
    }
  }
  if (leakIdx < 0) return null;
  return { stage: stages[leakIdx].label.toLowerCase(), drop: leakValue };
});

// ---- Summary callout --------------------------------------------

const calloutDismissed = ref(false);
const summaryCallout = computed<{ title: string; body: string } | null>(() => {
  if (calloutDismissed.value) return null;
  const f = funnelLeak.value;
  if (!f || f.drop > -0.3) return null;
  return {
    title: t("dashboard.callout.title"),
    body: t("dashboard.callout.funnel_leak", {
      stage: f.stage,
      drop: Math.round(Math.abs(f.drop) * 100),
    }),
  };
});

// ---- Sentiment over latest run ----------------------------------

interface SentRow {
  name: string;
  value: number;
  color: string;
}

const sentimentRows = computed<SentRow[]>(() => {
  const s = latest.value?.sentiment;
  if (!s) return [];
  const total = s.positive + s.neutral + s.negative;
  if (total === 0) return [];
  return [
    { name: t("sentiment.positive"), value: s.positive / total, color: "var(--color-success)" },
    { name: t("sentiment.neutral"), value: s.neutral / total, color: "var(--color-fg-muted)" },
    { name: t("sentiment.negative"), value: s.negative / total, color: "var(--color-danger)" },
  ];
});

const positivePct = computed(() => {
  const s = latest.value?.sentiment;
  if (!s) return null;
  const total = s.positive + s.neutral + s.negative;
  if (total === 0) return null;
  return s.positive / total;
});

const sentimentDonutSegments = computed(() =>
  sentimentRows.value.map((r) => ({ value: r.value * 100, color: r.color })),
);

// ---- Trend chart ------------------------------------------------

const chartLabels = computed(() => reverseSummaries.value.map((s) => shortDate(s.started_at)));
const chartSeries = computed(() => [
  {
    label: t("dashboard.kpi.visibility"),
    color: "#2B59FF",
    data: reverseSummaries.value.map((s) => s.metrics.visibility_rate * 100),
  },
  {
    label: t("dashboard.kpi.recommendation"),
    color: "#C2410C",
    dashed: true,
    data: reverseSummaries.value.map((s) => s.metrics.recommendation_rate * 100),
  },
]);

// ---- Best / worst prompts ---------------------------------------

const topPrompts = computed(() =>
  promptsPerf.value
    .filter((p) => p.intent !== "brand" && p.total_responses > 0)
    .slice()
    .sort((a, b) => b.hit_rate - a.hit_rate)
    .slice(0, 5),
);

const worstPrompts = computed(() =>
  promptsPerf.value
    .filter((p) => p.intent !== "brand" && p.total_responses > 0 && p.hit_rate < 0.5)
    .slice()
    .sort((a, b) => a.hit_rate - b.hit_rate)
    .slice(0, 5),
);

const allPromptsSorted = computed(() =>
  promptsPerf.value
    .filter((p) => p.intent !== "brand" && p.total_responses > 0)
    .slice()
    .sort((a, b) => b.hit_rate - a.hit_rate),
);

const promptsFilter = ref<"all" | "best" | "worst">("all");
const promptsToShow = computed(() => {
  if (promptsFilter.value === "best") return topPrompts.value;
  if (promptsFilter.value === "worst") return worstPrompts.value;
  // "all" — show top 5 + bottom 5
  return [...topPrompts.value, ...worstPrompts.value].slice(0, 8);
});

// ---- Leaderboard ------------------------------------------------

interface LeaderRow {
  brand_id: number;
  name: string;
  is_self: boolean;
  visibility: number;
  recommendation: number;
  share: number;
}

const leaderboardRows = computed<LeaderRow[]>(() => {
  const c = comparison.value;
  if (!c) return [];
  const totalMentions = c.brands.reduce((s, b) => s + b.metrics.brand_mentioned, 0);
  const rows: LeaderRow[] = c.brands.map((b) => ({
    brand_id: b.brand_id,
    name: b.brand_name,
    is_self: b.is_self,
    visibility: b.metrics.visibility_rate,
    recommendation: b.metrics.recommendation_rate,
    share: totalMentions > 0 ? b.metrics.brand_mentioned / totalMentions : 0,
  }));
  rows.sort((a, b) => {
    if (a.is_self !== b.is_self) return a.is_self ? -1 : 1;
    return b.share - a.share;
  });
  return rows;
});

function brandInitials(name: string): string {
  return name
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

onMounted(() => {
  loadAll();
  loadDemoStatus();
});
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <div class="flex items-center gap-2">
        <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("dashboard.title") }}</h1>
        <button
          v-if="selectedSource"
          type="button"
          class="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-[var(--color-accent-soft)] text-[var(--color-accent)] hover:opacity-80"
          :title="t('dashboard.click_to_clear')"
          @click="setSelectedSource(null)"
        >
          <span>{{ selectedSourceName }}</span>
          <span class="text-[10px]">✕</span>
        </button>
      </div>
      <p v-if="latest" class="dek mt-1">
        {{ t("dashboard.dek_responses", {
          count: latest.metrics.total_responses,
          sources: bySource.length,
          ago: timeAgo(latest.started_at),
        }) }}
      </p>
      <p v-else class="dek mt-1">{{ t("dashboard.dek_no_runs") }}</p>
    </div>
    <div class="flex items-center gap-2">
      <div class="inline-flex items-center border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] overflow-hidden">
        <button
          v-for="opt in (['7d', '14d', '30d', '90d'] as const)"
          :key="opt"
          type="button"
          @click="range = opt"
          :class="[
            'py-[5px] px-2.5 transition-colors border-r border-[var(--color-line)] last:border-r-0',
            range === opt
              ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] font-medium'
              : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
          ]"
        >{{ opt }}</button>
      </div>
      <button
        type="button"
        @click="loadAll({ silent: true })"
        :disabled="refreshing || loading"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors disabled:opacity-50"
      >
        <RefreshCw class="h-3 w-3" :class="refreshing ? 'animate-spin' : ''" />
        {{ t("btn.refresh") }}
      </button>
      <button
        type="button"
        @click="reportDialogOpen = true"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
      >
        <FileText class="h-3 w-3" />
        {{ t("btn.report") }}
      </button>
      <button
        type="button"
        @click="goToRuns"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] font-medium hover:bg-[var(--color-fg-2)] transition-colors"
      >
        <Play class="h-3 w-3" />
        {{ t("btn.run_now") }}
      </button>
    </div>
  </div>

  <ReportConfigDialog v-model:open="reportDialogOpen" />

  <div
    v-if="demo.is_demo"
    class="flex items-center gap-2.5 py-2 px-3.5 bg-[var(--color-accent-soft,var(--color-warning-soft))] border border-[color-mix(in_oklab,var(--color-accent,var(--color-warning))_30%,transparent)] rounded-lg text-[13px] mb-3"
  >
    <Sparkles class="h-4 w-4 shrink-0 text-[var(--color-accent,var(--color-warning))]" />
    <p class="flex-1">
      <strong class="font-semibold">Sample data.</strong>
      You're viewing a fictional demo brand (“Vellar”). Numbers are illustrative.
    </p>
    <button
      type="button"
      :disabled="demoBusy"
      @click="clearDemo"
      class="shrink-0 inline-flex items-center gap-1.5 py-1 px-2.5 border border-[var(--color-line)] rounded-md text-[12px] font-medium bg-[var(--color-surface)] hover:bg-[var(--color-bg)] disabled:opacity-50"
    >
      <Loader2 v-if="demoBusy" class="h-3 w-3 animate-spin" />
      Clear &amp; start fresh
    </button>
  </div>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <template v-else-if="latest && latest.metrics.total_responses > 0">
    <!-- Summary callout -->
    <div
      v-if="summaryCallout"
      class="flex items-start gap-2.5 py-2.5 px-3.5 bg-[var(--color-warning-soft)] border border-[color-mix(in_oklab,var(--color-warning)_30%,transparent)] rounded-lg text-[13px] mb-3"
    >
      <AlertTriangle class="h-4 w-4 text-[var(--color-warning)] shrink-0 mt-px" />
      <p class="flex-1">
        <strong class="font-semibold">{{ summaryCallout.title }}:</strong>
        {{ summaryCallout.body }}
      </p>
      <div class="flex gap-1.5">
        <button
          type="button"
          class="py-1 px-2 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)] transition-colors"
          @click="calloutDismissed = true"
        >{{ t("dashboard.btn.dismiss") }}</button>
        <button
          type="button"
          class="py-1 px-2 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] hover:bg-[var(--color-fg-2)] transition-colors"
          @click="router.push('/prompts')"
        >{{ t("dashboard.btn.show_prompts") }}</button>
      </div>
    </div>

    <!-- KPI strip -->
    <section class="grid grid-cols-4 gap-3">
      <div
        v-for="k in kpis"
        :key="k.label"
        class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg py-3.5 px-4 pb-3"
      >
        <p class="flex items-center gap-1.5 text-[12px] font-medium text-[var(--color-fg-2)] mb-1.5">
          {{ k.label }}
          <span
            class="inline-flex items-center justify-center w-3.5 h-3.5 border border-[var(--color-line)] rounded-full text-[var(--color-fg-muted)] text-[10px] cursor-help"
            :title="k.hint"
          >i</span>
        </p>
        <p class="display-num">{{ k.value }}</p>
        <div v-if="deltaInfo(k.delta)" class="mt-1 text-[12px] font-mono inline-flex items-center gap-1.5">
          <span :class="deltaInfo(k.delta)!.cls">{{ deltaInfo(k.delta)!.arrow }} {{ deltaInfo(k.delta)!.text }} pts</span>
          <span class="text-[var(--color-fg-muted)] font-sans">{{ t("dashboard.kpi.vs_prior_run") }}</span>
        </div>
        <div v-else class="mt-1 text-[12px] font-mono text-[var(--color-fg-muted)]">—</div>
        <div class="mt-2 h-8" v-if="k.spark.length > 1">
          <Sparkline :data="k.spark" :color="k.color" area :width="260" :height="32" />
        </div>
      </div>
    </section>

    <!-- Top opportunities -->
    <section
      v-if="recommendations.length > 0"
      class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden mt-3"
    >
      <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
        <div>
          <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.opportunities") }}</p>
          <p class="text-[12px] text-[var(--color-fg-muted)]">
            {{ t("dashboard.section.opportunities_dek") }}
          </p>
        </div>
        <span class="font-mono text-[11px] text-[var(--color-fg-muted)]">{{ t("dashboard.opportunities.surfaced", { count: recommendations.length }) }}</span>
      </header>
      <ul class="divide-y divide-[var(--color-line-soft)]">
        <li
          v-for="r in recommendations"
          :key="r.prompt_id"
          class="grid gap-3 py-3 px-4 hover:bg-[var(--color-bg)] cursor-pointer items-start"
          style="grid-template-columns: 1fr 240px"
          @click="router.push(`/prompts/${r.prompt_id}`)"
        >
          <div class="min-w-0">
            <div class="flex items-center gap-2 flex-wrap mb-1">
              <span
                class="inline-flex items-center py-0.5 px-2 rounded text-[10.5px] font-semibold uppercase tracking-[0.04em]"
                :class="{
                  'bg-[var(--color-highlight-soft)] text-[var(--color-highlight)]': r.recommendation_kind === 'get_cited',
                  'bg-[var(--color-accent-soft)] text-[var(--color-accent)]': r.recommendation_kind === 'publish_comparison',
                  'bg-[var(--color-info-soft)] text-[var(--color-info)]': r.recommendation_kind === 'target_query',
                  'bg-[var(--color-success-soft)] text-[var(--color-success)]': r.recommendation_kind === 'publish_content',
                }"
              >{{ r.recommendation_kind.replace(/_/g, " ") }}</span>
              <span
                class="inline-flex items-center py-0.5 px-2 border border-[var(--color-line)] rounded text-[10.5px] font-medium text-[var(--color-fg-2)] capitalize"
              >{{ r.intent }}</span>
              <span class="font-mono text-[10.5px] text-[var(--color-fg-muted)]">
                {{ t("dashboard.opportunities.you_vs_comp", {
                  self_n: r.self_mentioned_count,
                  self_total: r.self_total_responses,
                  comp_n: r.top_competitor.mention_count,
                  comp_name: r.top_competitor.brand_name,
                }) }}
              </span>
            </div>
            <p class="italic text-[13px] text-[var(--color-fg)] line-clamp-1">"{{ r.prompt_text }}"</p>
            <p class="text-[12.5px] text-[var(--color-fg-2)] mt-1.5 leading-snug">{{ r.recommendation_text }}</p>
            <div v-if="r.cited_domains.length > 0" class="flex flex-wrap gap-1 mt-2">
              <span
                v-for="d in r.cited_domains.slice(0, 4)"
                :key="d"
                class="font-mono text-[10.5px] text-[var(--color-fg-muted)] py-px px-1.5 rounded bg-[var(--color-surface-2)]"
              >{{ d }}</span>
            </div>
          </div>
          <div class="flex flex-col items-end gap-1">
            <span class="cap !text-[10px]">{{ t("dashboard.opportunity") }}</span>
            <div class="w-full h-2 bg-[var(--color-surface-3)] rounded overflow-hidden">
              <div
                class="h-full bg-[var(--color-accent)] rounded"
                :style="{ width: `${Math.min(100, r.opportunity_score * 100)}%` }"
              />
            </div>
            <span class="font-mono text-[11px] font-semibold">{{ pct(r.opportunity_score, 0) }}</span>
          </div>
        </li>
      </ul>
    </section>

    <!-- Trend + Sentiment -->
    <div class="grid grid-cols-[3fr_2fr] gap-3 mt-3">
      <!-- Trend chart -->
      <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden">
        <header class="flex items-center justify-between gap-3 py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.trend.title", { n: summaries.length }) }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("dashboard.trend.dek") }}</p>
          </div>
        </header>
        <div class="px-4 pb-4">
          <LineChart
            v-if="summaries.length > 1"
            :labels="chartLabels"
            :series="chartSeries"
            :y-format="(v: number) => `${v.toFixed(0)}%`"
          />
          <p v-else class="text-[13px] text-[var(--color-fg-muted)] text-center py-12">
            {{ t("dashboard.trend.need_runs") }}
          </p>
        </div>
      </section>

      <!-- Sentiment -->
      <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden">
        <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.sentiment") }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("dashboard.sentiment.mentions_count", { n: latest.metrics.brand_mentioned }) }}</p>
          </div>
        </header>
        <div class="px-4 pb-4 flex gap-4 items-center">
          <Donut
            v-if="sentimentRows.length > 0"
            :size="120"
            :thickness="16"
            :segments="sentimentDonutSegments"
            :center-value="positivePct !== null ? pct(positivePct, 0) : '—'"
            :center-label="t('dashboard.sentiment.positive')"
          />
          <div v-else class="w-[120px] h-[120px] flex items-center justify-center text-[var(--color-fg-muted)] text-[12px]">{{ t("dashboard.sentiment.no_data") }}</div>
          <div class="flex-1">
            <div
              v-for="row in sentimentRows"
              :key="row.name"
              class="flex items-center gap-2.5 py-1.5 text-[12px]"
            >
              <span class="w-2.5 h-2.5 rounded-sm" :style="{ background: row.color }" />
              <span class="flex-1">{{ row.name }}</span>
              <span class="font-mono text-[12px] text-[var(--color-fg)]">{{ pct(row.value, 0) }}</span>
            </div>
          </div>
        </div>
        <div class="border-t border-[var(--color-line-soft)] py-3 px-4 grid grid-cols-2 gap-4">
          <div>
            <p class="cap">{{ t("dashboard.metric.cited") }}</p>
            <p class="text-[22px] font-semibold tracking-[-0.02em] mt-0.5">{{ pct(latest.metrics.citation_rate, 0) }}</p>
          </div>
          <div>
            <p class="cap">{{ t("dashboard.metric.mentions") }}</p>
            <p class="text-[22px] font-semibold tracking-[-0.02em] mt-0.5">{{ latest.metrics.brand_mentioned }}</p>
          </div>
        </div>
      </section>
    </div>

    <!-- Per-source breakdown — also acts as the source filter.
         Click a row to filter every other panel to that source; click the
         active row again or the "show all" pill to clear. -->
    <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden mt-3">
      <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
        <div>
          <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.per_source") }}</p>
          <p class="text-[12px] text-[var(--color-fg-muted)]">
            {{ t("dashboard.section.per_source_dek") }}
          </p>
        </div>
        <button
          v-if="selectedSource"
          type="button"
          class="text-[11px] font-mono uppercase tracking-wider px-2 py-1 rounded border border-[var(--color-line)] hover:bg-[var(--color-surface-2)]"
          @click="setSelectedSource(null)"
        >{{ t("dashboard.per_source.show_all") }}</button>
      </header>
      <div class="grid border-t border-[var(--color-line)]" :style="{ gridTemplateColumns: `repeat(${bySource.length}, 1fr)` }">
        <button
          v-for="(s, i) in bySource"
          :key="s.source"
          type="button"
          class="text-left py-3.5 px-4 transition-colors"
          :class="[
            i < bySource.length - 1 ? 'border-r border-[var(--color-line-soft)]' : '',
            selectedSource === s.source
              ? 'bg-[var(--color-accent-soft)] ring-1 ring-inset ring-[var(--color-accent)]'
              : 'hover:bg-[var(--color-surface-2)]',
          ]"
          @click="toggleSourceFilter(s.source)"
        >
          <p class="flex items-center gap-2 text-[13px] font-medium mb-2">
            <span
              class="w-2 h-2 rounded-sm"
              :class="selectedSource === s.source ? 'bg-[var(--color-accent)]' : 'bg-[var(--color-fg-muted)]'"
            />
            {{ s.source_name }}
          </p>
          <p class="text-[22px] font-semibold tracking-[-0.02em] flex items-baseline gap-1 leading-none">
            {{ pct(s.metrics.visibility_rate, 0) }}
          </p>
          <p
            class="text-[11px] text-[var(--color-fg-muted)] mt-2"
          >{{ t("dashboard.per_source.responses_mentions", { responses: s.metrics.total_responses, mentions: s.metrics.brand_mentioned }) }}</p>
        </button>
      </div>
    </section>

    <!-- Citation gap + Top cited -->
    <div class="grid grid-cols-[3fr_2fr] gap-3 mt-3" v-if="citationGap.length > 0 || citations.length > 0">
      <!-- Citation gap (where competitors are cited but you're not) -->
      <section
        v-if="citationGap.length > 0"
        class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
      >
        <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.citation_gap") }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">
              {{ t("dashboard.citation_gap.dek") }}
            </p>
          </div>
        </header>
        <table class="w-full border-collapse text-[13px]">
          <thead>
            <tr class="bg-[var(--color-bg)]">
              <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">{{ t("dashboard.col.domain") }}</th>
              <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">{{ t("dashboard.citation_gap.col.owner") }}</th>
              <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.col.citations") }}</th>
              <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.col.share") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="d in citationGap"
              :key="d.domain"
              class="hover:bg-[var(--color-bg)]"
            >
              <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-[12.5px]">{{ d.domain }}</td>
              <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
                <span
                  v-if="d.brand_name"
                  class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium bg-[var(--color-highlight-soft)] text-[var(--color-highlight)]"
                >{{ d.brand_name }}</span>
                <span
                  v-else
                  class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium text-[var(--color-fg-muted)] italic"
                >{{ t("dashboard.citation_gap.third_party") }}</span>
              </td>
              <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ d.citation_count }}</td>
              <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ pct(d.share, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Top cited (all responses, including yours) -->
      <section
        v-if="citations.length > 0"
        class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
      >
        <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.top_cited") }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("dashboard.top_cited.dek") }}</p>
          </div>
        </header>
        <ul class="divide-y divide-[var(--color-line-soft)]">
          <li
            v-for="c in citations"
            :key="c.domain"
            class="flex items-center justify-between gap-3 py-2.5 px-4 text-[13px]"
            :class="c.is_self ? 'bg-[var(--color-accent-soft)]' : ''"
          >
            <span class="font-mono text-[12.5px] truncate flex items-center gap-2 min-w-0">
              <span class="truncate">{{ c.domain }}</span>
              <span
                v-if="c.is_self"
                class="bg-[var(--color-accent)] text-white text-[10px] font-mono px-1.5 py-px rounded shrink-0"
              >{{ t("dashboard.top_cited.you_badge") }}</span>
              <span
                v-else-if="c.brand_name"
                class="bg-[var(--color-highlight-soft)] text-[var(--color-highlight)] text-[10px] font-medium px-1.5 py-px rounded shrink-0"
              >{{ c.brand_name }}</span>
            </span>
            <span class="font-mono text-[11px] text-[var(--color-fg-muted)] shrink-0">
              {{ c.citation_count }} · {{ pct(c.share, 0) }}
            </span>
          </li>
        </ul>
      </section>
    </div>

    <!-- Leaderboard + Funnel -->
    <div class="grid grid-cols-[3fr_2fr] gap-3 mt-3">
      <!-- Leaderboard -->
      <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden">
        <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.leaderboard") }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("dashboard.leaderboard.dek") }}</p>
          </div>
          <RouterLink to="/brands" class="text-[12px] text-[var(--color-accent)] hover:underline">{{ t("dashboard.btn.full_report") }}</RouterLink>
        </header>
        <table class="w-full border-collapse text-[13px]">
          <thead>
            <tr class="bg-[var(--color-bg)]">
              <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] w-10">{{ t("dashboard.leaderboard.col.rank") }}</th>
              <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">{{ t("dashboard.col.brand") }}</th>
              <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.col.visibility") }}</th>
              <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.leaderboard.col.recommend") }}</th>
              <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.leaderboard.col.sov") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in leaderboardRows"
              :key="r.brand_id"
              :class="r.is_self ? 'bg-[var(--color-accent-soft)]' : 'hover:bg-[var(--color-bg)]'"
            >
              <td
                class="py-2 px-4 border-b border-[var(--color-line-soft)] font-mono text-[var(--color-fg-muted)]"
                :class="r.is_self ? 'shadow-[inset_3px_0_0_var(--color-accent)] !pl-3' : ''"
              >{{ i + 1 }}</td>
              <td class="py-2 px-4 border-b border-[var(--color-line-soft)]">
                <div class="flex items-center gap-2">
                  <span
                    :class="[
                      'w-[22px] h-[22px] rounded inline-flex items-center justify-center text-[10px] font-semibold',
                      r.is_self
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'bg-[var(--color-surface-2)] text-[var(--color-fg-2)]',
                    ]"
                  >{{ brandInitials(r.name) }}</span>
                  <span :class="r.is_self ? 'font-semibold' : 'font-medium'">{{ r.name }}</span>
                  <span
                    v-if="r.is_self"
                    class="bg-[var(--color-accent)] text-white text-[10px] font-medium px-2 py-px rounded"
                  >{{ t("dashboard.leaderboard.you_pill") }}</span>
                </div>
              </td>
              <td class="py-2 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ pct(r.visibility, 0) }}</td>
              <td class="py-2 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ pct(r.recommendation, 0) }}</td>
              <td class="py-2 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ pct(r.share, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Funnel -->
      <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden">
        <header class="flex items-center justify-between gap-3 py-3.5 px-4 pb-2.5">
          <div>
            <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.section.funnel") }}</p>
            <p class="text-[12px] text-[var(--color-fg-muted)]">
              {{ t("dashboard.funnel.dek", { responses: funnel?.total_responses ?? 0 }) }}
            </p>
          </div>
          <span
            v-if="funnelLeak"
            class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[var(--color-warning-soft)] text-[var(--color-warning)]"
          >{{ t("dashboard.funnel.leak", { stage: funnelLeak.stage }) }}</span>
        </header>
        <div class="px-4 pb-4">
          <FunnelChart v-if="funnel" :stages="funnelStages" />
        </div>
      </section>
    </div>

    <!-- Best & worst prompts -->
    <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden mt-3">
      <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
        <div>
          <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("dashboard.best_worst.title") }}</p>
          <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("dashboard.best_worst.dek") }}</p>
        </div>
        <div class="flex gap-1.5">
          <button
            v-for="opt in (['all', 'best', 'worst'] as const)"
            :key="opt"
            type="button"
            @click="promptsFilter = opt"
            :class="[
              'border rounded-md py-1 px-2.5 text-[12px] capitalize transition-colors',
              promptsFilter === opt
                ? 'bg-[var(--color-fg)] text-white border-[var(--color-fg)]'
                : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
            ]"
          >{{ t(`dashboard.best_worst.${opt}`) }}</button>
        </div>
      </header>
      <table class="w-full border-collapse text-[13px]">
        <thead>
          <tr class="bg-[var(--color-bg)]">
            <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">{{ t("dashboard.col.prompt") }}</th>
            <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">{{ t("dashboard.col.intent") }}</th>
            <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.col.visibility") }}</th>
            <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">{{ t("dashboard.best_worst.col.mentioned") }}</th>
            <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in promptsToShow"
            :key="p.prompt_id"
            class="hover:bg-[var(--color-bg)]"
          >
            <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]" style="max-width: 360px">
              <span class="line-clamp-1">{{ p.text }}</span>
            </td>
            <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
              <span
                class="inline-flex items-center py-0.5 px-2 border border-[var(--color-line)] rounded text-[11px] font-medium text-[var(--color-fg-2)] capitalize"
              >{{ p.intent }}</span>
            </td>
            <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
              <div class="flex items-center gap-2 justify-end">
                <span class="w-[60px] h-[6px] rounded-[3px] bg-[var(--color-surface-3)] overflow-hidden inline-block">
                  <span
                    class="block h-full rounded-[3px]"
                    :style="{
                      width: `${p.hit_rate * 100}%`,
                      background: p.hit_rate > 0.4 ? 'var(--color-success)' : 'var(--color-danger)',
                    }"
                  />
                </span>
                <span class="min-w-9 inline-block">{{ pct(p.hit_rate, 0) }}</span>
              </div>
            </td>
            <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
              <span
                v-if="p.mentioned_count > 0"
                class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[var(--color-success-soft)] text-[var(--color-success)]"
              >{{ t("dashboard.best_worst.yes", { n: p.mentioned_count, total: p.total_responses }) }}</span>
              <span
                v-else
                class="inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium bg-[var(--color-danger-soft)] text-[var(--color-danger)]"
              >{{ t("dashboard.best_worst.no", { total: p.total_responses }) }}</span>
            </td>
            <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] text-right">
              <RouterLink :to="`/prompts/${p.prompt_id}`" class="text-[12px] text-[var(--color-accent)] hover:underline">{{ t("dashboard.best_worst.view") }}</RouterLink>
            </td>
          </tr>
          <tr v-if="promptsToShow.length === 0">
            <td colspan="5" class="py-8 px-4 text-center text-[var(--color-fg-muted)] text-[13px]">{{ t("dashboard.best_worst.no_prompts") }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </template>

  <section
    v-else
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg p-12 text-center"
  >
    <h3 class="text-[18px] font-semibold mt-2">No data yet</h3>
    <p class="text-[13px] text-[var(--color-fg-2)] mt-2 max-w-md mx-auto">
      Explore the whole product with a realistic sample dataset — no API keys needed.
      Or configure a self-brand and trigger your first real run.
    </p>
    <div class="flex items-center justify-center gap-2 mt-5">
      <button
        type="button"
        :disabled="demoBusy"
        @click="seedDemo"
        class="inline-flex items-center gap-1.5 py-1.5 px-3 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[13px] font-medium disabled:opacity-50"
      >
        <Loader2 v-if="demoBusy" class="h-3.5 w-3.5 animate-spin" />
        <Sparkles v-else class="h-3.5 w-3.5" />
        Load sample data
      </button>
      <button
        type="button"
        @click="goToRuns"
        class="inline-flex items-center gap-1.5 py-1.5 px-3 border border-[var(--color-line)] rounded-md text-[13px] font-medium hover:bg-[var(--color-bg)]"
      >
        <Play class="h-3.5 w-3.5" />
        Run now
      </button>
    </div>
  </section>
</template>
