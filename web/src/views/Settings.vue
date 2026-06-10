<script setup lang="ts">
/**
 * Settings page — sources status + run schedule.
 *
 * Sources panel: read-only credentials check. Predefined in code,
 * each runs iff its credentials are present in the API's environment.
 *
 * Schedule panel: toggle automated runs + interval. The
 * scheduler loop in api/app/services/scheduler.py picks this up
 * within 60s of any change.
 */
import { computed, onMounted, ref } from "vue";
import { Loader2, CheckCircle2, AlertCircle, Clock, Save } from "lucide-vue-next";
import { Card, Badge, Switch } from "@/components/ui";
import { api, ApiError } from "@/api/client";
import type { RunSchedule, SourceStatus } from "@/api/types";
import { timeAgo } from "@/lib/format";
import { t, locale, setLocale, type LocaleCode } from "@/lib/i18n";
import { useToasts } from "@/stores/toasts";

const toasts = useToasts();

const sources = ref<SourceStatus[]>([]);
const loading = ref(true);

const schedule = ref<RunSchedule | null>(null);
const scheduleLoading = ref(true);
const scheduleSaving = ref(false);
const scheduleEnabled = ref(false);
const scheduleIntervalHours = ref(168);

const intervalPresets = [
  { label: "Daily", value: 24 },
  { label: "Every 2 days", value: 48 },
  { label: "Weekly", value: 168 },
  { label: "Bi-weekly", value: 336 },
  { label: "Monthly", value: 720 },
];

async function load() {
  loading.value = true;
  scheduleLoading.value = true;
  try {
    const [srcs, sched] = await Promise.all([api.listSources(), loadSchedule()]);
    sources.value = srcs;
    if (sched) {
      schedule.value = sched;
      scheduleEnabled.value = sched.enabled;
      scheduleIntervalHours.value = sched.interval_hours;
    }
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to load settings");
  } finally {
    loading.value = false;
    scheduleLoading.value = false;
  }
}

async function loadSchedule(): Promise<RunSchedule | null> {
  try {
    return await api.getSchedule();
  } catch (e) {
    if (e instanceof ApiError && e.status === 400) {
      // No self-brand configured — surface this gracefully, not as an error toast
      return null;
    }
    throw e;
  }
}

async function saveSchedule() {
  scheduleSaving.value = true;
  try {
    const updated = await api.updateSchedule({
      enabled: scheduleEnabled.value,
      interval_hours: scheduleIntervalHours.value,
    });
    schedule.value = updated;
    toasts.success("Schedule updated");
  } catch (e) {
    toasts.error(e instanceof ApiError ? (e.detail ?? e.message) : "Failed to save");
  } finally {
    scheduleSaving.value = false;
  }
}

const configuredCount = computed(() => sources.value.filter((s) => s.configured).length);

const dirty = computed(() => {
  if (!schedule.value) return false;
  return (
    scheduleEnabled.value !== schedule.value.enabled ||
    scheduleIntervalHours.value !== schedule.value.interval_hours
  );
});

const intervalLabel = computed(() => {
  const h = scheduleIntervalHours.value;
  if (h % 24 === 0) {
    const d = h / 24;
    return d === 1 ? "every day" : `every ${d} days`;
  }
  return `every ${h} hours`;
});

onMounted(load);
</script>

