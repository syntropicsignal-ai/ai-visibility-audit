<script setup lang="ts">
/**
 * Audit report — printable client-facing PDF.
 *
 * Standalone route (no app shell) so the PDF doesn't carry the sidebar
 * chrome. The view fetches one consolidated payload from `/api/report`
 * and renders every section in a single column sized for A4 print.
 *
 * URL contract:
 *   /report?run_id=42                     → single-run snapshot
 *   /report?from=YYYY-MM-DD&to=YYYY-MM-DD → range snapshot
 *   &competitors=1,2,3                    → optional competitor ids
 *   &samples=5                            → optional sample count
 *   &lang=pl                              → optional locale override
 *
 * The frontend keeps "human" param names (from / to / competitors /
 * samples / lang); the api client maps them to backend canonical names
 * (from_date / to_date / competitor_ids / sample_count / language).
 *
 * Charts: bar charts only — line charts don't render well on print.
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { Bar } from "vue-chartjs";
import {
  BarController,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  type ChartOptions,
  LinearScale,
  Legend,
  Tooltip as ChartTooltip,
} from "chart.js";

import { api, ApiError } from "@/api/client";
import type {
  ReportPayload,
  ReportPromptSentimentRow,
  ReportRequestParams,
  Sentiment,
} from "@/api/types";
import { pct, num } from "@/lib/format";
import { formatPeriodDate, resolveLocale, t, type LocaleCode } from "./report/i18n";

ChartJS.register(BarController, BarElement, CategoryScale, LinearScale, Legend, ChartTooltip);

const route = useRoute();
const loading = ref(true);
const errorMessage = ref<string | null>(null);
const payload = ref<ReportPayload | null>(null);

function parseParams(): ReportRequestParams {
  const q = route.query;
  const out: ReportRequestParams = {};
  if (typeof q.run_id === "string") out.run_id = Number(q.run_id);
  if (typeof q.from === "string") out.from_date = q.from;
  if (typeof q.to === "string") out.to_date = q.to;
  if (typeof q.competitors === "string" && q.competitors.length > 0) {
    out.competitor_ids = q.competitors
      .split(",")
      .map((s) => Number(s.trim()))
      .filter((n) => !Number.isNaN(n));
  }
  if (typeof q.samples === "string") out.sample_count = Number(q.samples);
  if (typeof q.lang === "string") out.language = q.lang;
  if (q.tier === "advanced" || q.tier === "simple") out.tier = q.tier;
  return out;
}

onMounted(async () => {
  try {
    payload.value = await api.report(parseParams());
  } catch (e) {
    errorMessage.value = e instanceof ApiError ? (e.detail ?? e.message) : String(e);
  } finally {
    loading.value = false;
  }
});

const locale = computed<LocaleCode>(() => resolveLocale(payload.value?.language));
function tt(key: Parameters<typeof t>[1], vars: Record<string, string | number> = {}) {
  return t(locale.value, key, vars);
}

const period = computed(() => payload.value?.period);
const periodLabel = computed(() => {
  if (!payload.value) return "";
  const p = payload.value.period;
  if (p.kind === "run") return formatPeriodDate(p.from_date, locale.value);
  return `${formatPeriodDate(p.from_date, locale.value)} — ${formatPeriodDate(p.to_date, locale.value)}`;
});

const generatedLabel = computed(() => formatPeriodDate(new Date().toISOString(), locale.value));

const brandUrl = computed(() =>
  locale.value === "pl" ? "https://syntropicsignal.ai/pl" : "https://syntropicsignal.ai",
);

interface KpiTile {
  label: string;
  value: string;
  hint: string;
  delta: number | null;
  higherIsBetter?: boolean;
}

function positiveRate(s: { positive: number; neutral: number; negative: number }): number | null {
  const total = s.positive + s.neutral + s.negative;
  return total > 0 ? s.positive / total : null;
}

const kpis = computed<KpiTile[]>(() => {
  const p = payload.value;
  if (!p) return [];
  const m = p.metrics;
  const mp = p.metrics_prior;
  const posRate = positiveRate(p.sentiment);
  const posRatePrior = p.sentiment_prior ? positiveRate(p.sentiment_prior) : null;

  const delta = (curr: number, prior: number | null | undefined): number | null =>
    prior === null || prior === undefined ? null : (curr - prior) * 100;

  return [
    {
      label: tt("kpi_visibility"),
      value: pct(m.visibility_rate),
      hint: tt("kpi_visibility_hint"),
      delta: delta(m.visibility_rate, mp?.visibility_rate),
    },
    {
      label: tt("kpi_recommendation"),
      value: pct(m.recommendation_rate),
      hint: tt("kpi_recommendation_hint"),
      delta: delta(m.recommendation_rate, mp?.recommendation_rate),
    },
    {
      label: tt("kpi_citation"),
      value: pct(m.citation_rate),
      hint: tt("kpi_citation_hint"),
      delta: delta(m.citation_rate, mp?.citation_rate),
    },
    {
      label: tt("kpi_positive_sentiment"),
      value: posRate === null ? "—" : pct(posRate),
      hint: tt("kpi_positive_sentiment_hint"),
      delta: posRate !== null ? delta(posRate, posRatePrior) : null,
    },
  ];
});

const execSummaryLines = computed<string[]>(() => {
  const p = payload.value;
  if (!p) return [];
  const lines: string[] = [];
  const m = p.metrics;
  const total = m.total_responses;
  if (total === 0 || m.brand_mentioned === 0) {
    lines.push(tt("exec_summary_no_mentions"));
    return lines;
  }
  lines.push(
    tt("exec_summary_visibility", { pct: pct(m.visibility_rate), total }),
  );
  if (m.brand_mentioned > 0) {
    const recRate = m.brand_mentioned > 0 ? m.recommendation_rate / m.visibility_rate : 0;
    lines.push(tt("exec_summary_recommendation", { rec_pct: pct(recRate) }));
  }
  const s = p.sentiment;
  const sTotal = s.positive + s.neutral + s.negative;
  if (sTotal > 0) {
    if (s.negative > sTotal * 0.4) {
      lines.push(tt("exec_summary_sentiment_neg", { neg: s.negative, total: sTotal }));
    } else if (s.positive > sTotal * 0.6) {
      lines.push(tt("exec_summary_sentiment_pos", { pos: s.positive, total: sTotal }));
    } else {
      lines.push(
        tt("exec_summary_sentiment_mixed", {
          pos: s.positive,
          neu: s.neutral,
          neg: s.negative,
        }),
      );
    }
  }
  return lines;
});

// ----- Per-source short summaries ----------------------
// One small card per source above the existing data table. Verdict
// pill is relative to the OVERALL window visibility — "Strong" when a
// source is meaningfully above the average across sources, "Weak"
// when it's meaningfully below, "Average" for everything in between.
// Threshold is ±25% deviation, which is loose enough to not flag noise
// but tight enough to surface the kind of swing the user cares about
// (e.g. "ChatGPT 5% vs Google AI Overview 16%" — both flagged).

type SourceVerdict = "strong" | "average" | "weak" | "absent" | "no_data";

interface PerSourceSummary {
  source: string;
  source_name: string;
  verdict: SourceVerdict;
  pillLabel: string;
  pillCls: string;
  lines: string[];
}

const verdictMeta: Record<
  SourceVerdict,
  { labelKey: Parameters<typeof t>[1]; cls: string }
> = {
  strong: {
    labelKey: "per_source_pill_strong",
    cls: "verdict-pill verdict-pill--strong",
  },
  average: {
    labelKey: "per_source_pill_average",
    cls: "verdict-pill verdict-pill--average",
  },
  weak: {
    labelKey: "per_source_pill_weak",
    cls: "verdict-pill verdict-pill--weak",
  },
  absent: {
    labelKey: "per_source_pill_absent",
    cls: "verdict-pill verdict-pill--weak",
  },
  no_data: {
    labelKey: "per_source_pill_no_data",
    cls: "verdict-pill verdict-pill--no-data",
  },
};

const perSourceSummaries = computed<PerSourceSummary[]>(() => {
  const p = payload.value;
  if (!p) return [];
  const overallVis = p.metrics.visibility_rate;
  return p.by_source.map((row) => {
    const total = row.metrics.total_responses;
    const mentioned = row.metrics.brand_mentioned;
    const vis = row.metrics.visibility_rate;
    const rec = row.metrics.recommendation_rate;
    const s = row.sentiment;
    const sentTotal = s.positive + s.neutral + s.negative;

    let verdict: SourceVerdict;
    if (total === 0) verdict = "no_data";
    else if (mentioned === 0) verdict = "absent";
    else if (overallVis > 0 && vis >= overallVis * 1.25) verdict = "strong";
    else if (overallVis > 0 && vis <= overallVis * 0.75) verdict = "weak";
    else verdict = "average";

    const lines: string[] = [];
    if (verdict === "no_data") {
      lines.push(tt("per_source_summary_no_data"));
    } else if (verdict === "absent") {
      lines.push(tt("per_source_summary_absent", { total }));
    } else {
      lines.push(
        tt("per_source_summary_visibility", {
          pct: pct(vis),
          total,
          mentioned,
        }),
      );

      // Comparative clause — only show when the verdict is non-average,
      // otherwise the line just adds noise saying "we're average".
      if (verdict === "strong") {
        lines.push(
          tt("per_source_summary_above_avg", { overall_pct: pct(overallVis) }),
        );
      } else if (verdict === "weak") {
        lines.push(
          tt("per_source_summary_below_avg", { overall_pct: pct(overallVis) }),
        );
      }

      // Recommendation clause.
      if (rec > 0) {
        lines.push(tt("per_source_summary_recommendation", { rec_pct: pct(rec) }));
      } else {
        lines.push(tt("per_source_summary_no_recommendation"));
      }

      // Sentiment clause — only when at least one mention was sentiment-
      // classified. `not_mentioned` rows aren't counted in s.{positive,
      // neutral,negative}, so sentTotal == 0 means "we have mentions but
      // no classified ones" which is rare enough we just omit the line.
      if (sentTotal > 0) {
        if (s.negative > sentTotal * 0.4) {
          lines.push(
            tt("per_source_summary_sentiment_neg", {
              pos: s.positive,
              neu: s.neutral,
              neg: s.negative,
            }),
          );
        } else if (s.positive > sentTotal * 0.6) {
          lines.push(
            tt("per_source_summary_sentiment_pos", {
              pos: s.positive,
              neu: s.neutral,
            }),
          );
        } else {
          lines.push(
            tt("per_source_summary_sentiment_mixed", {
              pos: s.positive,
              neu: s.neutral,
              neg: s.negative,
            }),
          );
        }
      }
    }

    const meta = verdictMeta[verdict];
    return {
      source: row.source,
      source_name: row.source_name,
      verdict,
      pillLabel: tt(meta.labelKey),
      pillCls: meta.cls,
      lines,
    };
  });
});

// ----- Competitor bar chart -----

const competitorChartData = computed(() => {
  const rows = payload.value?.competitor_visibility ?? [];
  return {
    labels: rows.map((r) => r.brand_name),
    datasets: [
      {
        label: tt("col_visibility"),
        data: rows.map((r) => r.metrics.visibility_rate * 100),
        backgroundColor: rows.map((r) =>
          r.is_self ? "#0E7888" : "#A8B5BD",
        ),
        borderWidth: 0,
        borderRadius: 4,
        barThickness: 22,
      },
    ],
  };
});

const competitorChartOptions = computed<ChartOptions<"bar">>(() => {
  // Cap the x-axis just above the highest bar so single-digit visibility
  // rates don't render as slivers next to a 100% gridline. +10% headroom,
  // snapped to the next multiple of 5 for clean ticks; floor at 5% so an
  // all-zero dataset still renders something readable.
  const rows = payload.value?.competitor_visibility ?? [];
  const peak = Math.max(0, ...rows.map((r) => r.metrics.visibility_rate * 100));
  const axisMax = Math.max(5, Math.ceil((peak * 1.1) / 5) * 5);
  return {
    indexAxis: "y" as const,
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const v = ctx.parsed.x;
            return v == null ? "" : `${v.toFixed(1)}%`;
          },
        },
      },
    },
    scales: {
      x: {
        beginAtZero: true,
        max: axisMax,
        ticks: { callback: (v) => `${v}%`, color: "#5C5F66" },
        grid: { color: "#E2E5EA" },
      },
      y: {
        ticks: { color: "#1A1B1F", font: { weight: 500 } },
        grid: { display: false },
      },
    },
  };
});

// ----- Brand awareness helpers -----

interface SentimentGroup {
  key: "negative" | "neutral" | "positive" | "not_mentioned";
  labelKey: Parameters<typeof t>[1];
  rows: ReportPromptSentimentRow[];
  tone: "danger" | "warning" | "success" | "muted";
}

const brandAwarenessGroups = computed<SentimentGroup[]>(() => {
  const ba = payload.value?.brand_awareness;
  if (!ba) return [];
  const groups: SentimentGroup[] = [
    { key: "negative", labelKey: "group_negative", rows: ba.negative, tone: "danger" },
    { key: "neutral", labelKey: "group_neutral", rows: ba.neutral, tone: "warning" },
    { key: "positive", labelKey: "group_positive", rows: ba.positive, tone: "success" },
    {
      key: "not_mentioned",
      labelKey: "group_not_mentioned",
      rows: ba.not_mentioned,
      tone: "muted",
    },
  ];
  return groups.filter((g) => g.rows.length > 0);
});

// ----- Sample badge tone helpers -----

function sampleSentimentLabel(s: Sentiment): string {
  if (s === "positive") return tt("sample_status_positive");
  if (s === "neutral") return tt("sample_status_neutral");
  if (s === "negative") return tt("sample_status_negative");
  return tt("sample_status_not_mentioned");
}

function deltaInfo(d: number | null, higherIsBetter = true): {
  label: string;
  cls: string;
} | null {
  if (d === null) return null;
  if (Math.abs(d) < 0.05) {
    return { label: "—", cls: "text-[var(--color-fg-muted)]" };
  }
  const positive = d > 0;
  const better = higherIsBetter ? positive : !positive;
  const arrow = positive ? "↑" : "↓";
  return {
    label: `${arrow} ${Math.abs(d).toFixed(1)}`,
    cls: better ? "text-[var(--color-success)]" : "text-[var(--color-danger)]",
  };
}

function clamp(text: string, max = 600): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

// ---- Advanced-tier helpers --------------------------------------

function recKindKey(kind: string): Parameters<typeof t>[1] {
  switch (kind) {
    case "get_cited":
      return "rec_kind_get_cited";
    case "publish_comparison":
      return "rec_kind_publish_comparison";
    case "target_query":
      return "rec_kind_target_query";
    default:
      return "rec_kind_publish_content";
  }
}
</script>

<template>
  <div class="report-shell">
    <div v-if="loading" class="report-loading">Loading report…</div>
    <div v-else-if="errorMessage" class="report-error">
      <p>{{ errorMessage }}</p>
    </div>

    <article v-else-if="payload" class="report-page">
      <!-- Cover -->
      <header class="cover">
        <div class="cover-eyebrow-row">
          <p class="cover-eyebrow">{{ tt("audit_report_title") }}</p>
          <span
            class="tier-badge"
            :data-tier="payload.tier"
          >{{ payload.tier === "advanced" ? tt("tier_advanced_badge") : tt("tier_simple_badge") }}</span>
        </div>
        <h1 class="cover-title">{{ payload.self_brand.name }}</h1>
        <p v-if="payload.self_brand.domain" class="cover-domain">
          {{ payload.self_brand.domain }}
        </p>
        <dl class="cover-meta">
          <div>
            <dt>{{ tt("reporting_period") }}</dt>
            <dd>
              {{ periodLabel }}
              <span class="cover-meta-extra" v-if="period && period.kind === 'run'">
                · {{ tt("single_run_label") }}
              </span>
            </dd>
          </div>
          <div>
            <dt>{{ tt("generated_on") }}</dt>
            <dd>{{ generatedLabel }}</dd>
          </div>
        </dl>
        <p class="cover-confidential">
          <span class="cover-confidential-tag">{{ tt("confidential_badge") }}</span>
          {{ tt("confidential_notice", { brand: payload.self_brand.name }) }}
        </p>
      </header>

      <!-- Executive summary -->
      <section class="exec">
        <h2>{{ tt("exec_summary") }}</h2>
        <ul class="exec-list">
          <li v-for="(line, i) in execSummaryLines" :key="i">{{ line }}</li>
        </ul>
      </section>

      <!-- KPI block -->
      <section class="kpis">
        <div v-for="k in kpis" :key="k.label" class="kpi-tile">
          <p class="kpi-label">{{ k.label }}</p>
          <div class="kpi-value-row">
            <p class="kpi-value">{{ k.value }}</p>
            <span
              v-if="deltaInfo(k.delta, k.higherIsBetter !== false)"
              :class="['kpi-delta', deltaInfo(k.delta, k.higherIsBetter !== false)!.cls]"
            >
              {{ deltaInfo(k.delta, k.higherIsBetter !== false)!.label }}
            </span>
          </div>
          <p class="kpi-hint">{{ k.hint }}</p>
          <p
            v-if="payload.metrics_prior && deltaInfo(k.delta, k.higherIsBetter !== false)"
            class="kpi-prior"
          >
            {{ tt("vs_prior_period") }}
          </p>
        </div>
      </section>

      <!-- Brand awareness -->
      <section class="awareness page-break-before-some">
        <header class="section-header">
          <h2>{{ tt("brand_awareness_title") }}</h2>
          <p class="section-description">{{ tt("brand_awareness_description") }}</p>
        </header>
        <div v-if="payload.brand_awareness.total_brand_prompts === 0" class="awareness-empty">
          {{ tt("no_brand_intent_prompts") }}
        </div>
        <template v-else>
          <p class="awareness-summary">
            {{
              tt("brand_awareness_summary", {
                prompts: payload.brand_awareness.total_brand_prompts,
                responses: payload.brand_awareness.total_responses,
                pos: payload.brand_awareness.sentiment_counts.positive,
                neu: payload.brand_awareness.sentiment_counts.neutral,
                neg: payload.brand_awareness.sentiment_counts.negative,
                rec_pct: pct(payload.brand_awareness.recommendation_rate),
              })
            }}
          </p>
          <div
            v-for="g in brandAwarenessGroups"
            :key="g.key"
            class="awareness-group"
            :data-tone="g.tone"
          >
            <div class="awareness-group-header">
              <span class="awareness-group-dot" />
              <h3>{{ tt(g.labelKey) }}</h3>
              <span class="awareness-group-count">{{ g.rows.length }}</span>
            </div>
            <ul class="awareness-list">
              <li v-for="r in g.rows" :key="r.prompt_id" class="awareness-row">
                <span class="awareness-prompt">{{ r.text }}</span>
                <span class="awareness-counts">
                  <span v-if="r.sentiment_counts.positive > 0" class="count count-pos"
                    >{{ r.sentiment_counts.positive }} +</span
                  >
                  <span v-if="r.sentiment_counts.neutral > 0" class="count count-neu"
                    >{{ r.sentiment_counts.neutral }} ~</span
                  >
                  <span v-if="r.sentiment_counts.negative > 0" class="count count-neg"
                    >{{ r.sentiment_counts.negative }} −</span
                  >
                  <span v-if="r.recommended_count > 0" class="count count-rec">
                    ✓ {{ r.recommended_count }}
                  </span>
                </span>
              </li>
            </ul>
          </div>
        </template>
      </section>

      <!-- Per-source -->
      <section class="per-source">
        <header class="section-header">
          <h2>{{ tt("per_source_title") }}</h2>
          <p class="section-description">{{ tt("per_source_description") }}</p>
        </header>
        <!-- Short narrative summaries. Sit above the data table
             so a reader gets a one-paragraph read on each source before
             the numerical detail. -->
        <div class="per-source-summaries" v-if="perSourceSummaries.length > 0">
          <article
            v-for="s in perSourceSummaries"
            :key="s.source"
            class="per-source-card"
            :data-verdict="s.verdict"
          >
            <header class="per-source-card-head">
              <h3>{{ s.source_name }}</h3>
              <span :class="s.pillCls">{{ s.pillLabel }}</span>
            </header>
            <p v-for="(line, i) in s.lines" :key="i" class="per-source-card-line">
              {{ line }}
            </p>
          </article>
        </div>
        <table class="report-table">
          <thead>
            <tr>
              <th>{{ tt("col_source") }}</th>
              <th class="num">{{ tt("col_responses") }}</th>
              <th class="num">{{ tt("col_visibility") }}</th>
              <th class="num">{{ tt("col_citation") }}</th>
              <th>{{ tt("col_sentiment") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in payload.by_source" :key="r.source">
              <td>{{ r.source_name }}</td>
              <td class="num">{{ r.metrics.total_responses }}</td>
              <td class="num">{{ pct(r.metrics.visibility_rate) }}</td>
              <td class="num">{{ pct(r.metrics.citation_rate) }}</td>
              <td>
                <span class="sent-pills">
                  <span v-if="r.sentiment.positive > 0" class="sent-pill pos">{{ r.sentiment.positive }}+</span>
                  <span v-if="r.sentiment.neutral > 0" class="sent-pill neu">{{ r.sentiment.neutral }}~</span>
                  <span v-if="r.sentiment.negative > 0" class="sent-pill neg">{{ r.sentiment.negative }}−</span>
                  <span
                    v-if="r.sentiment.positive + r.sentiment.neutral + r.sentiment.negative === 0"
                    class="sent-empty"
                    >—</span
                  >
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Top cited domains -->
      <section class="citations">
        <header class="section-header">
          <h2>{{ tt("citations_title") }}</h2>
          <p class="section-description">{{ tt("citations_description") }}</p>
        </header>
        <table class="report-table" v-if="payload.citations.length > 0">
          <thead>
            <tr>
              <th>{{ tt("col_domain") }}</th>
              <th class="num">{{ tt("col_citations") }}</th>
              <th class="num">{{ tt("col_share") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in payload.citations" :key="c.domain" :class="{ 'self-row': c.is_self }">
              <td>
                <span class="mono">{{ c.domain }}</span>
                <span v-if="c.is_self" class="self-pill">{{ tt("badge_you") }}</span>
                <span v-else-if="c.brand_name" class="brand-pill">{{ c.brand_name }}</span>
              </td>
              <td class="num">{{ c.citation_count }}</td>
              <td class="num">{{ pct(c.share) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Citation gap (advanced) -->
      <section
        v-if="payload.tier === 'advanced' && payload.citation_gap.length > 0"
        class="adv citation-gap"
      >
        <header class="section-header">
          <h2>{{ tt("citation_gap_title") }}</h2>
          <p class="section-description">{{ tt("citation_gap_description") }}</p>
        </header>
        <table class="report-table">
          <thead>
            <tr>
              <th>{{ tt("col_domain") }}</th>
              <th>{{ tt("col_brand") }}</th>
              <th class="num">{{ tt("col_citations") }}</th>
              <th class="num">{{ tt("col_share") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in payload.citation_gap" :key="d.domain">
              <td><span class="mono">{{ d.domain }}</span></td>
              <td>
                <span v-if="d.brand_name" class="brand-pill">{{ d.brand_name }}</span>
                <span v-else class="third-party-label">{{ tt("citation_gap_owner_third_party") }}</span>
              </td>
              <td class="num">{{ d.citation_count }}</td>
              <td class="num">{{ pct(d.share, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Competitor visibility -->
      <section class="competitor page-break-before-some">
        <header class="section-header">
          <h2>{{ tt("competitor_title") }}</h2>
          <p class="section-description">{{ tt("competitor_description") }}</p>
        </header>
        <div
          class="competitor-chart"
          :style="{ height: `${Math.max(160, payload.competitor_visibility.length * 38)}px` }"
        >
          <Bar :data="competitorChartData" :options="competitorChartOptions" />
        </div>
        <table class="report-table compact">
          <thead>
            <tr>
              <th>{{ tt("col_brand") }}</th>
              <th class="num">{{ tt("col_mentions") }}</th>
              <th class="num">{{ tt("col_visibility") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in payload.competitor_visibility"
              :key="r.brand_id"
              :class="{ 'self-row': r.is_self }"
            >
              <td>
                {{ r.brand_name }}
                <span v-if="r.is_self" class="self-pill">{{ tt("badge_you") }}</span>
              </td>
              <td class="num">{{ r.metrics.brand_mentioned }}</td>
              <td class="num">{{ pct(r.metrics.visibility_rate) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Recommendations / top opportunities (advanced) -->
      <section
        v-if="payload.tier === 'advanced' && payload.recommendations.length > 0"
        class="adv recs-section page-break-before-some"
      >
        <header class="section-header">
          <h2>{{ tt("recs_title") }}</h2>
          <p class="section-description">{{ tt("recs_description") }}</p>
        </header>
        <article
          v-for="r in payload.recommendations"
          :key="r.prompt_id"
          class="rec-card"
        >
          <div class="rec-card-head">
            <span class="rec-kind-pill" :data-kind="r.recommendation_kind">
              {{ tt(recKindKey(r.recommendation_kind)) }}
            </span>
            <span class="rec-intent-pill">{{ r.intent }}</span>
            <span class="rec-counts">
              {{ r.self_mentioned_count }}/{{ r.self_total_responses }} you ·
              {{ r.top_competitor.mention_count }} {{ r.top_competitor.brand_name }}
            </span>
            <span class="rec-score">
              <span class="rec-score-label">{{ tt("recs_score_label") }}</span>
              <span class="rec-score-value">{{ pct(r.opportunity_score, 0) }}</span>
            </span>
          </div>
          <p class="rec-prompt">"{{ r.prompt_text }}"</p>
          <p class="rec-text">{{ r.recommendation_text }}</p>
          <div v-if="r.cited_domains.length > 0" class="rec-domains">
            <span
              v-for="d in r.cited_domains.slice(0, 4)"
              :key="d"
              class="rec-domain mono"
            >{{ d }}</span>
          </div>
        </article>
      </section>

      <!-- Search-term frequency (advanced) -->
      <section
        v-if="payload.tier === 'advanced' && payload.search_terms.length > 0"
        class="adv search-terms-section"
      >
        <header class="section-header">
          <h2>{{ tt("search_terms_title") }}</h2>
          <p class="section-description">{{ tt("search_terms_description") }}</p>
        </header>
        <table class="report-table">
          <thead>
            <tr>
              <th>{{ tt("col_term") }}</th>
              <th class="num">{{ tt("col_count") }}</th>
              <th class="num">{{ tt("col_prompts") }}</th>
              <th class="num">{{ tt("col_sources") }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="term in payload.search_terms" :key="term.term">
              <td><span class="mono">{{ term.term }}</span></td>
              <td class="num">{{ term.count }}</td>
              <td class="num">{{ term.prompt_count }}</td>
              <td class="num">{{ term.source_count }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- Samples -->
      <section v-if="payload.samples.length > 0" class="samples page-break-before-some">
        <header class="section-header">
          <h2>{{ tt("samples_title") }}</h2>
          <p class="section-description">{{ tt("samples_description") }}</p>
        </header>
        <article v-for="s in payload.samples" :key="s.response_id" class="sample">
          <div class="sample-meta">
            <span class="sample-meta-label">{{ tt("sample_source_label") }}:</span>
            <span class="sample-source">{{ s.source_name }}</span>
            <span
              v-if="s.brand_found"
              class="sample-pill"
              :data-tone="
                s.sentiment === 'positive'
                  ? 'success'
                  : s.sentiment === 'negative'
                  ? 'danger'
                  : 'warning'
              "
            >{{ sampleSentimentLabel(s.sentiment) }}</span>
            <span v-if="s.recommended" class="sample-pill" data-tone="accent">{{
              tt("sample_status_recommended")
            }}</span>
          </div>
          <p class="sample-prompt">
            <span class="sample-prompt-label">{{ tt("sample_prompt_label") }}:</span>
            {{ s.prompt_text }}
          </p>
          <p class="sample-text">{{ clamp(s.response_text) }}</p>
          <p v-if="s.cited_domains.length > 0" class="sample-cited">
            {{ tt("sample_cited_label") }}:
            <span class="mono" v-for="(d, i) in s.cited_domains" :key="d">{{
              i > 0 ? " · " : ""
            }}{{ d }}</span>
          </p>
        </article>
      </section>

      <!-- Footer -->
      <footer class="report-footer">
        <p class="footer-confidential">{{ tt("confidential_footer") }}</p>
        <p class="footer-credit">
          <span class="footer-prefix">{{ tt("prepared_with") }}</span>
          <a class="footer-brand" :href="brandUrl" target="_blank" rel="noopener"
            ><span class="footer-brand-syntropic">Syntropic</span><span
              class="footer-brand-product"
              >{{ tt("product_label") }}</span
            ></a
          >
        </p>
      </footer>
    </article>
  </div>
</template>

<style scoped>
/* ------------------------------------------------------------------
   Print + screen layout.

   - On screen: white page on a neutral backdrop, centered, A4-ish width.
   - On print: page renders edge to edge with @page margins controlled
     by the user agent. We disable shadows and the screen backdrop so the
     PDF doesn't carry app chrome.
   ------------------------------------------------------------------ */

