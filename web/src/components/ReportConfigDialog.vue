<script setup lang="ts">
/**
 * Report-config dialog.
 *
 * Pop-out form on the Dashboard for configuring an audit report. Submits
 * by opening `/report?...` in a new tab; the user then uses the browser's
 * Print → Save as PDF for the printable output.
 *
 * Inputs:
 *   - mode: single run | date range
 *   - if single run: pick from recent runs
 *   - if range: from/to date pickers (defaults: last 30 days)
 *   - competitor brand picker (self-brand auto-included as the main row)
 *   - sample-response count
 *   - language (PL / EN)
 */
import { computed, onMounted, ref, watch } from "vue";
import { Button, Dialog, Input } from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { Brand, Run } from "@/api/types";
import { useToasts } from "@/stores/toasts";

const open = defineModel<boolean>("open");
const toasts = useToasts();

const brands = ref<Brand[]>([]);
const runs = ref<Run[]>([]);

const mode = ref<"run" | "range">("range");
const runId = ref<number | null>(null);
const fromDate = ref<string>("");
const toDate = ref<string>("");
const competitorIds = ref<number[]>([]);
const sampleCount = ref<number>(5);
const lang = ref<"en" | "pl">("en");
const tier = ref<"simple" | "advanced">("simple");
const submitting = ref(false);

function isoDateInput(d: Date): string {
  // YYYY-MM-DD for <input type="date">. Use UTC parts to avoid TZ shifts.
  return d.toISOString().slice(0, 10);
}

function defaultRange(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - 30 * 24 * 3600 * 1000);
  return { from: isoDateInput(from), to: isoDateInput(to) };
}

const competitorBrands = computed(() => brands.value.filter((b) => !b.is_self));
const selfBrand = computed(() => brands.value.find((b) => b.is_self) ?? null);

watch(open, async (isOpen) => {
  if (!isOpen) return;
  // Reload data + reset transient form state every time the dialog opens
  // so a stale picked run doesn't persist between sessions.
  try {
    const [b, r] = await Promise.all([api.listBrands(), api.listRuns()]);
    brands.value = b;
    runs.value = r;
    // Default competitor set: all non-self brands selected
    competitorIds.value = b.filter((x) => !x.is_self).map((x) => x.id);
    // Default run: most recent completed
    const completed = r.filter((x) => x.status === "completed");
    if (completed.length > 0) runId.value = completed[0].id;
    const range = defaultRange();
    fromDate.value = range.from;
    toDate.value = range.to;
  } catch (e) {
    toasts.error(
      e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load brands/runs",
    );
  }
});

onMounted(() => {
  // If the dialog defaults to closed, this is a no-op; the watcher above
  // handles loading on first open. We still set sensible date defaults so
  // the form doesn't render with empty inputs the moment it appears.
  const range = defaultRange();
  fromDate.value = range.from;
  toDate.value = range.to;
});

function toggleCompetitor(id: number, checked: boolean) {
  if (checked) {
    if (!competitorIds.value.includes(id)) competitorIds.value = [...competitorIds.value, id];
  } else {
    competitorIds.value = competitorIds.value.filter((x) => x !== id);
  }
}

function buildUrl(): string | null {
  const params = new URLSearchParams();
  if (mode.value === "run") {
    if (runId.value === null) {
      toasts.error("Pick a run before generating the report.");
      return null;
    }
    params.set("run_id", String(runId.value));
  } else {
    if (!fromDate.value || !toDate.value) {
      toasts.error("Pick a date range before generating the report.");
      return null;
    }
    if (fromDate.value > toDate.value) {
      toasts.error("`From` date must be before `to` date.");
      return null;
    }
    // Send full-day boundaries: from = 00:00 UTC, to = 23:59:59 UTC of the
    // selected day. Without this, picking the same day for from and to
    // would only include events at exactly 00:00.
    params.set("from", `${fromDate.value}T00:00:00Z`);
    params.set("to", `${toDate.value}T23:59:59Z`);
  }
  if (competitorIds.value.length > 0) {
    params.set("competitors", competitorIds.value.join(","));
  }
  if (sampleCount.value !== 5) params.set("samples", String(sampleCount.value));
  params.set("lang", lang.value);
  params.set("tier", tier.value);
  return `/report?${params.toString()}`;
}

function generate() {
  submitting.value = true;
  try {
    const url = buildUrl();
    if (!url) return;
    window.open(url, "_blank", "noopener");
    open.value = false;
  } finally {
    submitting.value = false;
  }
}

const downloading = ref(false);

/**
 * Build the same param set we use for the in-browser report URL, but
 * for the backend's /report/pdf endpoint (which takes the canonical
 * backend names — `from_date`, `to_date`, `competitor_ids` repeated,
 * `sample_count`, `language`, `tier`).
 */
