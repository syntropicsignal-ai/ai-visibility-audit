<script setup lang="ts">
/**
 * Prompts list — grouped by intent, with status pills + hit-rate bars.
 *
 * Two side dialogs:
 *   - Add prompt: manual entry
 *   - Generate from URL: kicks off the multi-stage Exa+LLM generator,
 *     then offers a checklist of suggested queries to save in bulk.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  Search,
  ListChecks,
  CheckCircle2,
  XCircle,
  Circle,
} from "lucide-vue-next";
import {
  Button,
  Badge,
  Input,
  Textarea,
  Select,
  Switch,
  Checkbox,
  Dialog,
  Card,
} from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { GenerateResult, IntentType, Prompt, PromptPerformance } from "@/api/types";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();
const router = useRouter();

const prompts = ref<Prompt[]>([]);
const performance = ref<PromptPerformance[]>([]);
const loading = ref(true);

const showForm = ref(false);
const showGenerate = ref(false);
const form = ref<{ text: string; intent: IntentType; tags: string; enabled: boolean }>({
  text: "",
  intent: "informational",
  tags: "",
  enabled: true,
});

const generateUrl = ref("");
const generating = ref(false);
const generateResult = ref<GenerateResult | null>(null);
const selectedQueries = ref<Set<number>>(new Set());
const saving = ref(false);

// Live pipeline progress: while generating, we poll a /run-status endpoint
// every ~1.5s and render a stage list with status icons + summaries +
// per-stage warnings. Once status flips to "completed", the result is
// already inlined in the response, so we wire it through to generateResult.
interface PipelineStageEvent {
  stage: string;
  started_at: string;
  completed_at: string | null;
  status: "running" | "completed" | "failed" | "skipped";
  summary: string;
  details: Record<string, unknown>;
  warnings: string[];
}
interface PipelineStatus {
  id: number;
  domain: string;
  status: "running" | "completed" | "failed";
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  stages: PipelineStageEvent[];
  generator_run_id: number | null;
  result: GenerateResult | null;
}
const liveStatus = ref<PipelineStatus | null>(null);
let pollTimer: number | null = null;

const intents: IntentType[] = [
  "transactional",
  "comparative",
  "informational",
  "brand",
  "local",
];

const intentOptions = intents.map((i) => ({ label: i, value: i }));
const intentFilterOptions = [
  { label: "All intents", value: "all" },
  ...intentOptions,
];
const statusFilterOptions = [
  { label: "All statuses", value: "all" },
  { label: "Winning (any mention)", value: "winning" },
  { label: "Missing on last run", value: "missing" },
  { label: "No data yet", value: "no_data" },
];

const filterIntent = ref<IntentType | "all">("all");
const filterStatus = ref<"all" | "missing" | "winning" | "no_data">("all");
const search = ref("");

async function loadAll() {
  loading.value = true;
  try {
    const [p, perf] = await Promise.all([api.listPrompts(), api.promptPerformance()]);
    prompts.value = p;
    performance.value = perf;
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load prompts");
  } finally {
    loading.value = false;
  }
}

const perfById = computed(() => {
  const m = new Map<number, PromptPerformance>();
  for (const p of performance.value) m.set(p.prompt_id, p);
  return m;
});

interface Row {
  prompt: Prompt;
  perf: PromptPerformance | null;
}

const rows = computed<Row[]>(() => {
  const q = search.value.trim().toLowerCase();
  return prompts.value
    .map((p) => ({ prompt: p, perf: perfById.value.get(p.id) ?? null }))
    .filter(({ prompt, perf }) => {
      if (filterIntent.value !== "all" && prompt.intent !== filterIntent.value) return false;
      if (filterStatus.value === "missing" && perf?.last_run_status !== "missing") return false;
      if (filterStatus.value === "winning" && (perf?.hit_rate ?? 0) === 0) return false;
      if (filterStatus.value === "no_data" && perf?.last_run_status !== "no_data") return false;
      if (q && !prompt.text.toLowerCase().includes(q)) return false;
      return true;
    });
});

const grouped = computed(() => {
  const groups = new Map<IntentType, Row[]>();
  for (const r of rows.value) {
    const list = groups.get(r.prompt.intent) ?? [];
    list.push(r);
    groups.set(r.prompt.intent, list);
  }
  return intents
    .map((i) => ({ intent: i, rows: groups.get(i) ?? [] }))
    .filter((g) => g.rows.length > 0);
});

const stats = computed(() => {
  const total = prompts.value.length;
  const missing = performance.value.filter((p) => p.last_run_status === "missing").length;
  const winning = performance.value.filter((p) => p.hit_rate > 0).length;
  return { total, missing, winning };
});

async function createPrompt() {
  try {
    await api.createPrompt({
      text: form.value.text,
      intent: form.value.intent,
      tags: form.value.tags.split(",").map((t) => t.trim()).filter(Boolean),
      enabled: form.value.enabled,
    });
    form.value = { text: "", intent: "informational", tags: "", enabled: true };
    showForm.value = false;
    toasts.success("Prompt created");
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to create prompt");
  }
}

async function deletePrompt(id: number) {
  if (!confirm("Delete this prompt? Historical responses are preserved.")) return;
  try {
    await api.deletePrompt(id);
    toasts.success("Prompt deleted");
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to delete prompt");
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function fetchPipelineStatus(id: number): Promise<PipelineStatus> {
  const res = await fetch(`/api/v1/generator/run-status/${id}`);
  if (!res.ok) throw new Error(`status ${res.status}`);
  return res.json();
}

async function pollOnce(pipelineRunId: number) {
  try {
    const status = await fetchPipelineStatus(pipelineRunId);
    liveStatus.value = status;
    if (status.status === "running") {
      pollTimer = window.setTimeout(() => pollOnce(pipelineRunId), 1500);
      return;
    }
    // Run finished — wire the result back into generateResult so the
    // existing checklist UI lights up. Failed runs surface as a toast
    // and leave the timeline visible for inspection.
    stopPolling();
    generating.value = false;
    if (status.status === "failed" || !status.result) {
      toasts.error(status.error || "Generation failed — see pipeline timeline");
      return;
    }
    generateResult.value = status.result;
    status.result.queries.forEach((_, i) => selectedQueries.value.add(i));
  } catch (e) {
    stopPolling();
    generating.value = false;
    toasts.error(e instanceof Error ? e.message : "Polling failed");
  }
}

async function generatePrompts() {
  if (!generateUrl.value.trim()) return;
  generating.value = true;
  generateResult.value = null;
  liveStatus.value = null;
  selectedQueries.value = new Set();
  stopPolling();
  try {
    const res = await fetch("/api/v1/generator/run-async", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        domain: generateUrl.value.trim(),
        num_queries: 50,
      }),
    });
    if (!res.ok) {
      const body = await res.text();
      throw new Error(body || `status ${res.status}`);
    }
    const { pipeline_run_id } = await res.json();
    await pollOnce(pipeline_run_id);
  } catch (e) {
    generating.value = false;
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : (e instanceof Error ? e.message : "Generation failed"));
  }
}

function toggleQuery(i: number) {
  const next = new Set(selectedQueries.value);
  if (next.has(i)) next.delete(i);
  else next.add(i);
  selectedQueries.value = next;
}

function toggleAll() {
  if (!generateResult.value) return;
  if (selectedQueries.value.size === generateResult.value.queries.length) {
    selectedQueries.value = new Set();
  } else {
    selectedQueries.value = new Set(generateResult.value.queries.map((_, i) => i));
  }
}

async function saveSelectedQueries() {
  if (!generateResult.value) return;
  saving.value = true;
  try {
    const selected = generateResult.value.queries.filter((_, i) =>
      selectedQueries.value.has(i),
    );
    for (const q of selected) {
      await api.createPrompt({
        text: q.text,
        intent: q.intent as IntentType,
        tags: q.tags,
        enabled: true,
        seed_source: q.seed_source ?? null,
        seed_keyword: q.seed_keyword ?? null,
        seed_search_volume: q.seed_search_volume ?? null,
        seed_position: q.seed_position ?? null,
      });
    }
    toasts.success(`Saved ${selected.length} prompts`);
    generateResult.value = null;
    liveStatus.value = null;
    showGenerate.value = false;
    generateUrl.value = "";
    await loadAll();
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to save prompts");
  } finally {
    saving.value = false;
  }
}

onUnmounted(stopPolling);

type StatusKind = "mentioned" | "missed" | "never" | "no_data";

function statusKind(perf: PromptPerformance | null): StatusKind {
  if (!perf || perf.total_responses === 0) return "no_data";
  if (perf.last_run_status === "mentioned") return "mentioned";
  if (perf.hit_rate > 0) return "missed";
  return "never";
}

function statusTone(perf: PromptPerformance | null) {
  return {
    mentioned: "success" as const,
    missed: "warning" as const,
    never: "danger" as const,
    no_data: "neutral" as const,
  }[statusKind(perf)];
}

function statusLabel(perf: PromptPerformance | null): string {
  if (!perf || perf.total_responses === 0) return "no data";
  if (perf.last_run_status === "mentioned") return "mentioned";
  if (perf.hit_rate > 0) return "missed last";
  return "never";
}

function closeGenerate() {
  showGenerate.value = false;
  generateResult.value = null;
  generateUrl.value = "";
}

onMounted(loadAll);
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("prompts.title") }}</h1>
      <p class="dek mt-1">
        {{ stats.total }} tracked prompts ·
        <span class="text-[var(--color-success)]">{{ stats.winning }} winning</span> ·
        <span class="text-[var(--color-danger)]">{{ stats.missing }} missing last run</span>
      </p>
    </div>
    <div class="flex items-center gap-2">
      <button
        type="button"
        @click="showGenerate = true"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
      >
        <Sparkles class="h-3 w-3" />
        Generate from URL
      </button>
      <button
        type="button"
        @click="showForm = true"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] font-medium hover:bg-[var(--color-fg-2)] transition-colors"
      >
        <Plus class="h-3 w-3" />
        Add prompt
      </button>
    </div>
  </div>

  <!-- Filter row -->
  <div class="flex items-center gap-2 py-2.5 px-4 border border-[var(--color-line)] rounded-lg mb-3 bg-[var(--color-surface)] text-[12px] flex-wrap">
    <span class="relative flex items-center min-w-[16rem]">
      <Search class="absolute left-2.5 h-3.5 w-3.5 text-[var(--color-fg-muted)] pointer-events-none" />
      <input
        v-model="search"
        type="text"
        placeholder="Search prompts…"
        class="border border-[var(--color-line)] bg-[var(--color-bg)] rounded-md py-1 pl-7 pr-2.5 text-[12px] outline-none focus:border-[var(--color-accent)] focus:bg-[var(--color-surface)] w-64"
      />
    </span>

    <span class="w-px h-[18px] bg-[var(--color-line)] mx-1" />

    <span class="cap !text-[11px] !tracking-[0.04em] mr-1">Intent</span>
    <button
      type="button"
      @click="filterIntent = 'all'"
      :class="[
        'border rounded-md py-[3px] px-2.5 text-[12px] cursor-pointer transition-colors',
        filterIntent === 'all'
          ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
          : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
      ]"
    >All</button>
    <button
      v-for="i in intents"
      :key="i"
      type="button"
      @click="filterIntent = i"
      :class="[
        'border rounded-md py-[3px] px-2.5 text-[12px] cursor-pointer transition-colors capitalize',
        filterIntent === i
          ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
          : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
      ]"
    >{{ i }}</button>

    <span class="w-px h-[18px] bg-[var(--color-line)] mx-1" />

    <span class="cap !text-[11px] !tracking-[0.04em] mr-1">Status</span>
    <button
      v-for="opt in statusFilterOptions"
      :key="opt.value"
      type="button"
      @click="filterStatus = opt.value as typeof filterStatus"
      :class="[
        'border rounded-md py-[3px] px-2.5 text-[12px] cursor-pointer transition-colors',
        filterStatus === opt.value
          ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
          : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
      ]"
    >{{ opt.label }}</button>
  </div>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <section
    v-else-if="prompts.length === 0"
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg p-12 text-center"
  >
    <ListChecks class="h-10 w-10 mx-auto text-[var(--color-fg-muted)] stroke-[1.4]" />
    <h3 class="text-[18px] font-semibold mt-4">No prompts yet</h3>
    <p class="text-sm text-[var(--color-fg-2)] mt-2 max-w-md mx-auto">
      Generate prompts from your URL or add one manually to start tracking visibility.
    </p>
    <div class="flex justify-center gap-2 mt-6">
      <button
        type="button"
        @click="showGenerate = true"
        class="inline-flex items-center gap-1.5 py-1.5 px-3 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[13px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
      >
        <Sparkles class="h-3.5 w-3.5" />
        Generate from URL
      </button>
      <button
        type="button"
        @click="showForm = true"
        class="inline-flex items-center gap-1.5 py-1.5 px-3 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[13px] font-medium hover:bg-[var(--color-fg-2)] transition-colors"
      >
        <Plus class="h-3.5 w-3.5" />
        Add prompt
      </button>
    </div>
  </section>

  <p v-else-if="rows.length === 0" class="text-sm text-[var(--color-fg-muted)] text-center py-12">
    No prompts match your filters.
  </p>

  <section
    v-else
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
  >
    <table class="w-full border-collapse text-[13px]">
      <thead>
        <tr class="bg-[var(--color-bg)]">
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Prompt</th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Intent</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Runs</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Hit rate</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Sentiment</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Status</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]"></th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="{ prompt, perf } in rows"
          :key="prompt.id"
          class="hover:bg-[var(--color-bg)] cursor-pointer"
          @click="router.push(`/prompts/${prompt.id}`)"
        >
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]" style="max-width: 360px">
            <p class="italic text-[var(--color-fg)] line-clamp-1">"{{ prompt.text }}"</p>
            <div v-if="prompt.tags.length" class="flex flex-wrap gap-1 mt-1">
              <span
                v-for="t in prompt.tags"
                :key="t"
                class="inline-flex items-center py-px px-1.5 rounded text-[10px] font-medium bg-[var(--color-surface-2)] text-[var(--color-fg-muted)]"
              >{{ t }}</span>
            </div>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <span
              class="inline-flex items-center py-0.5 px-2 border border-[var(--color-line)] rounded text-[11px] font-medium text-[var(--color-fg-2)] capitalize"
            >{{ prompt.intent }}</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            {{ perf?.total_responses ?? 0 }}
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">
            <div class="flex items-center gap-2 justify-end">
              <span class="w-[60px] h-[6px] rounded-[3px] bg-[var(--color-surface-3)] overflow-hidden inline-block">
                <span
                  class="block h-full rounded-[3px]"
                  :style="{
                    width: `${(perf?.hit_rate ?? 0) * 100}%`,
                    background: (perf?.hit_rate ?? 0) > 0.6 ? 'var(--color-success)' : (perf?.hit_rate ?? 0) > 0.2 ? 'var(--color-accent)' : 'var(--color-danger)',
                  }"
                />
              </span>
              <span class="min-w-9 inline-block">{{ perf ? `${Math.round(perf.hit_rate * 100)}%` : "—" }}</span>
            </div>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] text-right tabular-nums">
            <span
              v-if="perf && (perf.sentiment.positive + perf.sentiment.neutral + perf.sentiment.negative) > 0"
              class="inline-flex gap-1 text-[11px] font-mono"
            >
              <span v-if="perf.sentiment.positive > 0" class="text-[var(--color-success)] font-semibold">{{ perf.sentiment.positive }}+</span>
              <span v-if="perf.sentiment.neutral > 0" class="text-[var(--color-fg-2)]">{{ perf.sentiment.neutral }}~</span>
              <span v-if="perf.sentiment.negative > 0" class="text-[var(--color-danger)] font-semibold">{{ perf.sentiment.negative }}−</span>
            </span>
            <span v-else class="text-[var(--color-fg-muted)] text-[11px]">—</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] text-right">
            <span
              class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium"
              :class="{
                'bg-[var(--color-success-soft)] text-[var(--color-success)]': statusTone(perf) === 'success',
                'bg-[var(--color-warning-soft)] text-[var(--color-warning)]': statusTone(perf) === 'warning',
                'bg-[var(--color-danger-soft)] text-[var(--color-danger)]': statusTone(perf) === 'danger',
                'bg-[var(--color-surface-2)] text-[var(--color-fg-muted)]': statusTone(perf) === 'neutral',
              }"
            >{{ statusLabel(perf) }}</span>
            <span v-if="!prompt.enabled" class="ml-1 text-[10px] text-[var(--color-fg-muted)] italic">off</span>
          </td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] text-right">
            <button
              type="button"
              class="inline-flex items-center justify-center w-7 h-7 rounded-md text-[var(--color-fg-muted)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-danger)] transition-colors"
              aria-label="Delete"
              @click.stop="deletePrompt(prompt.id)"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </section>

  <!-- Add prompt dialog -->
  <Dialog v-model:open="showForm" title="Add prompt" size="lg">
    <form @submit.prevent="createPrompt" class="space-y-4">
      <div>
        <label class="label-eyebrow block mb-1.5">Prompt text</label>
        <Textarea v-model="form.text" :rows="3" required />
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="label-eyebrow block mb-1.5">Intent</label>
          <Select v-model="form.intent" :options="intentOptions" />
        </div>
        <div>
          <label class="label-eyebrow block mb-1.5">Tags</label>
          <Input v-model="form.tags" placeholder="comma-separated" />
        </div>
      </div>
      <label class="flex items-center gap-3 text-sm">
        <Switch v-model="form.enabled" />
        Enabled
      </label>
    </form>
    <template #footer>
      <Button variant="ghost" @click="showForm = false">Cancel</Button>
      <Button variant="primary" @click="createPrompt">Create</Button>
    </template>
  </Dialog>

  <!-- Generate dialog -->
  <Dialog
    v-model:open="showGenerate"
    title="Generate prompts from URL"
    size="xl"
    @update:open="(v: boolean | undefined) => { if (!v) closeGenerate(); }"
  >
    <div v-if="!generateResult">
      <p class="text-sm text-[var(--color-fg-2)] mb-4 leading-relaxed">
        Enter a website URL to automatically generate monitoring queries. The generator will
        analyze the site, find competitors, and create a query set covering the full buyer
        journey.
      </p>
      <form @submit.prevent="generatePrompts" class="flex gap-2">
        <Input v-model="generateUrl" placeholder="e.g. example.com" :disabled="generating" required />
        <Button type="submit" variant="primary" :disabled="generating">
          <Loader2 v-if="generating" class="h-3.5 w-3.5 animate-spin" />
          <Sparkles v-else class="h-3.5 w-3.5" />
          {{ generating ? "Generating…" : "Generate" }}
        </Button>
      </form>
      <Card v-if="generating && !liveStatus" class="mt-4 bg-[var(--color-info-soft)] border-[color-mix(in_srgb,var(--color-info),transparent_70%)]">
        <p class="text-xs text-[var(--color-info)]">
          Kicking off pipeline — staged progress will appear here in a moment…
        </p>
      </Card>

      <!-- Live pipeline timeline. Shown while a run is in flight, kept
           visible after completion so the user can review what each
           stage did (counts, warnings, durations). -->
      <Card v-if="liveStatus" class="mt-4 pipeline-card">
        <div class="pipeline-header">
          <span class="label-eyebrow">pipeline run · {{ liveStatus.domain }}</span>
          <span :class="['pipeline-status', liveStatus.status]">{{ liveStatus.status }}</span>
        </div>
        <p v-if="liveStatus.error" class="text-xs text-[var(--color-danger)] mt-1">
          {{ liveStatus.error }}
        </p>
        <ol class="stage-list">
          <li
            v-for="(s, i) in liveStatus.stages"
            :key="i"
            :class="['stage-item', s.status]"
          >
            <div class="stage-icon">
              <CheckCircle2 v-if="s.status === 'completed'" class="h-4 w-4" />
              <Loader2 v-else-if="s.status === 'running'" class="h-4 w-4 animate-spin" />
              <XCircle v-else-if="s.status === 'failed'" class="h-4 w-4" />
              <Circle v-else class="h-4 w-4" />
            </div>
            <div class="stage-body">
              <div class="stage-name">{{ s.stage }}</div>
              <div class="stage-summary">{{ s.summary || "…" }}</div>
              <div v-if="s.warnings && s.warnings.length" class="stage-warnings">
                <div v-for="w in s.warnings" :key="w" class="stage-warning">{{ w }}</div>
              </div>
            </div>
          </li>
        </ol>
      </Card>
    </div>

    <div v-else>
      <div class="mb-4 pb-4 border-b border-[var(--color-line)]">
        <h3 class="font-display text-base">
          Generated {{ generateResult.queries.length }} queries for
          <span class="font-mono font-normal text-sm">{{ generateResult.domain }}</span>
        </h3>
        <p class="text-xs text-[var(--color-fg-muted)] mt-1">
          Found {{ generateResult.pages_found }} pages.
          <span v-if="generateResult.competitors.length">
            Competitors: {{ generateResult.competitors.map((c) => c.name).join(", ") }}
          </span>
        </p>
      </div>

      <div class="space-y-1 max-h-96 overflow-y-auto pr-1">
        <label
          v-for="(q, i) in generateResult.queries"
          :key="i"
          class="flex items-start gap-3 p-2 rounded-[var(--radius-sm)] hover:bg-[var(--color-surface-2)]/50 cursor-pointer"
        >
          <Checkbox
            :model-value="selectedQueries.has(i)"
            @update:model-value="toggleQuery(i)"
          />
          <div class="flex-1 min-w-0">
            <p class="text-sm text-[var(--color-fg)]">{{ q.text }}</p>
            <div class="flex gap-1.5 mt-1.5 flex-wrap">
              <Badge tone="accent">{{ q.intent }}</Badge>
              <Badge v-for="tag in q.tags" :key="tag" tone="neutral">{{ tag }}</Badge>
            </div>
          </div>
        </label>
      </div>
    </div>

    <template v-if="generateResult" #footer>
      <Button variant="ghost" @click="toggleAll">
        {{ selectedQueries.size === generateResult.queries.length ? "Deselect all" : "Select all" }}
      </Button>
      <Button
        variant="primary"
        :disabled="selectedQueries.size === 0 || saving"
        @click="saveSelectedQueries"
      >
        <Loader2 v-if="saving" class="h-3.5 w-3.5 animate-spin" />
        {{ saving ? "Saving…" : `Save ${selectedQueries.size} selected` }}
      </Button>
    </template>
  </Dialog>
</template>

<style scoped>
.pipeline-card { padding: 0.85rem 1rem; }
.pipeline-header { display: flex; align-items: center; gap: 0.6rem; }
.pipeline-status { padding: 0.1rem 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.7rem; }
.pipeline-status.running { background: var(--color-accent-soft); color: var(--color-accent); }
.pipeline-status.completed { background: var(--color-success-soft); color: var(--color-success); }
.pipeline-status.failed { background: var(--color-danger-soft); color: var(--color-danger); }

.stage-list {
  list-style: none;
  padding: 0;
  margin: 0.6rem 0 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.stage-item {
  display: flex;
  gap: 0.55rem;
  padding: 0.4rem 0.55rem;
  border-radius: 6px;
  border: 1px solid var(--color-line-soft);
  background: var(--color-surface);
}
.stage-item.running {
  border-color: color-mix(in srgb, var(--color-accent), transparent 60%);
  background: color-mix(in srgb, var(--color-accent-soft), transparent 30%);
}
.stage-item.failed {
  border-color: color-mix(in srgb, var(--color-danger), transparent 60%);
  background: var(--color-danger-soft);
}
.stage-icon { flex-shrink: 0; padding-top: 0.05rem; color: var(--color-fg-muted); }
.stage-item.completed .stage-icon { color: var(--color-success); }
.stage-item.running .stage-icon { color: var(--color-accent); }
.stage-item.failed .stage-icon { color: var(--color-danger); }
.stage-body { flex: 1; min-width: 0; }
.stage-name { font-family: monospace; font-size: 0.74rem; color: var(--color-fg-muted); }
.stage-summary {
  font-size: 0.86rem;
  color: var(--color-fg);
  margin-top: 0.1rem;
  line-height: 1.35;
  word-break: break-word;
}
.stage-warnings { margin-top: 0.3rem; display: flex; flex-direction: column; gap: 0.15rem; }
.stage-warning {
  font-size: 0.76rem;
  line-height: 1.35;
  padding: 0.3rem 0.5rem;
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-radius: 4px;
  border: 1px solid color-mix(in srgb, var(--color-warning), transparent 80%);
}
</style>
