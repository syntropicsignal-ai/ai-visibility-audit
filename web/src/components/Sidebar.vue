<script setup lang="ts">
/**
 * Sidebar — functional SaaS layout.
 *
 * Square logo + wordmark, then a workspace switcher, nav grouped by
 * purpose (Overview / Data / Workflow), and a footer that surfaces the
 * last-run / next-run status. Each nav item gets a lucide icon + an
 * optional mono counter on the right.
 *
 * Active state is a soft surface fill plus a 3px cobalt rule on the
 * left — quiet but unambiguous.
 */
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { t } from "@/lib/i18n";
import {
  LayoutDashboard,
  MessageSquareText,
  ListChecks,
  History,
  Bookmark,
  Settings as SettingsIcon,
  ChevronDown,
  Network,
  Search,
} from "lucide-vue-next";
import { api, ApiError } from "@/api/client";
import type { Brand, Run } from "@/api/types";
import { timeAgo } from "@/lib/format";

interface NavLink {
  to: string;
  labelKey: Parameters<typeof t>[0];
  icon: typeof LayoutDashboard;
  matchPrefix?: string;
}

interface NavGroup {
  labelKey: Parameters<typeof t>[0];
  links: NavLink[];
}

const groups: NavGroup[] = [
  {
    labelKey: "nav.group.overview",
    links: [
      { to: "/", labelKey: "nav.dashboard", icon: LayoutDashboard },
      { to: "/topics", labelKey: "nav.topics", icon: Network },
      { to: "/search-terms", labelKey: "nav.search_terms", icon: Search },
    ],
  },
  {
    labelKey: "nav.group.data",
    links: [
      { to: "/responses", labelKey: "nav.responses", icon: MessageSquareText },
      { to: "/prompts", labelKey: "nav.prompts", icon: ListChecks, matchPrefix: "/prompts" },
      { to: "/runs", labelKey: "nav.runs", icon: History, matchPrefix: "/runs" },
    ],
  },
  {
    labelKey: "nav.group.workflow",
    links: [
      { to: "/brands", labelKey: "nav.brands", icon: Bookmark },
      { to: "/settings", labelKey: "nav.settings", icon: SettingsIcon },
    ],
  },
];

function isMatch(currentPath: string, link: NavLink): boolean {
  if (link.to === "/") return currentPath === "/";
  if (link.matchPrefix) return currentPath.startsWith(link.matchPrefix);
  return currentPath === link.to;
}

// Workspace info + last-run footer pull from existing endpoints. We
// keep this lightweight — failure here doesn't block navigation, the
// sidebar just falls back to a placeholder.
const selfBrand = ref<Brand | null>(null);
const lastRun = ref<Run | null>(null);

const orgInitials = computed(() =>
  (selfBrand.value?.name ?? "GM")
    .split(/\s+/)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase(),
);

const orgDomain = computed(() => {
  const d = selfBrand.value?.domains?.[0];
  return d ?? "";
});

onMounted(async () => {
  try {
    const [brands, runs] = await Promise.all([api.listBrands(), api.listRuns()]);
    selfBrand.value = brands.find((b) => b.is_self) ?? null;
    // Most recent completed run for the footer "last run" line
    const completed = runs.filter((r) => r.status === "completed");
    lastRun.value = completed[0] ?? runs[0] ?? null;
  } catch (e) {
    if (!(e instanceof ApiError)) throw e;
    // Silent — sidebar isn't blocking, just degrades gracefully
  }
});
</script>

<template>
  <aside
    class="w-[232px] shrink-0 h-screen sticky top-0 flex flex-col bg-[var(--color-surface)] border-r border-[var(--color-line)] px-3 py-[18px] gap-0.5 text-[13px]"
  >
    <!-- Brand -->
    <div class="flex items-center gap-2 px-2.5 pt-1 pb-2 text-[15px] font-semibold tracking-[-0.02em]">
      <span
        class="w-[22px] h-[22px] rounded-md bg-[var(--color-fg)] text-[var(--color-bg)] inline-flex items-center justify-center text-[12px] font-bold"
      >A</span>
      <span>AI Visibility Audit</span>
      <span class="ml-auto text-[10px] font-medium text-[var(--color-fg-muted)] tracking-normal">v0.1</span>
    </div>

    <!-- Workspace switcher -->
    <div
      class="flex items-center gap-2 py-2 px-2.5 border border-[var(--color-line)] rounded-md bg-[var(--color-bg)] mt-1.5 mx-1 mb-3.5 text-[13px] cursor-pointer hover:bg-[var(--color-surface-2)] transition-colors"
    >
      <span
        class="w-[22px] h-[22px] rounded bg-[var(--color-accent-soft)] text-[var(--color-accent)] inline-flex items-center justify-center text-[11px] font-bold"
      >{{ orgInitials }}</span>
      <div class="flex-1 leading-tight min-w-0">
        <p class="font-medium truncate">{{ selfBrand?.name ?? t("nav.workspace") }}</p>
        <p v-if="orgDomain" class="text-[11px] text-[var(--color-fg-muted)] truncate">{{ orgDomain }}</p>
      </div>
      <ChevronDown class="h-3.5 w-3.5 text-[var(--color-fg-muted)] shrink-0" />
    </div>

    <!-- Nav groups -->
    <nav class="flex-1 flex flex-col">
      <div v-for="group in groups" :key="group.labelKey" class="mt-3">
        <p class="cap !text-[11px] !tracking-[0.04em] px-3 py-1 pb-1.5">{{ t(group.labelKey) }}</p>
        <RouterLink
          v-for="link in group.links"
          :key="link.to"
          :to="link.to"
          custom
          v-slot="{ navigate, route }"
        >
          <a
            @click="navigate"
            :class="[
              'relative flex items-center gap-2.5 py-1.5 px-2.5 rounded-md cursor-pointer text-[13px] font-medium transition-colors',
              isMatch(route?.path ?? '/', link)
                ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] before:absolute before:left-[-12px] before:top-[5px] before:w-[3px] before:h-4 before:bg-[var(--color-accent)] before:rounded-r'
                : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)] hover:text-[var(--color-fg)]',
            ]"
          >
            <component :is="link.icon" class="h-[15px] w-[15px] shrink-0 stroke-[1.7]" />
            <span>{{ t(link.labelKey) }}</span>
          </a>
        </RouterLink>
      </div>
    </nav>

    <!-- Footer: run status -->
    <div class="mt-auto pt-3 px-2.5 border-t border-[var(--color-line)] text-[11px] text-[var(--color-fg-muted)] flex flex-col gap-1">
      <div class="flex items-center gap-1.5 text-[var(--color-fg-2)]">
        <span
          :class="[
            'w-1.5 h-1.5 rounded-full inline-block',
            lastRun?.status === 'completed' ? 'bg-[var(--color-success)]'
              : lastRun?.status === 'failed' ? 'bg-[var(--color-danger)]'
              : 'bg-[var(--color-fg-muted)]',
          ]"
        />
        <span v-if="lastRun">{{ t("sidebar.last_run") }} · {{ timeAgo(lastRun.started_at) }}</span>
        <span v-else>{{ t("sidebar.no_runs") }}</span>
      </div>
      <div class="flex items-center justify-between">
        <span class="text-[var(--color-fg-muted)]">{{ t("sidebar.sources_active") }}</span>
        <RouterLink
          to="/settings"
          class="text-[var(--color-accent)] hover:underline"
        >{{ t("sidebar.configure") }}</RouterLink>
      </div>
    </div>
  </aside>
</template>
