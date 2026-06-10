<script setup lang="ts">
/**
 * Topbar — breadcrumbs + Setup, refresh, and the locale picker.
 *
 * Crumbs render from `route.meta.crumbs` if a view provides them;
 * otherwise the crumb is derived from `route.name`.
 *
 * The locale picker persists to localStorage via setLocale and takes
 * effect immediately because every t() call re-evaluates against the
 * reactive `locale`.
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute } from "vue-router";
import { RefreshCw, Globe, KeyRound } from "lucide-vue-next";
import { t, locale, setLocale, supportedLocales, type LocaleCode } from "@/lib/i18n";
import { useSetupDialog } from "@/stores/setup";

const route = useRoute();
const { open: openSetup } = useSetupDialog();

function refresh() {
  window.location.reload();
}

interface Crumb {
  label: string;
  to?: string;
}

const crumbs = computed<Crumb[]>(() => {
  const fromMeta = (route.meta?.crumbs as Crumb[] | undefined) ?? null;
  if (fromMeta && fromMeta.length > 0) return fromMeta;
  const name = (route.name as string | undefined) ?? "";
  if (!name) return [{ label: t("nav.dashboard") }];
  // Fall back to the matching nav.* i18n key when one exists, otherwise
  // capitalise the route name so we still surface something sensible.
  const navKey = `nav.${name}`;
  const translated = t(navKey);
  if (translated !== navKey) return [{ label: translated }];
  return [{ label: name.charAt(0).toUpperCase() + name.slice(1) }];
});

// Language picker dropdown.
const localeOpen = ref(false);
const pickerEl = ref<HTMLDivElement | null>(null);

function toggleLocale() {
  localeOpen.value = !localeOpen.value;
}

function pickLocale(code: LocaleCode) {
  setLocale(code);
  localeOpen.value = false;
}

function handleClickOutside(evt: MouseEvent) {
  if (!pickerEl.value || !localeOpen.value) return;
  if (!pickerEl.value.contains(evt.target as Node)) localeOpen.value = false;
}

onMounted(() => document.addEventListener("click", handleClickOutside));
onUnmounted(() => document.removeEventListener("click", handleClickOutside));

const localeOptions = computed(() =>
  supportedLocales().map((code) => ({
    code,
    label: t(`locale.${code}`),
    short: code.toUpperCase(),
  })),
);
</script>

<template>
  <header
    class="flex items-center justify-between py-2.5 px-6 border-b border-[var(--color-line)] bg-[var(--color-surface)] text-[13px] h-[52px] shrink-0"
  >
    <div class="flex items-center gap-2 text-[var(--color-fg-2)]">
      <template v-for="(c, i) in crumbs" :key="i">
        <span v-if="i > 0" class="text-[var(--color-fg-muted)] opacity-70">/</span>
        <span :class="i === crumbs.length - 1 ? 'text-[var(--color-fg)] font-medium' : ''">
          {{ c.label }}
        </span>
      </template>
    </div>
    <div class="flex items-center gap-2.5">
      <button
        type="button"
        class="h-[30px] px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] inline-flex items-center gap-1.5 text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)] transition-colors text-[12px] font-medium"
        title="API keys & sample data"
        @click="openSetup"
      >
        <KeyRound class="h-3.5 w-3.5" />
        <span class="hidden md:inline">Setup</span>
      </button>
      <button
        type="button"
        class="w-[30px] h-[30px] border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] inline-flex items-center justify-center text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)] transition-colors"
        :title="t('topbar.refresh')"
        @click="refresh"
      >
        <RefreshCw class="h-3.5 w-3.5" />
      </button>

      <!-- Language picker -->
      <div ref="pickerEl" class="relative">
        <button
          type="button"
          class="h-[30px] px-2 border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] inline-flex items-center gap-1.5 text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)] transition-colors text-[12px] font-medium"
          :title="t('topbar.language')"
          @click.stop="toggleLocale"
        >
          <Globe class="h-3.5 w-3.5" />
          <span class="font-mono uppercase tracking-wider text-[10.5px]">{{ locale.toUpperCase() }}</span>
        </button>
        <div
          v-if="localeOpen"
          class="absolute right-0 top-full mt-1 min-w-[140px] bg-[var(--color-surface)] border border-[var(--color-line)] rounded-md shadow-lg py-1 z-30"
        >
          <button
            v-for="opt in localeOptions"
            :key="opt.code"
            type="button"
            class="w-full text-left px-3 py-1.5 text-[12.5px] flex items-center justify-between gap-3 hover:bg-[var(--color-surface-2)] transition-colors"
            :class="opt.code === locale ? 'text-[var(--color-fg)] font-medium' : 'text-[var(--color-fg-2)]'"
            @click="pickLocale(opt.code)"
          >
            <span>{{ opt.label }}</span>
            <span class="font-mono text-[10px] uppercase tracking-wider text-[var(--color-fg-muted)]">{{ opt.short }}</span>
          </button>
        </div>
      </div>
    </div>
  </header>
</template>
