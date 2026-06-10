<script setup lang="ts">
/**
 * Topics.
 *
 * Aggregates prompt performance by tag or intent and exposes per-cluster:
 *   - hit rate (mentions / responses)
 *   - share of voice (self mentions / total brand mentions in cluster)
 *   - dominant non-self competitor + their mention count
 *   - recommendation rate, sentiment
 *
 * SOV is the second-most-important number in this view — it answers
 * "when the AI does mention a brand for this topic, how often is it us?"
 * — distinct from hit rate's "do I appear at all?" Without it we can't
 * distinguish a topic the brand owns (low hit rate, high SOV) from one
 * where it's drowned out (low hit rate, low SOV).
 */
import { computed, onMounted, ref, watch } from "vue";
import { Loader2 } from "lucide-vue-next";
import { api, ApiError } from "@/api/client";
import type { TopicGraph, TopicStat } from "@/api/types";
import { pct } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";
import TopicsSankey from "@/components/TopicsSankey.vue";

const toasts = useToasts();

const loading = ref(true);
const graphLoading = ref(false);
const topics = ref<TopicStat[]>([]);
const graph = ref<TopicGraph | null>(null);
const dimension = ref<"tag" | "intent">("tag");
const view = ref<"table" | "graph">("table");
// Topic selected by clicking a graph node — filters the table when set.
// `null` = no filter.
const selectedTopic = ref<string | null>(null);

async function load() {
  loading.value = true;
  try {
    topics.value = await api.topics({ dimension: dimension.value });
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load");
  } finally {
    loading.value = false;
  }
}

async function loadGraph() {
  graphLoading.value = true;
  try {
    graph.value = await api.topicsGraph({ dimension: dimension.value });
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load graph");
  } finally {
    graphLoading.value = false;
  }
}

watch(dimension, () => {
  selectedTopic.value = null;
  load();
  if (view.value === "graph") loadGraph();
});

watch(view, (v) => {
  if (v === "graph" && graph.value === null) loadGraph();
});

function onSelectTopicFromGraph(topic: string | null) {
  selectedTopic.value = topic;
}

function hitRateColor(rate: number): string {
  if (rate > 0.6) return "var(--color-success)";
  if (rate > 0.2) return "var(--color-accent)";
  return "var(--color-danger)";
}

function sovColor(sov: number): string {
  if (sov > 0.5) return "var(--color-success)";
  if (sov > 0.2) return "var(--color-accent)";
  return "var(--color-danger)";
}

// Heuristic: a topic is a "win" when self brand has SOV > 50% (we own
// the conversation), a "loss" when SOV < 15% AND a clear competitor
// exists (someone else owns it). Everything else is "contested" —
// the AI mentions multiple brands roughly equally for these.
type Verdict = "win" | "loss" | "contested" | "no_data";

function verdictFor(row: TopicStat): Verdict {
  if (row.total_brand_mentions === 0) return "no_data";
  if (row.share_of_voice >= 0.5) return "win";
  if (row.share_of_voice < 0.15 && row.top_competitor !== null) return "loss";
  return "contested";
}

const verdictMeta: Record<Verdict, { label: string; cls: string }> = {
  win: { label: "Win", cls: "bg-[var(--color-success-soft)] text-[var(--color-success)]" },
  loss: { label: "Lose", cls: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]" },
  contested: { label: "Contested", cls: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]" },
  no_data: { label: "—", cls: "text-[var(--color-fg-muted)]" },
};

const ordered = computed(() => {
  const all = [...topics.value].sort((a, b) => b.total_responses - a.total_responses);
  if (selectedTopic.value === null) return all;
  return all.filter((row) => row.topic === selectedTopic.value);
});

