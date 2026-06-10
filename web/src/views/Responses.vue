<script setup lang="ts">
/**
 * Responses Explorer — master/detail.
 *
 * Left rail: filtered, scannable list of responses. Right pane: the
 * selected response in full. Brand mentions are highlighted inline;
 * clicking a brand row scroll-jumps + flashes the matching highlight
 * (or the source pill, if the brand was matched by URL only).
 *
 * Deep links from PromptDetail / RunDetail use:
 *   ?run=<id>          — pre-select that run
 *   ?response=<id>     — pre-select that response in the list
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import {
  Loader2,
  Search,
  Inbox,
  MessageSquare,
  Copy,
  Flag,
  Plus,
  RefreshCw,
  Download,
  ArrowUpRight,
} from "lucide-vue-next";
import { Card, Select } from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { Brand, IntentType, ResponseDetail, Run, Sentiment } from "@/api/types";
import { highlightTerms, hostname, renderMarkdown } from "@/lib/markdown";
import { date } from "@/lib/format";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";
import { sentimentColors } from "@/design/tokens";

const toasts = useToasts();
const route = useRoute();

const runs = ref<Run[]>([]);
const responses = ref<ResponseDetail[]>([]);
const brands = ref<Brand[]>([]);
const selectedRunId = ref<number | null>(null);
const selectedId = ref<number | null>(null);
const loadingRuns = ref(true);
const loadingResponses = ref(false);

const pendingSelectedId = ref<number | null>(null);

// Filters
const filterSource = ref<string | null>(null);
const filterIntent = ref<IntentType | null>(null);
const filterMentioned = ref<"all" | "mentioned" | "missed" | "recommended">("all");
const search = ref("");

const intents: IntentType[] = ["transactional", "informational", "comparative", "brand", "local"];

async function loadInitial() {
  loadingRuns.value = true;
  try {
    const queryResponse = Number(route.query.response);
    if (queryResponse) pendingSelectedId.value = queryResponse;

    const [r, b] = await Promise.all([api.listRuns(), api.listBrands()]);
    runs.value = r;
    brands.value = b;
    if (r.length > 0) {
      const queryRun = Number(route.query.run);
      const match = queryRun && r.find((run) => run.id === queryRun);
      selectedRunId.value = match ? match.id : r[0].id;
    }
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load");
  } finally {
    loadingRuns.value = false;
  }
}

async function loadResponses() {
  if (!selectedRunId.value) return;
  loadingResponses.value = true;
  try {
    responses.value = await api.responsesForRun(selectedRunId.value, {
      source: filterSource.value ?? undefined,
      intent: filterIntent.value ?? undefined,
      // Only push the "mentioned: yes/no" filter to the backend in those
      // exact modes. The "recommended" segment filters client-side
      // because the backend doesn't expose a recommended-only flag.
      mentioned:
        filterMentioned.value === "mentioned"
          ? true
          : filterMentioned.value === "missed"
            ? false
            : undefined,
      q: search.value || undefined,
    });
    const pending = pendingSelectedId.value;
    if (pending && responses.value.find((r) => r.id === pending)) {
      selectedId.value = pending;
      pendingSelectedId.value = null;
    } else if (!responses.value.find((r) => r.id === selectedId.value)) {
      selectedId.value = filteredResponses.value[0]?.id ?? null;
      pendingSelectedId.value = null;
    }
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load responses");
  } finally {
    loadingResponses.value = false;
  }
}

watch(
  [selectedRunId, filterSource, filterIntent, filterMentioned, search],
  loadResponses,
);

// Counts for the segment chips. Computed from the unfiltered loaded set
// so the numbers stay stable as the user clicks between segments.
const counts = computed(() => {
  const all = responses.value.length;
  let mentioned = 0;
  let recommended = 0;
  for (const r of responses.value) {
    if (selfMentioned(r)) mentioned++;
    if (selfRecommended(r)) recommended++;
  }
  return { all, mentioned, missed: all - mentioned, recommended };
});

const filteredResponses = computed(() => {
  if (filterMentioned.value === "recommended") {
    return responses.value.filter((r) => selfRecommended(r));
  }
  return responses.value;
});

// When filter changes, ensure selected item is visible
watch(filteredResponses, (list) => {
  if (list.length > 0 && !list.find((r) => r.id === selectedId.value)) {
    selectedId.value = list[0].id;
  }
});

const selected = computed(() =>
  responses.value.find((r) => r.id === selectedId.value) ?? null,
);

const sourceOptions = computed(() => {
  const seen = new Map<string, string>();
  for (const r of responses.value) seen.set(r.source, r.source_name);
  return [
    { id: "all", name: "All sources" },
    ...Array.from(seen.entries()).map(([id, name]) => ({ id, name })),
  ];
});

function selfMentioned(r: ResponseDetail): boolean {
  return r.analyses.some((a) => a.is_self && a.brand_found);
}
function selfRecommended(r: ResponseDetail): boolean {
  return r.analyses.some((a) => a.is_self && a.recommended);
}
function selfSentiment(r: ResponseDetail): Sentiment | null {
  const a = r.analyses.find((x) => x.is_self && x.brand_found);
  return a?.sentiment ?? null;
}
function competitorBrandsMentioned(r: ResponseDetail): string[] {
  return r.analyses.filter((a) => !a.is_self && a.brand_found).map((a) => a.brand_name);
}

const responseBodyEl = ref<HTMLElement | null>(null);

const renderedDetail = computed(() => {
  if (!selected.value) return "";
  let out = renderMarkdown(selected.value.text);
  for (const a of selected.value.analyses) {
    const brand = brands.value.find((b) => b.id === a.brand_id);
    if (!brand) continue;
    const terms = [brand.name, ...brand.aliases];
    const className = brand.is_self ? "mark-self" : "mark-competitor";
    out = highlightTerms(out, terms, className, brand.id);
  }
  return out;
});

function flash(el: HTMLElement, cls: string) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

function jumpToBrand(brandId: number) {
  const mark = responseBodyEl.value?.querySelector(
    `mark[data-brand-id="${brandId}"]`,
  ) as HTMLElement | null;
  if (mark) {
    mark.scrollIntoView({ behavior: "smooth", block: "center" });
    flash(mark, "mark--flash");
    return;
  }
  const sourcePill = document.querySelector(
    `a[data-brand-id="${brandId}"]`,
  ) as HTMLElement | null;
  if (sourcePill) {
    sourcePill.scrollIntoView({ behavior: "smooth", block: "nearest" });
    flash(sourcePill, "source--flash");
    return;
  }
  toasts.error("Brand was matched by the LLM but couldn't be located in the response text or sources.");
}

function urlBrandLabel(url: string): string {
  const host = hostname(url);
  for (const brand of brands.value) {
    if (brand.domains.some((d) => host.includes(d.toLowerCase()))) return brand.name;
  }
  return host;
}
function urlBrandId(url: string): number | null {
  const host = hostname(url);
  for (const brand of brands.value) {
    if (brand.domains.some((d) => host.includes(d.toLowerCase()))) return brand.id;
  }
  return null;
}
function urlBrandIsSelf(url: string): boolean {
  const host = hostname(url);
  for (const brand of brands.value) {
    if (brand.domains.some((d) => host.includes(d.toLowerCase()))) return brand.is_self;
  }
  return false;
}

function copyResponse() {
  if (!selected.value) return;
  navigator.clipboard.writeText(selected.value.text).then(
    () => toasts.success("Response copied"),
    () => toasts.error("Copy failed"),
  );
}

function shortTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const runOptions = computed(() =>
  runs.value.map((r) => ({
    label: `Run #${r.id} — ${date(r.started_at)} (${r.status})`,
    value: r.id,
  })),
);

onMounted(loadInitial);
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("responses.title") }}</h1>
      <p class="dek mt-1">
        {{ t("responses.dek") }} · {{ responses.length }} loaded · run
        <span v-if="selectedRunId" class="font-mono">#{{ selectedRunId }}</span>
      </p>
    </div>
    <div class="flex items-center gap-2">
      <Select
        v-if="runs.length"
        v-model="selectedRunId"
        :options="runOptions"
        class="!w-72"
      />
      <button
        type="button"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
        @click="loadResponses"
        :disabled="loadingResponses"
      >
        <RefreshCw class="h-3 w-3" :class="loadingResponses ? 'animate-spin' : ''" />
        Re-analyze
      </button>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
        @click="toasts.error('Export not implemented yet')"
      >
        <Download class="h-3 w-3" />
        Export CSV
      </button>
    </div>
  </div>

  <!-- Filter row -->
  <div
    v-if="!loadingRuns && runs.length"
    class="flex items-center gap-2 py-2.5 px-4 border border-[var(--color-line)] rounded-lg mb-3 bg-[var(--color-surface)] text-[12px] flex-wrap"
  >
    <span class="cap !text-[11px] !tracking-[0.04em] mr-1">Source</span>
    <button
      v-for="s in sourceOptions"
      :key="s.id"
      type="button"
      @click="filterSource = s.id === 'all' ? null : s.id"
      :class="[
        'border rounded-md py-[3px] px-2.5 text-[12px] cursor-pointer transition-colors',
        ((filterSource === null && s.id === 'all') || filterSource === s.id)
          ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
          : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
      ]"
    >{{ s.name }}</button>

    <span class="w-px h-[18px] bg-[var(--color-line)] mx-1" />

    <span class="cap !text-[11px] !tracking-[0.04em] mr-1">Intent</span>
    <button
      type="button"
      @click="filterIntent = null"
      :class="[
        'border rounded-md py-[3px] px-2.5 text-[12px] cursor-pointer transition-colors capitalize',
        filterIntent === null
          ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
          : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
      ]"
    >Any</button>
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
  </div>

  <div v-if="loadingRuns" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <Card v-else-if="!runs.length" class="text-center py-16">
    <Inbox class="h-10 w-10 mx-auto text-[var(--color-fg-muted)] stroke-[1.4]" />
    <h3 class="text-[18px] font-semibold mt-4">No runs yet</h3>
    <p class="text-sm text-[var(--color-fg-2)] mt-2">
      Trigger your first run from the Runs page.
    </p>
  </Card>

  <!-- Master / detail shell -->
  <div
    v-else
    class="grid bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden min-h-[720px]"
    style="grid-template-columns: 380px 1fr;"
  >
    <!-- Master pane -->
    <div class="flex flex-col bg-[var(--color-bg)] border-r border-[var(--color-line)] min-h-0">
      <!-- List head -->
      <div class="flex items-center justify-between py-3 px-3.5 border-b border-[var(--color-line)] bg-[var(--color-surface)]">
        <p class="text-[12px] text-[var(--color-fg-2)]">
          <strong class="text-[var(--color-fg)] font-semibold">{{ filteredResponses.length }}</strong>
          of {{ responses.length }} responses
        </p>
        <span class="text-[11px] text-[var(--color-fg-muted)]">Sort: time ↓</span>
      </div>
      <!-- Search -->
      <div class="py-2 px-3 border-b border-[var(--color-line)] bg-[var(--color-surface)] relative">
        <Search class="absolute left-5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[var(--color-fg-muted)] pointer-events-none" />
        <input
          v-model="search"
          type="text"
          placeholder="Search prompts, brands, or response text…"
          class="w-full border border-[var(--color-line)] bg-[var(--color-bg)] rounded-md py-1.5 pl-7 pr-2.5 text-[12px] outline-none focus:border-[var(--color-accent)] focus:bg-[var(--color-surface)]"
        />
      </div>
      <!-- Segments -->
      <div class="flex py-2 px-3 gap-1 border-b border-[var(--color-line)] bg-[var(--color-surface)]">
        <button
          v-for="s in [
            { k: 'all',         label: 'All',       n: counts.all },
            { k: 'mentioned',   label: 'Mentioned', n: counts.mentioned },
            { k: 'missed',      label: 'Missed',    n: counts.missed },
            { k: 'recommended', label: 'Rec',       n: counts.recommended },
          ] as const"
          :key="s.k"
          type="button"
          @click="filterMentioned = s.k"
          :class="[
            'flex-1 text-center py-1.5 px-2 text-[11px] font-medium rounded-md transition-colors',
            filterMentioned === s.k
              ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)]'
              : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
          ]"
        >
          {{ s.label }}<span class="font-mono text-[10px] text-[var(--color-fg-muted)] ml-1">{{ s.n }}</span>
        </button>
      </div>

      <!-- Loading / empty -->
      <div v-if="loadingResponses" class="flex justify-center py-10">
        <Loader2 class="h-4 w-4 animate-spin text-[var(--color-fg-muted)]" />
      </div>
      <p
        v-else-if="filteredResponses.length === 0"
        class="text-center text-[var(--color-fg-muted)] text-[12px] py-6"
      >No responses match these filters.</p>

      <!-- Rows -->
      <div v-else class="flex-1 overflow-auto min-h-0">
        <div
          v-for="r in filteredResponses"
          :key="r.id"
          @click="selectedId = r.id"
          :class="[
            'relative grid gap-x-2.5 gap-y-1 py-3 px-3.5 border-b border-[var(--color-line-soft)] cursor-pointer hover:bg-[var(--color-surface-2)]',
            selectedId === r.id ? 'bg-[var(--color-surface)] before:content-[\'\'] before:absolute before:left-0 before:top-0 before:bottom-0 before:w-[3px] before:bg-[var(--color-accent)]' : '',
          ]"
          style="grid-template-columns: 1fr auto"
        >
          <div class="flex items-center gap-1.5 text-[12px]">
            <span class="w-[7px] h-[7px] rounded-sm bg-[var(--color-accent)]" />
            <span class="font-semibold text-[var(--color-fg)]">{{ r.source_name }}</span>
            <span class="font-mono text-[10.5px] text-[var(--color-fg-muted)] ml-auto">{{ shortTime(r.created_at) }}</span>
          </div>
          <p
            class="col-span-full text-[12.5px] italic line-clamp-2 leading-snug text-[var(--color-fg)]"
          >"{{ r.prompt_text }}"</p>
          <div class="col-span-full flex items-center gap-1.5 flex-wrap mt-0.5">
            <span
              v-if="selfMentioned(r)"
              class="font-mono text-[10px] font-semibold py-px px-1.5 rounded bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
            >Named</span>
            <span
              v-else
              class="font-mono text-[10px] font-semibold py-px px-1.5 rounded bg-[var(--color-surface-3)] text-[var(--color-fg-muted)]"
            >—</span>
            <span
              class="inline-flex items-center py-px px-1.5 border border-[var(--color-line)] rounded text-[10px] font-medium text-[var(--color-fg-2)] capitalize"
            >{{ r.prompt_intent }}</span>
            <span
              v-if="selfRecommended(r)"
              class="inline-flex items-center py-px px-1.5 rounded text-[10px] font-semibold bg-[var(--color-accent)] text-white"
            >Rec</span>
            <span
              v-if="selfSentiment(r)"
              class="w-1.5 h-1.5 rounded-full"
              :style="{ background: sentimentColors[selfSentiment(r) ?? 'neutral'] }"
              :title="selfSentiment(r) ?? ''"
            />
            <span
              v-if="r.source_urls && r.source_urls.length"
              class="ml-auto font-mono text-[10.5px] text-[var(--color-fg-2)]"
            >{{ r.source_urls.length }} src</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Detail pane -->
    <div v-if="selected" class="flex flex-col min-h-0 bg-[var(--color-surface)]">
      <!-- Detail header -->
      <header class="py-4 px-5 border-b border-[var(--color-line)]">
        <div class="flex items-center gap-2.5 flex-wrap mb-2.5">
          <span class="w-2.5 h-2.5 rounded-sm bg-[var(--color-accent)]" />
          <span class="text-[13px] font-semibold text-[var(--color-fg)]">{{ selected.source_name }}</span>
          <span class="font-mono text-[11px] text-[var(--color-fg-muted)]">· {{ shortTime(selected.created_at) }}</span>
          <span
            class="inline-flex items-center py-px px-1.5 border border-[var(--color-line)] rounded text-[11px] font-medium text-[var(--color-fg-2)] capitalize"
          >{{ selected.prompt_intent }}</span>
          <div class="ml-auto flex gap-1.5">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 py-1 px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
              @click="copyResponse"
            >
              <Copy class="h-3 w-3" /> Copy
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 py-1 px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] font-medium text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] transition-colors"
              @click="toasts.error('Flag not implemented yet')"
            >
              <Flag class="h-3 w-3" /> Flag
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 py-1 px-2.5 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] font-medium hover:bg-[var(--color-fg-2)] transition-colors"
              @click="toasts.error('Annotate not implemented yet')"
            >
              <Plus class="h-3 w-3" /> Annotate
            </button>
          </div>
        </div>
        <h2 class="text-[18px] font-semibold tracking-[-0.015em] leading-snug m-0 text-[var(--color-fg)]">
          "{{ selected.prompt_text }}"
        </h2>
      </header>

      <!-- 4 stat tiles -->
      <div class="grid grid-cols-4 border-b border-[var(--color-line)]">
        <div class="py-3 px-4 border-r border-[var(--color-line)]">
          <p class="cap !text-[10.5px] !tracking-[0.04em] mb-1">You named</p>
          <p
            class="text-[18px] font-semibold tracking-[-0.01em]"
            :class="selfMentioned(selected) ? 'text-[var(--color-fg)]' : 'text-[var(--color-fg-muted)]'"
          >{{ selfMentioned(selected) ? "Yes" : "No" }}</p>
        </div>
        <div class="py-3 px-4 border-r border-[var(--color-line)]">
          <p class="cap !text-[10.5px] !tracking-[0.04em] mb-1">Sentiment</p>
          <p
            class="text-[18px] font-semibold tracking-[-0.01em] capitalize"
            :style="{ color: selfSentiment(selected) ? sentimentColors[selfSentiment(selected) ?? 'neutral'] : 'var(--color-fg-muted)' }"
          >
            {{ selfSentiment(selected) ?? "n/a" }}
          </p>
        </div>
        <div class="py-3 px-4 border-r border-[var(--color-line)]">
          <p class="cap !text-[10.5px] !tracking-[0.04em] mb-1">Recommended</p>
          <p
            class="text-[18px] font-semibold tracking-[-0.01em]"
            :class="selfRecommended(selected) ? 'text-[var(--color-fg)]' : 'text-[var(--color-fg-muted)]'"
          >{{ selfRecommended(selected) ? "Yes" : "No" }}</p>
        </div>
        <div class="py-3 px-4">
          <p class="cap !text-[10.5px] !tracking-[0.04em] mb-1">Sources cited</p>
          <p class="text-[18px] font-semibold tracking-[-0.01em] text-[var(--color-fg)]">
            {{ selected.source_urls?.length ?? 0 }}
          </p>
        </div>
      </div>

      <!-- Body grid -->
      <div
        v-if="selected.error_kind"
        class="m-5 p-3 rounded-md bg-[var(--color-danger-soft)] border border-[color-mix(in_oklab,var(--color-danger)_30%,transparent)]"
      >
        <p class="text-sm text-[var(--color-danger)] font-medium">{{ selected.error_kind }}</p>
        <p class="text-xs text-[var(--color-danger)] mt-1 opacity-90">{{ selected.error_message }}</p>
      </div>
      <div
        class="grid gap-6 py-4 px-5 overflow-auto flex-1 items-start"
        style="grid-template-columns: 1fr 280px"
      >
        <div ref="responseBodyEl" class="prose-response" v-html="renderedDetail" />

        <aside class="flex flex-col gap-5 text-[12px]">
          <!-- Sources -->
          <div v-if="selected.source_urls && selected.source_urls.length">
            <h4 class="cap !text-[11px] !tracking-[0.05em] mb-2">Sources</h4>
            <a
              v-for="url in selected.source_urls"
              :key="url"
              :href="url"
              :data-brand-id="urlBrandId(url) ?? undefined"
              target="_blank"
              rel="noopener noreferrer"
              :class="[
                'source-pill flex items-center gap-2 py-1.5 px-2 rounded-md mb-1 text-[11.5px] hover:bg-[var(--color-surface-2)] transition-colors',
                urlBrandIsSelf(url)
                  ? 'bg-[var(--color-accent-soft)] border border-[var(--color-accent)]'
                  : 'border border-[var(--color-line)]',
              ]"
            >
              <span
                class="w-1.5 h-1.5 rounded-full shrink-0"
                :style="{ background: urlBrandIsSelf(url) ? 'var(--color-accent)' : 'var(--color-fg-muted)' }"
              />
              <span class="font-mono text-[11px] flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{{ urlBrandLabel(url) }}</span>
              <ArrowUpRight class="h-3 w-3 text-[var(--color-fg-muted)] shrink-0" />
            </a>
          </div>

          <!-- Competitors mentioned -->
          <div v-if="competitorBrandsMentioned(selected).length > 0">
            <h4 class="cap !text-[11px] !tracking-[0.05em] mb-2">Competitors mentioned</h4>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="c in competitorBrandsMentioned(selected)"
                :key="c"
                class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium bg-[var(--color-highlight-soft)] text-[var(--color-highlight)]"
              >{{ c }}</span>
            </div>
          </div>

          <!-- Brand analysis (replaces "Across LLMs same prompt" — we don't yet
               aggregate cross-source positions for the same prompt, so we show
               the per-brand analysis for this response instead) -->
          <div v-if="selected.analyses.length">
            <h4 class="cap !text-[11px] !tracking-[0.05em] mb-2">Brand analysis</h4>
            <div
              v-for="a in selected.analyses"
              :key="a.brand_id"
              :class="[
                'grid items-center gap-2 py-1.5 px-2 rounded-md text-[11.5px]',
                a.is_self ? 'bg-[var(--color-accent-soft)]' : '',
                a.brand_found ? 'cursor-pointer hover:bg-[var(--color-surface-2)] transition-colors' : '',
              ]"
              style="grid-template-columns: auto 1fr auto"
              @click="a.brand_found && jumpToBrand(a.brand_id)"
            >
              <span
                class="w-2 h-2 rounded-sm shrink-0"
                :style="{ background: a.is_self ? 'var(--color-accent)' : 'var(--color-fg-muted)' }"
              />
              <span class="font-medium truncate">
                {{ a.brand_name }}
                <span
                  v-if="a.is_self"
                  class="ml-1 inline-block bg-[var(--color-accent)] text-white text-[9px] font-mono px-1 py-px rounded"
                >YOU</span>
              </span>
              <span
                v-if="a.brand_found"
                :class="[
                  'font-mono text-[10px] font-semibold py-px px-1.5 rounded',
                  a.recommended
                    ? 'bg-[var(--color-warning-soft)] text-[var(--color-warning)]'
                    : 'bg-[var(--color-accent-soft)] text-[var(--color-accent)]',
                ]"
              >{{ a.recommended ? "Rec" : "✓" }}</span>
              <span
                v-else
                class="font-mono text-[10px] py-px px-1.5 rounded bg-[var(--color-surface-3)] text-[var(--color-fg-muted)]"
              >—</span>
            </div>
          </div>

          <!-- Search queries -->
          <div v-if="selected.search_queries && selected.search_queries.length">
            <h4 class="cap !text-[11px] !tracking-[0.05em] mb-2">Search queries</h4>
            <div class="flex flex-wrap gap-1">
              <span
                v-for="q in selected.search_queries"
                :key="q"
                class="inline-flex items-center py-0.5 px-2 rounded text-[11px] font-medium bg-[var(--color-info-soft)] text-[var(--color-info)] font-mono"
              >{{ q }}</span>
            </div>
          </div>
        </aside>
      </div>
    </div>

    <div v-else class="flex flex-col items-center justify-center text-center px-8">
      <MessageSquare class="h-10 w-10 text-[var(--color-fg-muted)] stroke-[1.4]" />
      <h3 class="text-[18px] font-semibold mt-4">Select a response</h3>
      <p class="text-sm text-[var(--color-fg-2)] mt-2">
        Pick a response from the list to see its full text, sources, and analysis.
      </p>
    </div>
  </div>
</template>

<style>
/* Brand highlights inside the markdown response.
   Self brand → cobalt soft; competitor → amber soft. */
