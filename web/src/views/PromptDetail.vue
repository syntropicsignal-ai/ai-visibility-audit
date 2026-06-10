<script setup lang="ts">
/**
 * Single prompt detail.
 *
 * Three views in one screen:
 *   1. Headline metrics for this prompt across all runs
 *   2. Per-source breakdown — does Bright Data mention us, but not DataForSEO?
 *   3. Recent responses to skim — click to drill into the full response
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { Loader2, ArrowLeft } from "lucide-vue-next";
import {
  Button,
  Card,
  CardHeader,
  Badge,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui";
import LineChart from "@/components/LineChart.vue";
import { api, ApiError } from "@/api/client";
import type { PromptDetail, Sentiment } from "@/api/types";
import { num, pct, shortDate, timeAgo } from "@/lib/format";
import { useToasts } from "@/stores/toasts";
import { chartPalette } from "@/design/tokens";

const props = defineProps<{ id: string }>();

const toasts = useToasts();
const router = useRouter();

const detail = ref<PromptDetail | null>(null);
const loading = ref(true);

async function load() {
  loading.value = true;
  try {
    detail.value = await api.getPromptDetail(Number(props.id));
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      toasts.error("Prompt not found");
      router.replace("/prompts");
      return;
    }
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load prompt");
  } finally {
    loading.value = false;
  }
}

watch(() => props.id, load);
onMounted(load);

const chartLabels = computed(() =>
  (detail.value?.trend ?? []).map((p) => shortDate(p.started_at)),
);

const chartSeries = computed(() => [
  {
    label: "Hit rate",
    color: chartPalette[0],
    data: (detail.value?.trend ?? []).map((p) => p.hit_rate * 100),
  },
]);

function sentimentTone(s: Sentiment): "success" | "danger" | "neutral" {
  if (s === "positive") return "success";
  if (s === "negative") return "danger";
  return "neutral";
}

function openResponse(runId: number, responseId: number) {
  router.push({
    path: "/responses",
    query: { run: String(runId), response: String(responseId) },
  });
}
</script>

<template>
  <header class="mb-7">
    <Button
      variant="ghost"
      size="sm"
      class="-ml-2 mb-2"
      @click="router.push('/prompts')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Back to prompts
    </Button>
    <p class="label-eyebrow">Prompt</p>
    <h1 v-if="detail" class="font-display text-2xl tracking-tight mt-1 leading-tight max-w-3xl">
      {{ detail.text }}
    </h1>
    <div v-if="detail" class="flex items-center gap-2 mt-3 flex-wrap">
      <Badge tone="accent">{{ detail.intent }}</Badge>
      <Badge v-for="t in detail.tags" :key="t" tone="neutral">{{ t }}</Badge>
      <Badge v-if="!detail.enabled" tone="warning">disabled</Badge>
    </div>
  </header>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <template v-else-if="detail">
    <!-- KPI tiles -->
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
      <Card compact>
        <p class="label-eyebrow">Hit rate</p>
        <p class="display-num mt-3">{{ pct(detail.metrics.visibility_rate) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">
          {{ detail.metrics.brand_mentioned }} of {{ detail.metrics.total_responses }} responses
        </p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Recommendation</p>
        <p class="display-num mt-3">{{ pct(detail.metrics.recommendation_rate) }}</p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Cited</p>
        <p class="display-num mt-3">{{ pct(detail.metrics.citation_rate) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">responses citing your pages</p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Responses</p>
        <p class="display-num mt-3">{{ detail.metrics.total_responses }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">across {{ detail.trend.length }} runs</p>
      </Card>
    </div>

    <!-- Trend -->
    <Card class="mb-6">
      <CardHeader title="Hit rate over time" :subtitle="`Last ${detail.trend.length} runs`" />
      <LineChart
        v-if="detail.trend.length > 1"
        :labels="chartLabels"
        :series="chartSeries"
        :y-format="(v: number) => `${v.toFixed(0)}%`"
      />
      <p v-else class="text-sm text-[var(--color-fg-muted)] text-center py-12">
        Need at least 2 runs to chart a trend.
      </p>
    </Card>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Per-source -->
      <Card flush>
        <div class="px-5 pt-5">
          <CardHeader
            title="Per-source"
            subtitle="How each source handles this prompt"
            class="!mb-0"
          />
        </div>
        <div v-if="detail.per_source.length === 0" class="text-sm text-[var(--color-fg-muted)] py-6 text-center">
          No responses yet.
        </div>
        <Table v-else class="!rounded-none !border-x-0 !border-b-0 mt-4">
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead align="right" width="6.5rem">Hit rate</TableHead>
              <TableHead align="right" width="5rem">Recom.</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="s in detail.per_source" :key="s.source">
              <TableCell class="font-medium text-[var(--color-fg)]">{{ s.source_name }}</TableCell>
              <TableCell align="right">
                <span class="display-num text-base inline-block mr-1.5" style="font-size: 14px">
                  {{ pct(s.hit_rate) }}
                </span>
                <span class="text-xs text-[var(--color-fg-muted)] tabular-nums">
                  ({{ s.mentioned_count }}/{{ s.total_responses }})
                </span>
              </TableCell>
              <TableCell align="right" class="text-[var(--color-fg-2)]">{{ s.recommended_count }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </Card>

      <!-- Competitors -->
      <Card>
        <CardHeader
          title="Competitors winning this prompt"
          subtitle="Brands mentioned in responses to this prompt"
        />
        <div v-if="detail.competitors.length === 0" class="text-sm text-[var(--color-fg-muted)] py-6 text-center">
          No competitor mentions for this prompt.
        </div>
        <ul v-else class="space-y-2">
          <li
            v-for="c in detail.competitors"
            :key="c.brand_id"
            class="flex items-center justify-between text-sm bg-[var(--color-surface-2)]/50 rounded-[var(--radius-sm)] px-3 py-2"
          >
            <span class="font-medium text-[var(--color-fg)]">{{ c.brand_name }}</span>
            <Badge tone="info">{{ c.mention_count }} mentions</Badge>
          </li>
        </ul>
      </Card>
    </div>

    <!-- Recent responses -->
    <Card>
      <CardHeader
        title="Recent responses"
        :subtitle="`Latest ${detail.recent_responses.length} · click to open`"
      />
      <div v-if="detail.recent_responses.length === 0" class="text-sm text-[var(--color-fg-muted)] py-6 text-center">
        No responses yet.
      </div>
      <ul v-else class="divide-y divide-[var(--color-line)]">
        <li
          v-for="r in detail.recent_responses"
          :key="r.response_id"
          class="py-3 first:pt-0 last:pb-0 cursor-pointer rounded-[var(--radius-sm)] hover:bg-[var(--color-surface-2)]/40 -mx-2 px-2 transition-colors"
          @click="openResponse(r.run_id, r.response_id)"
        >
          <div class="flex items-center justify-between gap-2 mb-1.5 flex-wrap">
            <div class="flex items-center gap-2">
              <Badge tone="neutral">{{ r.source_name }}</Badge>
              <span class="text-xs text-[var(--color-fg-muted)]">{{ timeAgo(r.created_at) }}</span>
            </div>
            <div class="flex items-center gap-1.5 flex-wrap">
              <Badge v-if="r.error_kind" tone="danger">{{ r.error_kind }}</Badge>
              <template v-else>
                <Badge v-if="r.mentioned" tone="success" dot>mentioned</Badge>
                <Badge v-else tone="neutral">missing</Badge>
                <Badge
                  v-if="r.mentioned && r.sentiment !== 'not_mentioned'"
                  :tone="sentimentTone(r.sentiment)"
                >
                  {{ r.sentiment }}
                </Badge>
                <Badge v-if="r.recommended" tone="warning">★ recommended</Badge>
              </template>
            </div>
          </div>
          <p class="text-sm text-[var(--color-fg-2)] line-clamp-2 leading-relaxed">
            {{ r.snippet || "(empty response)" }}
          </p>
        </li>
      </ul>
    </Card>
  </template>
</template>