function buildPdfUrl(): string | null {
  if (mode.value === "run") {
    if (runId.value === null) {
      toasts.error("Pick a run before generating the report.");
      return null;
    }
  } else {
    if (!fromDate.value || !toDate.value) {
      toasts.error("Pick a date range before generating the report.");
      return null;
    }
    if (fromDate.value > toDate.value) {
      toasts.error("`From` date must be before `to` date.");
      return null;
    }
  }
  const params = new URLSearchParams();
  if (mode.value === "run") {
    params.set("run_id", String(runId.value));
  } else {
    params.set("from_date", `${fromDate.value}T00:00:00Z`);
    params.set("to_date", `${toDate.value}T23:59:59Z`);
  }
  for (const id of competitorIds.value) {
    params.append("competitor_ids", String(id));
  }
  params.set("sample_count", String(sampleCount.value));
  params.set("language", lang.value);
  params.set("tier", tier.value);
  return `/api/v1/report/pdf?${params.toString()}`;
}

async function downloadPdf() {
  const url = buildPdfUrl();
  if (!url) return;
  downloading.value = true;
  try {
    const res = await fetch(url);
    if (!res.ok) {
      let detail = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (typeof body?.detail === "string") detail = body.detail;
      } catch {
        // body wasn't JSON — keep the status-line detail
      }
      toasts.error(`PDF generation failed: ${detail}`);
      return;
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = "ai-visibility-audit-report.pdf";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
    toasts.success("Report downloaded");
    open.value = false;
  } catch (e) {
    toasts.error(`PDF generation failed: ${(e as Error).message}`);
  } finally {
    downloading.value = false;
  }
}

function setRangePreset(days: number) {
  const to = new Date();
  const from = new Date(to.getTime() - days * 24 * 3600 * 1000);
  fromDate.value = isoDateInput(from);
  toDate.value = isoDateInput(to);
  mode.value = "range";
}
</script>