.prose-response {
  color: var(--color-fg);
  font-size: 14px;
  line-height: 1.65;
  max-width: 68ch;
}
.prose-response p { margin-bottom: 0.85rem; }
.prose-response h2,
.prose-response h3,
.prose-response h4,
.prose-response h5 {
  font-weight: 600;
  letter-spacing: -0.015em;
  margin-top: 1.4rem;
  margin-bottom: 0.5rem;
  color: var(--color-fg);
}
.prose-response h3 { font-size: 16px; }
.prose-response h4 { font-size: 14px; }
.prose-response ul,
.prose-response ol { margin-bottom: 0.85rem; padding-left: 1.25rem; }
.prose-response ul li { list-style: disc; margin-bottom: 0.25rem; }
.prose-response ol li { list-style: decimal; margin-bottom: 0.25rem; }
.prose-response a {
  color: var(--color-accent);
  text-decoration: underline;
  text-underline-offset: 2px;
  text-decoration-thickness: 1px;
}
.prose-response .ref-cite {
  font-size: 0.625rem;
  line-height: 1;
  vertical-align: super;
  margin: 0 0.0625rem;
}
.prose-response .ref-cite a {
  display: inline-block;
  min-width: 1rem;
  padding: 0 0.25rem;
  border-radius: 3px;
  background: var(--color-accent-soft);
  color: var(--color-accent);
  font-weight: 600;
  text-decoration: none;
  text-align: center;
}
.mark-self {
  background: var(--color-accent-soft);
  color: var(--color-fg);
  border-radius: 3px;
  padding: 1px 4px;
  font-weight: 600;
  border-bottom: 2px solid var(--color-accent);
  scroll-margin-top: 2rem;
}
.mark-competitor {
  background: var(--color-highlight-soft);
  color: var(--color-fg);
  border-radius: 3px;
  padding: 1px 4px;
  font-weight: 500;
  border-bottom: 2px solid var(--color-highlight);
}
.mark--flash {
  animation: mark-flash 1.4s ease-out;
}
@keyframes mark-flash {
  0% {
    box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-accent), transparent 50%);
    background: color-mix(in srgb, var(--color-accent), transparent 35%);
  }
  100% { box-shadow: 0 0 0 0 transparent; }
}
.source-pill { scroll-margin-top: 2rem; }
.source--flash { animation: source-flash 1.4s ease-out; }
@keyframes source-flash {
  0% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-accent), transparent 55%); }
  100% { box-shadow: 0 0 0 0 transparent; }
}
</style>
