<script setup lang="ts">
/**
 * Search-term frequency table.
 *
 * Surfaces what the AI actually searches for during grounding —
 * read straight from `Response.search_queries`. High-signal for
 * content strategy: these are the terms AI gravitates to when
 * answering questions in our category, not what users typed in.
 */
import { onMounted, ref, computed } from "vue";
import { Loader2 } from "lucide-vue-next";
import { api, ApiError } from "@/api/client";
import type { SearchTermStat } from "@/api/types";
import { t } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();

const loading = ref(true);
const terms = ref<SearchTermStat[]>([]);
const days = ref<7 | 30 | 90>(30);

async function load() {
  loading.value = true;
  try {
    terms.value = await api.searchTerms({ days: days.value, limit: 100, min_count: 2 });
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load");
  } finally {
    loading.value = false;
  }
}

const maxCount = computed(() => Math.max(1, ...terms.value.map((t) => t.count)));

function reload(d: 7 | 30 | 90) {
  days.value = d;
  load();
}

onMounted(load);
</script>

<template>
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("search_terms.title") }}</h1>
      <p class="dek mt-1">{{ t("search_terms.dek", { days: days }) }}</p>
    </div>
    <div class="inline-flex items-center border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[12px] overflow-hidden">
      <button
        v-for="opt in ([7, 30, 90] as const)"
        :key="opt"
        type="button"
        @click="reload(opt)"
        :class="[
          'py-[5px] px-2.5 transition-colors border-r border-[var(--color-line)] last:border-r-0',
          days === opt
            ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] font-medium'
            : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
        ]"
      >{{ opt }}d</button>
    </div>
  </div>

  <div v-if="loading" class="flex justify-center py-16">
    <Loader2 class="h-5 w-5 animate-spin text-[var(--color-fg-muted)]" />
  </div>

  <p
    v-else-if="terms.length === 0"
    class="text-sm text-[var(--color-fg-muted)] text-center py-12"
  >No grounding queries captured yet.</p>

  <section
    v-else
    class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
  >
    <table class="w-full border-collapse text-[13px]">
      <thead>
        <tr class="bg-[var(--color-bg)]">
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)]">Term</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Count</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Prompts</th>
          <th class="text-right text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] font-mono">Sources</th>
          <th class="text-left text-[11px] uppercase tracking-[0.04em] text-[var(--color-fg-muted)] font-semibold py-2.5 px-4 border-b border-[var(--color-line)] w-[180px]"></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in terms" :key="t.term" class="hover:bg-[var(--color-bg)]">
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-[12.5px]">{{ t.term }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right">{{ t.count }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-2)]">{{ t.prompt_count }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)] font-mono text-right text-[var(--color-fg-2)]">{{ t.source_count }}</td>
          <td class="py-2.5 px-4 border-b border-[var(--color-line-soft)]">
            <span class="block h-[6px] rounded-[3px] bg-[var(--color-surface-3)] overflow-hidden">
              <span
                class="block h-full bg-[var(--color-accent)] rounded-[3px]"
                :style="{ width: `${(t.count / maxCount) * 100}%` }"
              />
            </span>
          </td>
        </tr>
      </tbody>
    </table>
  </section>
</template>