<template>
  <Dialog v-model:open="open" title="Generate audit report" size="lg"
    description="Configure a printable PDF report for a client.">
    <div class="flex flex-col gap-5">
      <!-- Self brand info -->
      <div v-if="selfBrand" class="flex items-baseline gap-2 text-sm text-[var(--color-fg-2)]">
        <span class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold">Main brand</span>
        <span class="font-semibold text-[var(--color-fg)]">{{ selfBrand.name }}</span>
        <span v-if="selfBrand.domains.length > 0" class="font-mono text-xs text-[var(--color-fg-muted)]">
          · {{ selfBrand.domains[0] }}
        </span>
      </div>

      <!-- Mode toggle -->
      <fieldset class="flex flex-col gap-2">
        <legend class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold mb-1.5">Period</legend>
        <div class="flex gap-2">
          <label
            :class="[
              'flex-1 text-center py-2 px-3 rounded-[var(--radius-md)] cursor-pointer text-sm font-medium border transition-colors',
              mode === 'range'
                ? 'bg-[var(--color-accent-soft)] border-[var(--color-accent)] text-[var(--color-accent)]'
                : 'bg-[var(--color-surface)] border-[var(--color-line)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
            ]"
          >
            <input v-model="mode" value="range" type="radio" class="sr-only" />
            Date range
          </label>
          <label
            :class="[
              'flex-1 text-center py-2 px-3 rounded-[var(--radius-md)] cursor-pointer text-sm font-medium border transition-colors',
              mode === 'run'
                ? 'bg-[var(--color-accent-soft)] border-[var(--color-accent)] text-[var(--color-accent)]'
                : 'bg-[var(--color-surface)] border-[var(--color-line)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
            ]"
          >
            <input v-model="mode" value="run" type="radio" class="sr-only" />
            Single run
          </label>
        </div>

        <!-- Range mode controls -->
        <div v-if="mode === 'range'" class="flex flex-col gap-2 mt-2">
          <div class="flex gap-2">
            <div class="flex-1">
              <label class="text-xs text-[var(--color-fg-muted)] mb-1 block">From</label>
              <Input type="date" v-model="fromDate" />
            </div>
            <div class="flex-1">
              <label class="text-xs text-[var(--color-fg-muted)] mb-1 block">To</label>
              <Input type="date" v-model="toDate" />
            </div>
          </div>
          <div class="flex gap-2 mt-1">
            <button
              type="button"
              class="text-xs px-2 py-1 rounded-[var(--radius-sm)] border border-[var(--color-line)] hover:bg-[var(--color-surface-2)] text-[var(--color-fg-2)]"
              @click="setRangePreset(7)"
            >Last 7 days</button>
            <button
              type="button"
              class="text-xs px-2 py-1 rounded-[var(--radius-sm)] border border-[var(--color-line)] hover:bg-[var(--color-surface-2)] text-[var(--color-fg-2)]"
              @click="setRangePreset(30)"
            >Last 30 days</button>
            <button
              type="button"
              class="text-xs px-2 py-1 rounded-[var(--radius-sm)] border border-[var(--color-line)] hover:bg-[var(--color-surface-2)] text-[var(--color-fg-2)]"
              @click="setRangePreset(90)"
            >Last 90 days</button>
          </div>
        </div>

        <!-- Single-run mode controls -->
        <div v-else class="mt-2">
          <label class="text-xs text-[var(--color-fg-muted)] mb-1 block">Run</label>
          <select
            v-model="runId"
            class="w-full bg-[var(--color-surface)] border border-[var(--color-line)] rounded-[var(--radius-md)] py-2 px-3 text-sm focus-ring"
          >
            <option v-for="r in runs" :key="r.id" :value="r.id">
              #{{ r.id }} ·
              {{ new Date(r.started_at).toLocaleString() }}
              · {{ r.status }}
            </option>
          </select>
        </div>
      </fieldset>

      <!-- Competitor picker -->
      <fieldset class="flex flex-col gap-2" v-if="competitorBrands.length > 0">
        <legend class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold mb-1.5">
          Competitors to include
        </legend>
        <div class="flex flex-col gap-1.5 max-h-44 overflow-auto border border-[var(--color-line)] rounded-[var(--radius-md)] p-2">
          <label
            v-for="b in competitorBrands"
            :key="b.id"
            class="flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-sm)] hover:bg-[var(--color-surface-2)] cursor-pointer"
          >
            <input
              type="checkbox"
              :checked="competitorIds.includes(b.id)"
              @change="toggleCompetitor(b.id, ($event.target as HTMLInputElement).checked)"
            />
            <span class="text-sm">{{ b.name }}</span>
            <span v-if="b.domains.length > 0" class="font-mono text-xs text-[var(--color-fg-muted)]">
              · {{ b.domains[0] }}
            </span>
          </label>
        </div>
      </fieldset>

      <!-- Tier (simple / advanced) -->
      <fieldset class="flex flex-col gap-2">
        <legend class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold mb-1.5">
          Report tier
        </legend>
        <div class="grid grid-cols-2 gap-2">
          <label
            :class="[
              'flex flex-col gap-1 p-3 rounded-[var(--radius-md)] cursor-pointer border transition-colors',
              tier === 'simple'
                ? 'bg-[var(--color-accent-soft)] border-[var(--color-accent)]'
                : 'bg-[var(--color-surface)] border-[var(--color-line)] hover:bg-[var(--color-surface-2)]',
            ]"
          >
            <input v-model="tier" value="simple" type="radio" class="sr-only" />
            <span :class="[
              'text-sm font-semibold',
              tier === 'simple' ? 'text-[var(--color-accent)]' : 'text-[var(--color-fg)]',
            ]">Simple</span>
            <span class="text-[11px] text-[var(--color-fg-muted)] leading-snug">
              KPIs, brand awareness, per-source, top cited, competitor visibility, sample responses.
            </span>
          </label>
          <label
            :class="[
              'flex flex-col gap-1 p-3 rounded-[var(--radius-md)] cursor-pointer border transition-colors relative',
              tier === 'advanced'
                ? 'bg-[var(--color-accent-soft)] border-[var(--color-accent)]'
                : 'bg-[var(--color-surface)] border-[var(--color-line)] hover:bg-[var(--color-surface-2)]',
            ]"
          >
            <input v-model="tier" value="advanced" type="radio" class="sr-only" />
            <span :class="[
              'text-sm font-semibold',
              tier === 'advanced' ? 'text-[var(--color-accent)]' : 'text-[var(--color-fg)]',
            ]">Advanced</span>
            <span class="text-[11px] text-[var(--color-fg-muted)] leading-snug">
              Everything in Simple plus per-prompt recommendations, citation gap, and search-term analysis.
            </span>
          </label>
        </div>
      </fieldset>

      <!-- Language + sample count -->
      <div class="grid grid-cols-2 gap-4">
        <div>
          <label class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold mb-1.5 block">
            Language
          </label>
          <div class="flex gap-2">
            <label
              v-for="opt in [{ v: 'en', l: 'English' }, { v: 'pl', l: 'Polski' }]"
              :key="opt.v"
              :class="[
                'flex-1 text-center py-2 px-3 rounded-[var(--radius-md)] cursor-pointer text-sm font-medium border transition-colors',
                lang === opt.v
                  ? 'bg-[var(--color-accent-soft)] border-[var(--color-accent)] text-[var(--color-accent)]'
                  : 'bg-[var(--color-surface)] border-[var(--color-line)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
              ]"
            >
              <input v-model="lang" :value="opt.v" type="radio" class="sr-only" />
              {{ opt.l }}
            </label>
          </div>
        </div>
        <div>
          <label class="text-xs text-[var(--color-fg-muted)] uppercase tracking-[0.06em] font-semibold mb-1.5 block">
            Sample responses
          </label>
          <Input v-model.number="sampleCount" type="number" min="0" max="20" />
        </div>
      </div>
    </div>

    <template #footer>
      <Button variant="secondary" @click="open = false">Cancel</Button>
      <Button
        variant="secondary"
        :disabled="downloading || submitting"
        @click="generate"
      >
        Open in browser
      </Button>
      <Button
        variant="primary"
        :disabled="downloading || submitting"
        @click="downloadPdf"
      >
        {{ downloading ? "Rendering PDF…" : "Download PDF" }}
      </Button>
    </template>
  </Dialog>
</template>