@page {
  size: A4;
  margin: 16mm 14mm;
}

.report-shell {
  background: var(--color-bg);
  min-height: 100vh;
  padding: 32px 0;
  color: var(--color-fg);
}

.report-page {
  background: #ffffff;
  width: 210mm;
  min-height: 297mm;
  margin: 0 auto;
  padding: 22mm 18mm;
  box-shadow: 0 6px 24px rgba(20, 23, 32, 0.08);
  display: flex;
  flex-direction: column;
  gap: 14mm;
}

.report-loading,
.report-error {
  text-align: center;
  padding: 64px 24px;
  color: var(--color-fg-2);
}
.report-error {
  color: var(--color-danger);
}

/* Cover */
.cover {
  border-bottom: 1px solid var(--color-line);
  padding-bottom: 8mm;
}
.cover-eyebrow-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.cover-eyebrow {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--color-fg-muted);
  font-weight: 600;
  margin: 0;
}
.tier-badge {
  font-size: 9.5px;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 3px;
  border: 1px solid var(--color-line);
  color: var(--color-fg-2);
}
.tier-badge[data-tier="advanced"] {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-color: color-mix(in oklab, var(--color-warning) 30%, transparent);
}
.cover-title {
  font-family: var(--font-display);
  font-size: 38px;
  letter-spacing: -0.02em;
  font-weight: 500;
  margin: 0;
  line-height: 1.05;
}
.cover-domain {
  font-family: var(--font-mono);
  color: var(--color-fg-2);
  font-size: 13px;
  margin-top: 8px;
}
.cover-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-top: 18px;
  font-size: 13.5px;
}
.cover-meta dt {
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-fg-muted);
  font-weight: 600;
  margin-bottom: 4px;
}
.cover-meta dd {
  margin: 0;
  color: var(--color-fg);
  font-weight: 500;
}
.cover-confidential {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 14mm 0 0;
  padding: 8px 10px;
  border-left: 2px solid #d4a853;
  background: color-mix(in oklab, #d4a853 10%, transparent);
  font-size: 11px;
  line-height: 1.4;
  color: var(--color-fg-2);
}
.cover-confidential-tag {
  flex-shrink: 0;
  font-size: 9.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-weight: 700;
  color: #8a6c2a;
}
.cover-meta-extra {
  color: var(--color-fg-muted);
  font-weight: 400;
}

/* Section header */
.section-header {
  margin-bottom: 8mm;
}
.section-header h2,
.exec h2,
.awareness h2 {
  font-family: var(--font-display);
  font-size: 22px;
  letter-spacing: -0.015em;
  font-weight: 500;
  margin: 0 0 4px 0;
}
.section-description {
  color: var(--color-fg-2);
  font-size: 13.5px;
  margin: 0;
}

/* Exec summary */
.exec-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.exec-list li {
  font-size: 14.5px;
  line-height: 1.5;
  color: var(--color-fg);
  padding-left: 18px;
  position: relative;
}
.exec-list li::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 2px;
  background: var(--color-accent);
  position: absolute;
  left: 0;
  top: 7px;
}