<template>
  <!-- Page head -->
  <div class="flex items-start justify-between gap-6 mb-[18px]">
    <div>
      <h1 class="text-[22px] font-semibold tracking-[-0.02em] m-0 text-[var(--color-fg)]">{{ t("settings.title") }}</h1>
      <p class="dek mt-1">{{ t("settings.dek") }}</p>
    </div>
  </div>

  <!-- Locale picker -->
  <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden mb-3">
    <header class="py-3.5 px-4 pb-2.5">
      <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("settings.locale.title") }}</p>
      <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("settings.locale.dek") }}</p>
    </header>
    <div class="border-t border-[var(--color-line-soft)] py-3 px-4">
      <div class="inline-flex items-center border border-[var(--color-line)] rounded-md bg-[var(--color-surface)] text-[13px] overflow-hidden">
        <button
          v-for="code in (['en', 'pl'] as const)"
          :key="code"
          type="button"
          @click="setLocale(code)"
          :class="[
            'py-[6px] px-3 transition-colors border-r border-[var(--color-line)] last:border-r-0',
            locale === code
              ? 'bg-[var(--color-surface-2)] text-[var(--color-fg)] font-medium'
              : 'text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
          ]"
        >{{ t(`locale.${code}` as `locale.${LocaleCode}`) }}</button>
      </div>
    </div>
  </section>

  <!-- Schedule panel -->
  <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden mb-3">
    <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
      <div>
        <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("settings.schedule.title") }}</p>
        <p class="text-[12px] text-[var(--color-fg-muted)]">{{ t("settings.schedule.dek") }}</p>
      </div>
      <span
        class="inline-flex items-center gap-1.5 py-0.5 px-2 rounded text-[11px] font-medium"
        :class="
          schedule?.enabled
            ? 'bg-[var(--color-success-soft)] text-[var(--color-success)]'
            : 'bg-[var(--color-surface-2)] text-[var(--color-fg-muted)]'
        "
      >
        <span
          class="w-1.5 h-1.5 rounded-full"
          :style="{ background: schedule?.enabled ? 'var(--color-success)' : 'var(--color-fg-muted)' }"
        />
        {{ schedule?.enabled ? "Active" : "Off" }}
      </span>
    </header>

    <div v-if="scheduleLoading" class="flex justify-center py-8">
      <Loader2 class="h-4 w-4 animate-spin text-[var(--color-fg-muted)]" />
    </div>

    <div
      v-else-if="!schedule"
      class="text-[13px] text-[var(--color-fg-muted)] py-4 px-4 border-t border-[var(--color-line-soft)]"
    >
      No self-brand configured — go to <a href="/brands" class="text-[var(--color-accent)] hover:underline">Brands</a> and mark a brand as <em>your brand</em> to enable scheduled runs.
    </div>

    <div v-else class="border-t border-[var(--color-line-soft)]">
      <!-- Enable toggle row -->
      <div class="flex items-center gap-3 py-3 px-4 border-b border-[var(--color-line-soft)]">
        <Clock class="h-4 w-4 text-[var(--color-fg-muted)]" />
        <div class="flex-1">
          <p class="text-[13px] font-medium">Run automatically</p>
          <p class="text-[11.5px] text-[var(--color-fg-muted)]">
            <template v-if="scheduleEnabled">
              Trigger a benchmark {{ intervalLabel }}.
              <span v-if="schedule.last_triggered_at" class="ml-1">
                · Last run {{ timeAgo(schedule.last_triggered_at) }}.
              </span>
              <span v-else class="ml-1">· No runs triggered yet.</span>
            </template>
            <template v-else>
              Manual triggers only. Toggle on to start automatic monitoring.
            </template>
          </p>
        </div>
        <Switch v-model="scheduleEnabled" />
      </div>

      <!-- Interval picker -->
      <div class="py-3 px-4 border-b border-[var(--color-line-soft)]" v-if="scheduleEnabled">
        <p class="text-[13px] font-medium mb-2">Cadence</p>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="p in intervalPresets"
            :key="p.value"
            type="button"
            @click="scheduleIntervalHours = p.value"
            :class="[
              'border rounded-md py-[5px] px-2.5 text-[12px] font-medium cursor-pointer transition-colors',
              scheduleIntervalHours === p.value
                ? 'bg-[var(--color-fg)] text-[var(--color-bg)] border-[var(--color-fg)]'
                : 'border-[var(--color-line)] bg-[var(--color-surface)] text-[var(--color-fg-2)] hover:bg-[var(--color-surface-2)]',
            ]"
          >{{ p.label }}</button>
        </div>
      </div>

      <!-- Save row -->
      <div class="flex items-center justify-between py-3 px-4">
        <p class="text-[11.5px] text-[var(--color-fg-muted)]">
          <template v-if="schedule.next_run_at && scheduleEnabled && !dirty">
            Next run · {{ timeAgo(schedule.next_run_at) }}
          </template>
          <template v-else-if="dirty">
            <span class="text-[var(--color-warning)]">Unsaved changes</span>
          </template>
        </p>
        <button
          type="button"
          :disabled="!dirty || scheduleSaving"
          @click="saveSchedule"
          class="inline-flex items-center gap-1.5 py-[5px] px-2.5 border border-[var(--color-fg)] rounded-md bg-[var(--color-fg)] text-white text-[12px] font-medium hover:bg-[var(--color-fg-2)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Loader2 v-if="scheduleSaving" class="h-3 w-3 animate-spin" />
          <Save v-else class="h-3 w-3" />
          Save schedule
        </button>
      </div>
    </div>
  </section>

  <!-- Sources panel -->
  <section class="bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden">
    <header class="flex items-center justify-between py-3.5 px-4 pb-2.5">
      <div>
        <p class="text-[14px] font-semibold tracking-[-0.01em]">{{ t("settings.sources.title") }}</p>
        <p class="text-[12px] text-[var(--color-fg-muted)]">
          Credentials check · {{ configuredCount }}/{{ sources.length }} configured
        </p>
      </div>
    </header>

    <div v-if="loading" class="flex justify-center py-10">
      <Loader2 class="h-4 w-4 animate-spin text-[var(--color-fg-muted)]" />
    </div>

    <Card v-else flush class="!border-0 !rounded-none">
      <ul>
        <li
          v-for="(s, i) in sources"
          :key="s.id"
          :class="[
            'flex items-center gap-4 px-5 py-4',
            i > 0 ? 'border-t border-[var(--color-line-soft)]' : 'border-t border-[var(--color-line)]',
          ]"
        >
          <div
            :class="[
              'shrink-0 h-9 w-9 rounded-md flex items-center justify-center',
              s.configured
                ? 'bg-[var(--color-success-soft)] text-[var(--color-success)]'
                : 'bg-[var(--color-warning-soft)] text-[var(--color-warning)]',
            ]"
          >
            <CheckCircle2 v-if="s.configured" class="h-4 w-4" />
            <AlertCircle v-else class="h-4 w-4" />
          </div>

          <div class="flex-1 min-w-0">
            <div class="flex items-baseline gap-2 flex-wrap">
              <span class="font-medium text-[var(--color-fg)] text-[14px]">{{ s.display_name }}</span>
              <code class="font-mono text-xs text-[var(--color-fg-muted)]">{{ s.id }}</code>
            </div>
            <p class="text-xs text-[var(--color-fg-2)] mt-1 leading-snug">
              <template v-if="s.configured">Active. Runs on every benchmark.</template>
              <template v-else>
                Set
                <code class="font-mono text-xs text-[var(--color-fg)] bg-[var(--color-surface-2)] px-1 py-px rounded">{{ s.credential_hint }}</code>
                in the API's <code class="font-mono text-xs">.env</code> to enable.
              </template>
            </p>
          </div>

          <Badge :tone="s.configured ? 'success' : 'warning'">
            {{ s.configured ? "Active" : "Not configured" }}
          </Badge>
        </li>
      </ul>
    </Card>
  </section>
</template>
