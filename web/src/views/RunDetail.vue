<script setup lang="ts">
/**
 * Run detail.
 *
 * One screen, three questions:
 *   1. How did this run perform overall? (KPI tiles)
 *   2. Which source drove the result? (per-source breakdown)
 *   3. Who got cited instead of me? (top cited domains, filterable by intent)
 *
 * Citations are the headline addition over plain Runs — they surface the
 * raw "every URL the model returned" signal, which the share-of-voice
 * widget can't show because that one only counts brands you've configured.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { Loader2, ArrowLeft } from "lucide-vue-next";
import {
  Button,
  Card,
  CardHeader,
  Badge,
  Tabs,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui";
import StatusBadge from "@/components/StatusBadge.vue";
import { api, ApiError } from "@/api/client";
import type { CitationStat, IntentType, RunSummary, SourceBreakdown } from "@/api/types";
import { date, pct, timeAgo, usd } from "@/lib/format";
import { useToasts } from "@/stores/toasts";

const route = useRoute();
const router = useRouter();
const toasts = useToasts();

const runId = computed(() => Number(route.params.id));

const summary = ref<RunSummary | null>(null);
const totalResponses = ref<number>(0);
const bySource = ref<SourceBreakdown[]>([]);
const citations = ref<CitationStat[]>([]);
const loading = ref(true);
const citationsLoading = ref(false);
const intentFilter = ref<IntentType | null>(null);

const intentTabs = [
  { value: null, label: "All" },
  { value: "transactional", label: "Transactional" },
  { value: "informational", label: "Informational" },
  { value: "comparative", label: "Comparative" },
  { value: "brand", label: "Brand" },
  { value: "local", label: "Local" },
] as const;

async function loadAll() {
  loading.value = true;
  try {
    const [sAll, s, sources, cits] = await Promise.all([
      api.runSummary(runId.value),
      api.runSummary(runId.value, { excludeIntent: "brand" }),
      api.bySource({ runId: runId.value, excludeIntent: "brand" }),
      api.citations({ run_id: runId.value, limit: 20 }),
    ]);
    totalResponses.value = sAll.metrics.total_responses;
    summary.value = s;
    bySource.value = sources;
    citations.value = cits;
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load run");
  } finally {
    loading.value = false;
  }
}

async function reloadCitations() {
  citationsLoading.value = true;
  try {
    citations.value = await api.citations({
      run_id: runId.value,
      intent: intentFilter.value ?? undefined,
      limit: 20,
    });
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? (e.detail ?? e.message) : "Failed to reload citations",
    );
  } finally {
    citationsLoading.value = false;
  }
}

watch(intentFilter, reloadCitations);

function duration(s: RunSummary): string {
  if (!s.completed_at) return "—";
  const ms = new Date(s.completed_at).getTime() - new Date(s.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}

function openResponsesForCitation(_c: CitationStat) {
  router.push({ path: "/responses", query: { run: String(runId.value) } });
}

onMounted(loadAll);

watch(runId, (newId, oldId) => {
  if (newId !== oldId) {
    intentFilter.value = null;
    loadAll();
  }
});
</script>

<template>
  <header class="mb-7">
    <Button
      variant="ghost"
      size="sm"
      class="-ml-2 mb-2"
      @click="router.push('/runs')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Back to runs
    </Button>
    <p class="label-eyebrow">Activity</p>
    <h1 class="font-display text-3xl tracking-tight mt-1">Run #{{ runId }}</h1>
    <div
      v-if="summary"
      class="text-xs text-[var(--color-fg-muted)] mt-3 flex items-center gap-2 flex-wrap"
    >
      <StatusBadge :status="summary.status" />
      <span>·</span>
      <span>{{ date(summary.started_at) }}</span>
      <span>·</span>
      <span>{{ timeAgo(summary.started_at) }}</span>
      <span>·</span>
      <span>{{ duration(summary) }}</span>
      <span>·</span>
      <span>{{ usd(summary.total_cost) }} (est.)</span>
    </div>
  </header>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <template v-else-if="summary">
    <!-- KPI tiles -->
    <div class="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-6">
      <Card compact>
        <p class="label-eyebrow">Responses</p>
        <p class="display-num mt-3">
          {{ summary.metrics.total_responses }}
          <span class="text-base text-[var(--color-fg-muted)] font-sans tabular-nums">
            +{{ totalResponses - summary.metrics.total_responses }}
          </span>
        </p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">non-branded + branded</p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Visibility</p>
        <p class="display-num mt-3">{{ pct(summary.metrics.visibility_rate) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">
          {{ summary.metrics.brand_mentioned }} of {{ summary.metrics.total_responses }} non-branded
        </p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Recommendation</p>
        <p class="display-num mt-3">{{ pct(summary.metrics.recommendation_rate) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">Actively recommended</p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Citation</p>
        <p class="display-num mt-3">{{ pct(summary.metrics.citation_rate) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">Your pages cited as sources</p>
      </Card>
      <Card compact>
        <p class="label-eyebrow">Cost</p>
        <p class="display-num mt-3">{{ usd(summary.total_cost) }}</p>
        <p class="text-xs text-[var(--color-fg-muted)] mt-2">Estimated, not billed</p>
      </Card>
    </div>

    <!-- Per-source breakdown -->
    <Card class="mb-6" flush>
      <div class="px-5 pt-5">
        <CardHeader title="Per-source" subtitle="How each source performed in this run" class="!mb-0" />
      </div>
      <div class="mt-5">
        <Table class="!rounded-none !border-x-0 !border-b-0">
          <TableHeader>
            <TableRow>
              <TableHead>Source</TableHead>
              <TableHead align="right" width="5rem">Resp.</TableHead>
              <TableHead align="right" width="7rem">Visibility</TableHead>
              <TableHead align="right" width="9rem">Recommendation</TableHead>
              <TableHead align="right" width="7rem">Citation</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="r in bySource" :key="r.source">
              <TableCell class="font-medium text-[var(--color-fg)]">{{ r.source_name }}</TableCell>
              <TableCell align="right" class="text-[var(--color-fg-2)]">{{ r.metrics.total_responses }}</TableCell>
              <TableCell align="right" display class="text-base">{{ pct(r.metrics.visibility_rate) }}</TableCell>
              <TableCell align="right" class="text-[var(--color-fg-2)]">{{ pct(r.metrics.recommendation_rate) }}</TableCell>
              <TableCell align="right" class="text-[var(--color-fg-2)]">{{ pct(r.metrics.citation_rate) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </Card>

    <!-- Citations -->
    <Card flush>
      <div class="px-5 pt-5">
        <CardHeader
          title="Top cited domains"
          subtitle="Every URL the model cited, grouped by host. Click a row to open the matching responses."
          class="!mb-3"
        />
        <Tabs v-model="intentFilter" :items="intentTabs" />
      </div>
      <div v-if="citationsLoading" class="flex justify-center py-10">
        <Loader2 class="h-4 w-4 animate-spin text-[var(--color-fg-muted)]" />
      </div>
      <div v-else-if="citations.length === 0" class="text-sm text-[var(--color-fg-muted)] py-10 text-center">
        No citations in this scope.
      </div>
      <Table v-else class="!rounded-none !border-x-0 !border-b-0 mt-4">
        <TableHeader>
          <TableRow>
            <TableHead>Domain</TableHead>
            <TableHead align="right" width="8rem">Citations</TableHead>
            <TableHead align="right" width="11rem">Share of responses</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow
            v-for="c in citations"
            :key="c.domain"
            hoverable
            @click="openResponsesForCitation(c)"
          >
            <TableCell>
              <div class="flex items-center gap-2 min-w-0">
                <span class="font-mono text-[12.5px] text-[var(--color-fg)] truncate">{{ c.domain }}</span>
                <Badge v-if="c.is_self" tone="accent">you</Badge>
                <Badge v-else-if="c.brand_name" tone="info">{{ c.brand_name }}</Badge>
              </div>
            </TableCell>
            <TableCell align="right" class="text-[var(--color-fg-2)]">{{ c.citation_count }}</TableCell>
            <TableCell align="right" display class="text-base">{{ pct(c.share) }}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </Card>
  </template>
</template>