onMounted(load);
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("topics.title") }}</h1>
      <p class="dek mt-1">
        {{ t("topics.dek", { by: dimension === "tag" ? t("topics.by_tag") : t("topics.by_intent") }) }}
      </p>
    </div>
    <div class="flex items-center gap-2">
      <div class="inline-flex items-center border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] overflow-hidden">
        <button
          v-for="opt in (['tag', 'intent'] as const)"
          :key="opt"
          type="button"
          @click="dimension = opt"
          :class="[
            'py-[5px] px-2.5 transition-colors border-r border-[var(--color-line)] last:border-r-0 capitalize',
            dimension === opt
              ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] font-medium'
              : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
          ]"
        >{{ opt === "tag" ? t("topics.toggle.tag") : t("topics.toggle.intent") }}</button>
      </div>
      <div class="inline-flex items-center border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] overflow-hidden">
        <button
          v-for="opt in (['table', 'graph'] as const)"
          :key="opt"
          type="button"
          @click="view = opt"
          :class="[
            'py-[5px] px-2.5 transition-colors border-r border-[var(--color-line)] last:border-r-0 capitalize',
            view === opt
              ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] font-medium'
              : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
          ]"
        >{{ opt }}</button>
      </div>
    </div>
  </div>

  <!-- Active topic filter chip — appears when a graph node has been clicked.
       Clicking the chip clears the filter and shows all rows again. -->
  <div v-if="selectedTopic" class="mb-3">
    <button
      type="button"
      class="inline-flex items-center gap-1.5 text-[11px] font-mono uppercase tracking-wider px-2 py-1 rounded bg-[var(--color-accent-soft)] text-[var(--color-accent)] hover:opacity-80"
      @click="selectedTopic = null"
    >
      Filtered to: {{ selectedTopic }}
      <span class="text-[10px]">✕</span>
    </button>
  </div>

  <!-- Graph view -->
  <TopicsSankey
    v-if="view === 'graph'"
    :data="graph"
    :loading="graphLoading"
    @select-topic="onSelectTopicFromGraph"
  />

  <!-- Table view -->
  <div v-else-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <p
    v-else-if="ordered.length === 0"
    class="text-sm text-[var(--color-fg-muted)] text-center py-12"
  >No data yet — run a benchmark first to populate topics.</p>

  <section
    v-else
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
  >
    <table class="w-full border-collapse text-[13px]">
      <thead>
        <tr class="bg-[var(--color-bg)]">
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">
            {{ dimension === "tag" ? "Tag" : "Intent" }}
          </th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">
            Verdict
          </th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Prompts</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Resp.</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono" title="% of responses in this topic that mention you">Hit rate</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono" title="Of all brand mentions in this topic, what % is you. Distinct from hit rate.">SOV</th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Top competitor</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Recommend</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Sentiment</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in ordered" :key="row.topic" class="hover:bg-[var(--color-bg)]">
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <span
              class="inline-flex items-center py-0.5 px-2 border border-[var(--color-line)] rounded text-[12px] font-medium text-[var(--color-fg)] capitalize"
            >{{ row.topic }}</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <span
              class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-mono uppercase tracking-wider"
              :class="verdictMeta[verdictFor(row)].cls"
            >{{ verdictMeta[verdictFor(row)].label }}</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ row.prompt_count }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ row.total_responses }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            <div class="flex items-center gap-2 justify-end">
              <span class="w-[60px] h-[6px] rounded-[3px] bg-[var(--color-surface-3)] overflow-hidden inline-block">
                <span
                  class="block h-full rounded-[3px]"
                  :style="{ width: `${row.hit_rate * 100}%`, background: hitRateColor(row.hit_rate) }"
                />
              </span>
              <span class="min-w-[36px] inline-block">{{ pct(row.hit_rate, 0) }}</span>
            </div>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            <div v-if="row.total_brand_mentions > 0" class="flex items-center gap-2 justify-end">
              <span class="w-[60px] h-[6px] rounded-[3px] bg-[var(--color-surface-3)] overflow-hidden inline-block">
                <span
                  class="block h-full rounded-[3px]"
                  :style="{ width: `${row.share_of_voice * 100}%`, background: sovColor(row.share_of_voice) }"
                />
              </span>
              <span class="min-w-[36px] inline-block">{{ pct(row.share_of_voice, 0) }}</span>
            </div>
            <span v-else class="text-[var(--color-fg-muted)]">—</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <div v-if="row.top_competitor" class="flex flex-col gap-0.5">
              <span class="text-[12px] text-[var(--color-fg)]">{{ row.top_competitor.brand_name }}</span>
              <span class="font-mono text-[11px] text-[var(--color-fg-muted)]">
                {{ row.top_competitor.mention_count }} / {{ row.total_brand_mentions }} mentions
              </span>
            </div>
            <span v-else class="text-[var(--color-fg-muted)]">—</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            {{ pct(row.recommendation_rate, 0) }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] text-right tabular-nums">
            <span
              v-if="row.sentiment.positive + row.sentiment.neutral + row.sentiment.negative > 0"
              class="inline-flex gap-1 text-[11px] font-mono"
            >
              <span v-if="row.sentiment.positive > 0" class="text-[var(--color-success)] font-semibold">{{ row.sentiment.positive }}+</span>
              <span v-if="row.sentiment.neutral > 0" class="text-[var(--color-fg-2)]">{{ row.sentiment.neutral }}~</span>
              <span v-if="row.sentiment.negative > 0" class="text-[var(--color-danger)] font-semibold">{{ row.sentiment.negative }}−</span>
            </span>
            <span v-else class="text-[var(--color-fg-muted)] text-[11px]">—</span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