/* KPIs */
.kpis {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 10px;
}
.kpi-tile {
  border: 1px solid var(--color-line);
  border-radius: 8px;
  padding: 14px 14px 12px;
  background: #fff;
}
.kpi-label {
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-fg-muted);
  font-weight: 600;
  margin: 0 0 10px 0;
}
.kpi-value-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.kpi-value {
  font-family: var(--font-display);
  font-variation-settings: "opsz" 144;
  font-size: 30px;
  letter-spacing: -0.03em;
  line-height: 1;
  margin: 0;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
}
.kpi-delta {
  font-size: 11.5px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.kpi-hint {
  font-size: 11.5px;
  color: var(--color-fg-muted);
  margin: 8px 0 0 0;
  line-height: 1.35;
}
.kpi-prior {
  font-size: 10px;
  color: var(--color-fg-muted);
  margin: 4px 0 0 0;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

/* Brand awareness */
.awareness-empty {
  font-size: 14px;
  color: var(--color-fg-muted);
  padding: 20px;
  border: 1px dashed var(--color-line);
  border-radius: 8px;
  text-align: center;
}
.awareness-summary {
  font-size: 13.5px;
  color: var(--color-fg-2);
  margin: 0 0 14px 0;
}
.awareness-group {
  margin-top: 14px;
}
.awareness-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.awareness-group-dot {
  width: 8px;
  height: 8px;
  border-radius: 99px;
}
.awareness-group[data-tone="danger"] .awareness-group-dot { background: var(--color-danger); }
.awareness-group[data-tone="warning"] .awareness-group-dot { background: var(--color-warning); }
.awareness-group[data-tone="success"] .awareness-group-dot { background: var(--color-success); }
.awareness-group[data-tone="muted"] .awareness-group-dot { background: var(--color-fg-muted); }

.awareness-group h3 {
  font-family: var(--font-sans);
  font-size: 13px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  font-weight: 700;
  color: var(--color-fg);
  margin: 0;
}
.awareness-group[data-tone="danger"] h3 { color: var(--color-danger); }
.awareness-group[data-tone="warning"] h3 { color: var(--color-warning); }
.awareness-group[data-tone="success"] h3 { color: var(--color-success); }
.awareness-group[data-tone="muted"] h3 { color: var(--color-fg-muted); }

.awareness-group-count {
  font-size: 11px;
  color: var(--color-fg-muted);
  font-variant-numeric: tabular-nums;
}

.awareness-list {
  list-style: none;
  margin: 0;
  padding: 0;
  border-top: 1px solid var(--color-line);
}
.awareness-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--color-line);
  font-size: 13.5px;
}
.awareness-prompt {
  flex: 1;
  min-width: 0;
}
.awareness-counts {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  font-size: 11.5px;
}
.count {
  border-radius: 4px;
  padding: 1px 6px;
  font-weight: 600;
}
.count-pos { background: var(--color-success-soft); color: var(--color-success); }
.count-neu { background: var(--color-surface-2); color: var(--color-fg-2); }
.count-neg { background: var(--color-danger-soft); color: var(--color-danger); }
.count-rec { background: var(--color-accent-soft); color: var(--color-accent); }

