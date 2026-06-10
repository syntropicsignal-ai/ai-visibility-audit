<script setup lang="ts">
/**
 * Runs list — table of every monitoring run, newest first.
 *
 * Click a row to drill into RunDetail. The brand selector + Run-now
 * button at the top are how you trigger a new run; brand-intent prompts
 * are excluded from the headline metrics for fairness.
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { Loader2, Play } from "lucide-vue-next";
import { Select, Tooltip } from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { Brand, RunSummary } from "@/api/types";
import { date, pct, timeAgo, usd } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();
const router = useRouter();

const summaries = ref<RunSummary[]>([]);
const allSummaries = ref<RunSummary[]>([]);
const selfBrands = ref<Brand[]>([]);
const selectedBrandId = ref<number | null>(null);
const loading = ref(true);
const running = ref(false);

const totalRespByRun = computed(() => {
  const m = new Map<number, number>();
  for (const s of allSummaries.value) m.set(s.run_id, s.metrics.total_responses);
  return m;
});

async function load() {
  loading.value = true;
  try {
    const [sAll, sNonBrand, brands] = await Promise.all([
      api.runsSummary(50),
      api.runsSummary(50, { excludeIntent: "brand" }),
      api.listBrands(),
    ]);
    allSummaries.value = sAll;
    summaries.value = sNonBrand;
    selfBrands.value = brands.filter((b) => b.is_self);
    if (
      selectedBrandId.value === null ||
      !selfBrands.value.some((b) => b.id === selectedBrandId.value)
    ) {
      selectedBrandId.value = selfBrands.value[0]?.id ?? null;
    }
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load runs");
  } finally {
    loading.value = false;
  }
}

async function triggerRun() {
  if (selectedBrandId.value === null) {
    toasts.error("Pick a brand to run");
    return;
  }
  running.value = true;
  try {
    await api.triggerRun(selectedBrandId.value);
    toasts.success("Run completed");
    await load();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Run failed");
  } finally {
    running.value = false;
  }
}

function duration(s: RunSummary): string {
  if (!s.completed_at) return "—";
  const ms = new Date(s.completed_at).getTime() - new Date(s.started_at).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60_000)}m ${Math.floor((ms % 60_000) / 1000)}s`;
}

const brandOptions = computed(() =>
  selfBrands.value.map((b) => ({
    label: `${b.name} · ${b.country_name}`,
    value: b.id,
  })),
);

const totals = computed(() => {
  const completed = summaries.value.filter((s) => s.status === "completed").length;
  const failed = summaries.value.filter((s) => s.status === "failed").length;
  return { completed, failed, total: summaries.value.length };
});

function brandedDelta(run: RunSummary): number {
  return (totalRespByRun.value.get(run.run_id) ?? run.metrics.total_responses) - run.metrics.total_responses;
}

onMounted(load);
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("runs.title") }}</h1>
      <p class="dek mt-1">
        {{ t("runs.dek", { total: totals.total }) }}
        <span v-if="totals.failed > 0">· <span class="text-[var(--color-danger)]">{{ totals.failed }} failed</span></span>
      </p>
    </div>
    <div class="flex items-center gap-2">
      <Select
        v-model="selectedBrandId"
        :options="brandOptions"
        placeholder="Pick a brand"
        class="!w-64"
      />
      <button
        type="button"
        :disabled="selectedBrandId === null || running"
        @click="triggerRun"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] font-medium hover:bg-[var(--color-fg-2)] transition-colors disabled:opacity-50"
      >
        <Loader2 v-if="running" class="h-3 w-3 animate-spin" />
        <Play v-else class="h-3 w-3" />
        {{ running ? "Running…" : "Run now" }}
      </button>
    </div>
  </div>

  <div
    v-if="selfBrands.length === 0 && !loading"
    class="flex items-start gap-2.5 py-2.5 px-3.5 bg-[var(--color-warning-soft)] border border-[color-mix(in_oklab,var(--color-warning)_30%,transparent)] rounded-lg text-[13px] mb-3"
  >
    <span class="text-[var(--color-warning)] font-bold">!</span>
    <p>
      <strong class="font-semibold">No self-brand configured.</strong> Add a brand and mark it as
      <em>your brand</em> in the Brands page to enable runs.
    </p>
  </div>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <section
    v-else
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
  >
    <table class="w-full border-collapse text-[13px]">
      <thead>
        <tr class="bg-[var(--color-bg)]">
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono w-16">#</th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Started</th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Status</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Resp.</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Visibility</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Recommend</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Citation</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Cost</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Duration</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="r in summaries"
          :key="r.run_id"
          class="hover:bg-[var(--color-bg)] cursor-pointer"
          @click="router.push(`/runs/${r.run_id}`)"
        >
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-muted)]">
            {{ String(r.run_id).padStart(3, "0") }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <div class="text-[var(--color-fg)]">{{ date(r.started_at) }}</div>
            <div class="text-[11px] text-[var(--color-fg-muted)] font-mono">{{ timeAgo(r.started_at) }}</div>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <span
              class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium capitalize"
              :class="{
                'bg-[var(--color-success-soft)] text-[var(--color-success)]': r.status === 'completed',
                'bg-[var(--color-danger-soft)] text-[var(--color-danger)]': r.status === 'failed',
                'bg-[var(--color-warning-soft)] text-[var(--color-warning)]': r.status === 'running' || r.status === 'pending',
              }"
            >{{ r.status === "completed" ? "complete" : r.status }}</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            <Tooltip :content="`${r.metrics.total_responses} non-branded · ${brandedDelta(r)} branded`">
              <span tabindex="0" class="cursor-help">
                {{ r.metrics.total_responses }}<span
                  v-if="brandedDelta(r) > 0"
                  class="text-[var(--color-fg-muted)]"
                >+{{ brandedDelta(r) }}</span>
              </span>
            </Tooltip>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right font-semibold">
            {{ pct(r.metrics.visibility_rate, 0) }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-2)]">
            {{ pct(r.metrics.recommendation_rate, 0) }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-2)]">
            {{ pct(r.metrics.citation_rate, 0) }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-2)]">
            <Tooltip content="Estimated, based on flat-rate per source record.">
              <span tabindex="0" class="cursor-help">{{ usd(r.total_cost) }}</span>
            </Tooltip>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-muted)]">
            {{ duration(r) }}
          </td>
        </tr>
        <tr v-if="summaries.length === 0">
          <td colspan="9" class="py-12 px-4 text-center text-[var(--color-fg-muted)] text-[13px]">
            No runs yet. Trigger your first run with the button above.
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
