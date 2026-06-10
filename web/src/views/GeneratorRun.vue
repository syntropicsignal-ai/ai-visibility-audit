<script setup lang="ts">
/**
 * Prompt-generator run review.
 *
 * Kicks off a run for a domain, polls staged progress while it's in
 * flight, and shows the resulting profile, competitors, corpus,
 * personas, and queries.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { Loader2, Play, RefreshCcw, CheckCircle2, XCircle, Circle } from "lucide-vue-next";

interface RunProfile {
  brand_name?: string;
  language?: string;
  country?: string;
  currency?: string;
  distribution?: string;
  customer_type?: string;
  product_categories?: string[];
  key_products?: string[];
  domain_terms?: string[];
  seasonal_factors?: string[];
  tone?: string;
  summary?: string;
}

interface CorpusSample {
  text: string;
  source: string;
  seed?: string | null;
  intent?: string | null;
  length_mode?: string | null;
  score?: number | null;
}

interface RunPersona {
  name: string;
  goal: string;
  vocabulary_samples: string[];
  constraints: string[];
  typical_intents: string[];
}

interface RunPayload {
  id: number;
  domain: string;
  created_at: string | null;
  sources_meta: {
    pages?: number;
    competitor_count?: number;
    client_keywords_count?: number;
    corpus_counts?: { wildchat?: number; paa?: number; suggestion?: number };
    persona_count?: number;
  };
  profile: RunProfile;
  competitors: { name?: string; brand_name?: string; domain?: string }[];
  corpus: {
    counts: { wildchat?: number; paa?: number; suggestion?: number };
    seed_terms: string[];
    warnings: string[];
    samples: CorpusSample[];
  };
  personas: RunPersona[];
  keyword_signals: {
    client_keywords?: { keyword: string; position: number; search_volume: number | null }[];
    gap_keywords?: { keyword: string; position: number; search_volume: number | null }[];
  };
  queries: {
    text: string;
    intent: string;
    length_mode?: string;
    buyer_stage?: string;
    shape?: number;
    tags?: string[];
    seed_source?: string | null;
    seed_keyword?: string | null;
  }[];
}

interface RunDetail {
  domain: string;
  run: RunPayload;
}

interface RunIndex {
  id: number;
  domain: string;
  created_at: string | null;
  sources_meta: { pages?: number; competitor_count?: number; client_keywords_count?: number };
  brand_name: string | null;
  queries_count: number;
}

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
}

const domain = ref("");
const numQueries = ref(50);
const loading = ref(false);
const errorMsg = ref<string | null>(null);
const detail = ref<RunDetail | null>(null);
const index = ref<RunIndex[]>([]);

const liveStatus = ref<PipelineStatus | null>(null);
let pollTimer: number | null = null;

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/v1${url}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.json();
}

async function loadIndex() {
  index.value = await fetchJSON<RunIndex[]>("/generator");
}

async function loadDetail(d: string) {
  errorMsg.value = null;
  detail.value = null;
  try {
    detail.value = await fetchJSON<RunDetail>(`/generator/${encodeURIComponent(d)}`);
    domain.value = d;
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e);
  }
}

function stopPolling() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

async function pollOnce(pipelineRunId: number, targetDomain: string) {
  try {
    const status = await fetchJSON<PipelineStatus>(`/generator/run-status/${pipelineRunId}`);
    liveStatus.value = status;
    if (status.status === "running") {
      pollTimer = window.setTimeout(() => pollOnce(pipelineRunId, targetDomain), 1500);
    } else {
      // Run finished — refresh index + detail. Keep liveStatus visible so
      // the user can see the completed timeline above the result.
      stopPolling();
      loading.value = false;
      await Promise.all([loadIndex(), loadDetail(targetDomain)]);
    }
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e);
    stopPolling();
    loading.value = false;
  }
}

async function runGenerator() {
  if (!domain.value.trim()) return;
  errorMsg.value = null;
  liveStatus.value = null;
  detail.value = null;
  loading.value = true;
  stopPolling();
  const target = domain.value.trim();
  try {
    const { pipeline_run_id } = await fetchJSON<{ pipeline_run_id: number }>(
      "/generator/run-async",
      {
        method: "POST",
        body: JSON.stringify({ domain: target, num_queries: numQueries.value }),
      },
    );
    await pollOnce(pipeline_run_id, target);
  } catch (e: any) {
    errorMsg.value = e?.message ?? String(e);
    loading.value = false;
  }
}

onMounted(loadIndex);
onUnmounted(stopPolling);

const profile = computed(() => detail.value?.run.profile ?? null);
const sourcesMeta = computed(() => detail.value?.run.sources_meta ?? {});
const corpus = computed(() => detail.value?.run.corpus ?? null);
const personas = computed(() => detail.value?.run.personas ?? []);

function corpusSamplesBySource(source: string, limit = 12): CorpusSample[] {
  if (!corpus.value) return [];
  return corpus.value.samples.filter((s) => s.source === source).slice(0, limit);
}
</script>

<template>
  <div class="page">
    <header class="page-head">
      <h1>prompt generator</h1>
      <p class="sub">
        Pick a domain and run the prompt-generator pipeline. Inspect the
        resulting profile, competitors, corpus, personas, and queries.
      </p>
    </header>

    <section class="run-bar">
      <input
        v-model="domain"
        type="text"
        placeholder="domain (e.g. example.com)"
        class="domain-input"
        @keydown.enter="runGenerator"
      />
      <input v-model.number="numQueries" type="number" min="1" max="200" class="num-input" />
      <button :disabled="loading || !domain.trim()" class="btn primary" @click="runGenerator">
        <Loader2 v-if="loading" class="icon spin" />
        <Play v-else class="icon" />
        run
      </button>
      <button class="btn" @click="loadIndex"><RefreshCcw class="icon" /> refresh</button>
    </section>

    <section v-if="errorMsg" class="error">{{ errorMsg }}</section>

    <section v-if="liveStatus" class="card live-panel">
      <div class="card-head">
        live pipeline run · {{ liveStatus.domain }} ·
        <span :class="['live-status', liveStatus.status]">{{ liveStatus.status }}</span>
        <span v-if="liveStatus.error" class="muted error-inline">— {{ liveStatus.error }}</span>
      </div>
      <ol class="stage-list">
        <li v-for="(s, i) in liveStatus.stages" :key="i" :class="['stage-item', s.status]">
          <div class="stage-icon">
            <CheckCircle2 v-if="s.status === 'completed'" class="icon" />
            <Loader2 v-else-if="s.status === 'running'" class="icon spin" />
            <XCircle v-else-if="s.status === 'failed'" class="icon" />
            <Circle v-else class="icon" />
          </div>
          <div class="stage-body">
            <div class="stage-name">{{ s.stage }}</div>
            <div class="stage-summary">{{ s.summary }}</div>
            <div v-if="s.warnings && s.warnings.length" class="stage-warnings">
              <div v-for="w in s.warnings" :key="w" class="caveat">{{ w }}</div>
            </div>
          </div>
        </li>
      </ol>
    </section>

    <section class="index-bar">
      <div class="index-label">recent runs:</div>
      <button
        v-for="r in index"
        :key="r.id"
        class="chip"
        :class="{ active: detail?.domain === r.domain }"
        @click="loadDetail(r.domain)"
      >
        {{ r.domain }} <span class="chip-meta">· {{ r.queries_count }}q</span>
      </button>
      <span v-if="!index.length" class="muted">no runs yet — start one above</span>
    </section>

    <section v-if="detail" class="result">
      <div class="meta">
        <span class="badge" :class="{ ok: sourcesMeta.client_keywords_count, miss: !sourcesMeta.client_keywords_count }">
          DFS keywords: {{ sourcesMeta.client_keywords_count ?? 0 }}
        </span>
        <span class="badge" :class="{ ok: sourcesMeta.pages, miss: !sourcesMeta.pages }">
          Exa pages: {{ sourcesMeta.pages ?? 0 }}
        </span>
        <span class="badge">competitors: {{ sourcesMeta.competitor_count ?? 0 }}</span>
      </div>

      <h2>profile</h2>
      <div class="card">
        <table class="kv">
          <tbody>
          <tr><th>brand</th><td>{{ profile?.brand_name }}</td></tr>
          <tr><th>language</th><td>{{ profile?.language }}</td></tr>
          <tr><th>country</th><td>{{ profile?.country }}</td></tr>
          <tr><th>customer</th><td>{{ profile?.customer_type }} · {{ profile?.distribution }}</td></tr>
          <tr><th>categories</th><td><div class="tags"><span v-for="c in profile?.product_categories" :key="c" class="tag">{{ c }}</span></div></td></tr>
          <tr><th>key products</th><td><div class="tags"><span v-for="p in profile?.key_products" :key="p" class="tag">{{ p }}</span></div></td></tr>
          <tr><th>domain terms</th><td><div class="tags"><span v-for="t in profile?.domain_terms" :key="t" class="tag soft">{{ t }}</span></div></td></tr>
          <tr><th>summary</th><td><p class="summary">{{ profile?.summary }}</p></td></tr>
          </tbody>
        </table>
      </div>

      <h2>category corpus</h2>
      <div v-if="corpus" class="card">
        <div class="meta">
          <span class="badge ok">WildChat: {{ corpus.counts.wildchat || 0 }}</span>
          <span class="badge ok">PAA: {{ corpus.counts.paa || 0 }}</span>
          <span class="badge ok">suggestions: {{ corpus.counts.suggestion || 0 }}</span>
          <span v-for="w in corpus.warnings" :key="w" class="badge warn">{{ w }}</span>
        </div>
        <p class="muted">
          Seed terms: <code>{{ corpus.seed_terms.join(", ") }}</code>
        </p>
        <div v-if="corpusSamplesBySource('paa').length" class="corpus-section">
          <h3>People-Also-Ask (Google-measured)</h3>
          <ul class="corpus-list">
            <li v-for="(s, i) in corpusSamplesBySource('paa', 10)" :key="`paa-${i}`">
              <span class="muted">({{ s.seed }})</span> {{ s.text }}
            </li>
          </ul>
        </div>
        <div v-if="corpusSamplesBySource('wildchat').length" class="corpus-section">
          <h3>WildChat (real ChatGPT conversations, top by similarity)</h3>
          <ul class="corpus-list">
            <li v-for="(s, i) in corpusSamplesBySource('wildchat', 10)" :key="`wc-${i}`">
              <span v-if="s.score" class="tag soft mini">{{ s.score.toFixed(2) }}</span>
              {{ s.text }}
            </li>
          </ul>
        </div>
        <div v-if="corpusSamplesBySource('suggestion').length" class="corpus-section">
          <h3>Google search suggestions</h3>
          <ul class="corpus-list">
            <li v-for="(s, i) in corpusSamplesBySource('suggestion', 12)" :key="`sg-${i}`">
              {{ s.text }}
            </li>
          </ul>
        </div>
      </div>
      <p v-else class="muted">no corpus on this run</p>

      <h2>personas ({{ personas.length }})</h2>
      <div v-if="personas.length" class="persona-grid">
        <div v-for="(p, i) in personas" :key="i" class="card persona">
          <div class="persona-name">{{ p.name }}</div>
          <p class="persona-goal">{{ p.goal }}</p>
          <div v-if="p.vocabulary_samples.length" class="persona-section">
            <div class="persona-label">voice samples</div>
            <ul class="corpus-list small">
              <li v-for="v in p.vocabulary_samples.slice(0, 4)" :key="v">{{ v }}</li>
            </ul>
          </div>
          <div v-if="p.constraints.length" class="persona-section">
            <div class="persona-label">constraints</div>
            <div class="tags">
              <span v-for="c in p.constraints" :key="c" class="tag soft">{{ c }}</span>
            </div>
          </div>
          <div v-if="p.typical_intents.length" class="persona-section">
            <div class="persona-label">intents</div>
            <div class="tags">
              <span v-for="t in p.typical_intents" :key="t" class="tag accent">{{ t }}</span>
            </div>
          </div>
        </div>
      </div>
      <p v-else class="muted">no personas on this run</p>

      <h2>competitors</h2>
      <div class="comp-list">
        <span v-for="c in detail.run.competitors" :key="c.domain" class="tag">
          {{ c.name || c.brand_name }} <span class="muted">{{ c.domain }}</span>
        </span>
        <span v-if="!detail.run.competitors.length" class="muted">none</span>
      </div>

      <h2>queries ({{ detail.run.queries.length }})</h2>
      <div class="card">
        <div class="query-list">
          <div v-for="(q, i) in detail.run.queries" :key="i" class="query">
            <div class="q-text">{{ q.text }}</div>
            <div class="q-meta">
              <span class="tag soft">{{ q.intent }}</span>
              <span v-if="q.length_mode" class="tag soft">{{ q.length_mode }}</span>
              <span v-if="q.buyer_stage" class="tag soft">{{ q.buyer_stage }}</span>
              <span v-if="q.seed_keyword" class="tag accent">seed: {{ q.seed_keyword }}</span>
            </div>
          </div>
          <p v-if="!detail.run.queries.length" class="muted">no queries on this run</p>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page { padding: 1.25rem 1.5rem 4rem; max-width: 1400px; margin: 0 auto; color: var(--color-fg); }
.page-head h1 { font-size: 1.4rem; font-weight: 600; margin: 0 0 0.25rem; }
.page-head .sub { color: var(--color-fg-muted); font-size: 0.9rem; margin: 0; }

.run-bar { display: flex; gap: 0.5rem; margin: 1.25rem 0; align-items: center; }
.domain-input, .num-input {
  padding: 0.5rem 0.75rem; border-radius: 6px; border: 1px solid var(--color-line);
  background: var(--color-surface); color: var(--color-fg); font-size: 0.95rem;
}
.domain-input { flex: 1; }
.num-input { width: 80px; }
.btn {
  display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.5rem 0.9rem;
  border-radius: 6px; border: 1px solid var(--color-line);
  background: var(--color-surface); color: var(--color-fg); cursor: pointer; font-size: 0.9rem;
}
.btn:hover:not(:disabled) { background: var(--color-surface-2); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn.primary { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-fg); }
.btn.primary:hover:not(:disabled) { background: var(--color-accent-hover); }
.icon { width: 16px; height: 16px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.error {
  padding: 0.75rem; background: var(--color-danger-soft); color: var(--color-danger);
  border: 1px solid color-mix(in srgb, var(--color-danger), transparent 70%);
  border-radius: 6px; margin-bottom: 1rem; font-family: monospace; font-size: 0.85rem;
}

.index-bar { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1.5rem; align-items: center; }
.index-label { color: var(--color-fg-muted); font-size: 0.85rem; }
.chip {
  padding: 0.25rem 0.6rem; border-radius: 999px; border: 1px solid var(--color-line);
  background: var(--color-surface); color: var(--color-fg-2); font-size: 0.8rem; cursor: pointer;
}
.chip:hover { border-color: var(--color-fg-muted); }
.chip.active { background: var(--color-accent); border-color: var(--color-accent); color: var(--color-accent-fg); }
.chip-meta { color: var(--color-fg-muted); font-size: 0.75rem; }
.chip.active .chip-meta { color: color-mix(in srgb, var(--color-accent-fg), transparent 30%); }

.muted { color: var(--color-fg-muted); font-size: 0.85rem; }

.meta { display: flex; gap: 0.4rem; margin-bottom: 1rem; flex-wrap: wrap; }
.badge {
  padding: 0.2rem 0.6rem; border-radius: 4px; background: var(--color-surface-2);
  color: var(--color-fg-2); font-size: 0.75rem; font-family: monospace;
  border: 1px solid var(--color-line-soft);
}
.badge.ok { background: var(--color-success-soft); color: var(--color-success); border-color: color-mix(in srgb, var(--color-success), transparent 70%); }
.badge.miss { background: var(--color-surface-3); color: var(--color-fg-muted); }
.badge.warn { background: var(--color-warning-soft); color: var(--color-warning); border-color: color-mix(in srgb, var(--color-warning), transparent 70%); }

h2 { font-size: 1.05rem; margin: 1.25rem 0 0.6rem; font-weight: 600; color: var(--color-fg); }
h3 { font-size: 0.95rem; margin: 0.75rem 0 0.4rem; font-weight: 600; color: var(--color-fg-2); }

.card { background: var(--color-surface); border: 1px solid var(--color-line); border-radius: 8px; padding: 0.75rem 1rem 1rem; }
.card-head { font-size: 0.75rem; color: var(--color-fg-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; font-weight: 600; }

.kv { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
.kv th { text-align: left; color: var(--color-fg-muted); font-weight: 400; padding: 0.4rem 0.6rem 0.4rem 0; vertical-align: top; width: 110px; }
.kv td { padding: 0.4rem 0; vertical-align: top; color: var(--color-fg); }
.summary { margin: 0; line-height: 1.5; color: var(--color-fg-2); }

.tags { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.tag {
  padding: 0.15rem 0.5rem; border-radius: 4px; background: var(--color-surface-2);
  color: var(--color-fg); font-size: 0.78rem; border: 1px solid var(--color-line);
}
.tag.soft { background: var(--color-surface); color: var(--color-fg-2); }
.tag.accent { background: var(--color-accent-soft); color: var(--color-accent); border-color: color-mix(in srgb, var(--color-accent), transparent 70%); }

.comp-list { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }

.query-list { display: flex; flex-direction: column; gap: 0.4rem; }
.query { background: var(--color-surface); border: 1px solid var(--color-line); border-radius: 6px; padding: 0.6rem 0.8rem; }
.q-text { color: var(--color-fg); font-size: 0.9rem; line-height: 1.4; margin-bottom: 0.3rem; }
.q-meta { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.caveat { font-size: 0.78rem; line-height: 1.4; padding: 0.45rem 0.6rem; background: var(--color-warning-soft); color: var(--color-warning); border-radius: 4px; margin: 0 0 0.6rem; border: 1px solid color-mix(in srgb, var(--color-warning), transparent 80%); }

.corpus-section { margin-top: 0.85rem; }
.corpus-list { margin: 0.3rem 0 0; padding-left: 1rem; font-size: 0.86rem; color: var(--color-fg); line-height: 1.5; }
.corpus-list li { margin-bottom: 0.2rem; }
.corpus-list.small { font-size: 0.82rem; }
.tag.mini { font-size: 0.68rem; padding: 0 0.35rem; margin-right: 0.3rem; font-family: monospace; }

.persona-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.75rem; }
.persona { padding: 0.75rem 0.9rem; }
.persona-name { font-weight: 600; color: var(--color-fg); margin-bottom: 0.25rem; font-size: 0.92rem; }
.persona-goal { margin: 0 0 0.6rem; color: var(--color-fg-2); font-size: 0.85rem; line-height: 1.4; }
.persona-section { margin-bottom: 0.5rem; }
.persona-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-fg-muted); font-weight: 600; margin-bottom: 0.2rem; }

.live-panel { margin-bottom: 1.25rem; }
.live-status { padding: 0.1rem 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.75rem; }
.live-status.running { background: var(--color-accent-soft); color: var(--color-accent); }
.live-status.completed { background: var(--color-success-soft); color: var(--color-success); }
.live-status.failed { background: var(--color-danger-soft); color: var(--color-danger); }
.error-inline { font-size: 0.78rem; }

.stage-list { list-style: none; padding: 0; margin: 0.5rem 0 0; display: flex; flex-direction: column; gap: 0.4rem; }
.stage-item { display: flex; gap: 0.6rem; padding: 0.4rem 0.55rem; border-radius: 6px; border: 1px solid var(--color-line-soft); background: var(--color-surface); }
.stage-item.running { border-color: color-mix(in srgb, var(--color-accent), transparent 60%); background: color-mix(in srgb, var(--color-accent-soft), transparent 30%); }
.stage-item.failed { border-color: color-mix(in srgb, var(--color-danger), transparent 60%); background: var(--color-danger-soft); }
.stage-icon { flex-shrink: 0; padding-top: 0.05rem; color: var(--color-fg-muted); }
.stage-item.completed .stage-icon { color: var(--color-success); }
.stage-item.running .stage-icon { color: var(--color-accent); }
.stage-item.failed .stage-icon { color: var(--color-danger); }
.stage-body { flex: 1; min-width: 0; }
.stage-name { font-family: monospace; font-size: 0.78rem; color: var(--color-fg-muted); }
.stage-summary { font-size: 0.86rem; color: var(--color-fg); margin-top: 0.1rem; line-height: 1.35; }
.stage-warnings { margin-top: 0.35rem; }
.stage-warnings .caveat { margin: 0.15rem 0 0; }
</style>