/* Per-source narrative cards. Two-column grid on the page so
   four sources fit in two rows; each card collapses to a paragraph
   feel — a thin left border in the verdict colour, the source name +
   a small pill, and 1–4 short lines of prose. Mirrors the executive-
   summary voice used elsewhere in the report. */
.per-source-summaries {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
  margin-bottom: 14px;
}
.per-source-card {
  border: 1px solid var(--color-line);
  border-left-width: 3px;
  border-left-color: var(--color-fg-muted);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--color-bg);
  break-inside: avoid;
}
.per-source-card[data-verdict="strong"] {
  border-left-color: var(--color-success);
}
.per-source-card[data-verdict="weak"],
.per-source-card[data-verdict="absent"] {
  border-left-color: var(--color-danger);
}
.per-source-card[data-verdict="average"] {
  border-left-color: var(--color-accent);
}
.per-source-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.per-source-card-head h3 {
  font-size: 13.5px;
  font-weight: 600;
  margin: 0;
  color: var(--color-fg);
}
.per-source-card-line {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--color-fg-2);
}
.per-source-card-line + .per-source-card-line {
  margin-top: 2px;
}
.verdict-pill {
  font-size: 9.5px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
}
.verdict-pill--strong {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.verdict-pill--weak {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}
.verdict-pill--average {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
.verdict-pill--no-data {
  background: var(--color-surface-2);
  color: var(--color-fg-muted);
}

/* Tables */
.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.report-table thead th {
  text-align: left;
  font-size: 10.5px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--color-fg-muted);
  font-weight: 700;
  padding: 6px 8px;
  border-bottom: 1px solid var(--color-line-strong);
}
.report-table th.num,
.report-table td.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.report-table tbody td {
  padding: 9px 8px;
  border-bottom: 1px solid var(--color-line);
  color: var(--color-fg);
  vertical-align: middle;
}
.report-table tbody tr:last-child td {
  border-bottom: none;
}
.report-table.compact tbody td {
  padding: 7px 8px;
}
.report-table tbody tr.self-row td {
  background: var(--color-accent-soft);
  font-weight: 600;
}

.mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.self-pill {
  display: inline-block;
  margin-left: 6px;
  background: var(--color-accent);
  color: #fff;
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 10px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-weight: 600;
  vertical-align: middle;
}
.brand-pill {
  display: inline-block;
  margin-left: 6px;
  background: var(--color-info-soft);
  color: var(--color-info);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 500;
  vertical-align: middle;
}

.sent-pills {
  display: inline-flex;
  gap: 4px;
}
.sent-pill {
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 6px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.sent-pill.pos { background: var(--color-success-soft); color: var(--color-success); }
.sent-pill.neu { background: var(--color-surface-2); color: var(--color-fg-2); }
.sent-pill.neg { background: var(--color-danger-soft); color: var(--color-danger); }
.sent-empty {
  font-size: 11px;
  color: var(--color-fg-muted);
}

/* Competitor chart */
.competitor-chart {
  margin: 0 0 16px 0;
  padding: 14px 4px;
  border: 1px solid var(--color-line);
  border-radius: 8px;
  background: #fff;
}

/* Samples */
.sample {
  border: 1px solid var(--color-line);
  border-radius: 8px;
  padding: 14px 16px;
  margin-top: 12px;
  break-inside: avoid;
  page-break-inside: avoid;
}
.sample-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 8px;
  font-size: 12.5px;
}
.sample-meta-label {
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--color-fg-muted);
  font-size: 10.5px;
  font-weight: 600;
}
.sample-source {
  color: var(--color-fg);
  font-weight: 600;
}
.sample-pill {
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.sample-pill[data-tone="success"] { background: var(--color-success-soft); color: var(--color-success); }
.sample-pill[data-tone="danger"]  { background: var(--color-danger-soft);  color: var(--color-danger); }
.sample-pill[data-tone="warning"] { background: var(--color-warning-soft); color: var(--color-warning); }
.sample-pill[data-tone="accent"]  { background: var(--color-accent-soft);  color: var(--color-accent); }

.sample-prompt {
  font-size: 13px;
  color: var(--color-fg);
  margin: 0 0 10px 0;
}
.sample-prompt-label {
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-size: 10.5px;
  font-weight: 600;
  color: var(--color-fg-muted);
  margin-right: 6px;
}
.sample-text {
  font-size: 13px;
  line-height: 1.55;
  color: var(--color-fg-2);
  white-space: pre-wrap;
  margin: 0;
}
.sample-cited {
  font-size: 11.5px;
  color: var(--color-fg-muted);
  margin: 8px 0 0 0;
}

/* Advanced-tier sections: thin accent rule on the section header. */
.adv > .section-header {
  border-left: 2px solid var(--color-accent);
  padding-left: 10px;
}

/* Citation gap — extra "third-party" label style */
.third-party-label {
  font-size: 11px;
  font-style: italic;
  color: var(--color-fg-muted);
}

/* Recommendations — card list */
.rec-card {
  border: 1px solid var(--color-line);
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 10px;
  break-inside: avoid;
  page-break-inside: avoid;
}
.rec-card-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 6px;
}
.rec-kind-pill {
  font-size: 9.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  padding: 2px 7px;
  border-radius: 3px;
}
.rec-kind-pill[data-kind="get_cited"] {
  background: var(--color-highlight-soft);
  color: var(--color-highlight);
}
.rec-kind-pill[data-kind="publish_comparison"] {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}
.rec-kind-pill[data-kind="target_query"] {
  background: var(--color-info-soft);
  color: var(--color-info);
}
.rec-kind-pill[data-kind="publish_content"] {
  background: var(--color-success-soft);
  color: var(--color-success);
}
.rec-intent-pill {
  font-size: 10px;
  font-weight: 500;
  padding: 1px 6px;
  border-radius: 3px;
  border: 1px solid var(--color-line);
  color: var(--color-fg-2);
  text-transform: capitalize;
}
.rec-counts {
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: var(--color-fg-muted);
}
.rec-score {
  margin-left: auto;
  display: flex;
  align-items: baseline;
  gap: 5px;
}
.rec-score-label {
  font-size: 9.5px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--color-fg-muted);
  font-weight: 600;
}
.rec-score-value {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  color: var(--color-accent);
}
.rec-prompt {
  font-style: italic;
  font-size: 13px;
  color: var(--color-fg);
  margin: 4px 0 6px 0;
}
.rec-text {
  font-size: 12.5px;
  color: var(--color-fg-2);
  margin: 0 0 6px 0;
  line-height: 1.5;
}
.rec-domains {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.rec-domain {
  font-size: 10.5px;
  color: var(--color-fg-muted);
  padding: 1px 6px;
  border-radius: 3px;
  background: var(--color-surface-2);
}

/* Footer */
.report-footer {
  margin-top: 14mm;
  padding-top: 6mm;
  border-top: 1px solid var(--color-line);
  text-align: center;
  font-size: 11px;
  color: var(--color-fg-muted);
}
.footer-confidential {
  margin: 0 0 4mm;
  font-size: 9.5px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  font-weight: 600;
  color: var(--color-fg-muted);
}
.footer-credit {
  margin: 0;
}
.footer-prefix {
  color: var(--color-fg-muted);
  margin-right: 0.4em;
}
.footer-brand {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  text-decoration: none;
}
.footer-brand-syntropic {
  color: #d4a853;
}
.footer-brand-product {
  color: #0e2640;
  margin-left: 0.5em;
}
.footer-brand:hover {
  text-decoration: underline;
}

/* Page-break hints — apply to sections that should ideally start fresh
   when there's not enough space. The "some" suffix is a reminder that
   it's a hint, not a guarantee — the renderer can override. */
.page-break-before-some {
  break-before: auto;
  page-break-inside: avoid;
}

/* Print overrides */
@media print {
  .report-shell {
    background: #fff;
    padding: 0;
  }
  .report-page {
    box-shadow: none;
    width: 100%;
    margin: 0;
    padding: 0;
    min-height: auto;
  }
}
</style>
