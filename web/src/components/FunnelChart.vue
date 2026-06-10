<script setup lang="ts">
/**
 * GEO Funnel — 5-stage horizontal bar chart.
 *
 * Each row: name + sub-label, a proportional rounded bar with the raw
 * count inside, and the rate + drop label on the right. The biggest
 * negative drop is tinted amber/red on the bar so the chart calls out
 * the leak without a separate annotation layer.
 *
 * Stages are normalised against the max stage rate so the visual peaks
 * at 100% width — keeps the funnel from looking flat when discovery is
 * naturally a small fraction.
 */
import { computed } from "vue";
import { pct } from "@/lib/format";

interface Stage {
  label: string; // human label e.g. "Discovery"
  tag: string;   // sub-label e.g. "AI searched our domain"
  count: number;
  rate: number;  // 0..1
}

const props = defineProps<{
  stages: Stage[];
}>();

interface RenderedStage extends Stage {
  drop: number | null;
  isLeak: boolean;
}

const rendered = computed<RenderedStage[]>(() => {
  let leakIdx = -1;
  let leakValue = 0;
  for (let i = 1; i < props.stages.length; i++) {
    const prev = props.stages[i - 1].rate;
    const curr = props.stages[i].rate;
    if (prev <= 0) continue;
    const change = (curr - prev) / prev;
    if (change < leakValue) {
      leakValue = change;
      leakIdx = i;
    }
  }
  return props.stages.map((s, i) => {
    const prev = i > 0 ? props.stages[i - 1].rate : null;
    const drop = prev !== null && prev > 0 ? (s.rate - prev) / prev : null;
    return { ...s, drop, isLeak: i === leakIdx };
  });
});

const maxRate = computed(() => Math.max(0.01, ...props.stages.map((s) => s.rate)));

function fillWidth(rate: number): string {
  if (maxRate.value === 0) return "0%";
  return `${Math.max(2, (rate / maxRate.value) * 100)}%`;
}

function dropLabel(d: number | null): string {
  if (d === null) return "";
  const sign = d > 0 ? "+" : "−";
  return `${sign}${Math.round(Math.abs(d) * 100)}% from prev`;
}
</script>

<template>
  <div class="py-1">
    <div
      v-for="(s, i) in rendered"
      :key="s.label"
      class="grid items-center gap-3.5 py-2 border-b border-[var(--color-line-soft)] last:border-b-0"
      style="grid-template-columns: 150px 1fr 110px"
    >
      <div class="text-[12px]">
        <p class="font-semibold text-[var(--color-fg)]">{{ s.label }}</p>
        <p class="text-[11px] text-[var(--color-fg-muted)] leading-tight">{{ s.tag }}</p>
      </div>
      <div class="h-[22px] bg-[var(--color-surface-2)] rounded overflow-hidden">
        <div
          class="h-full flex items-center pl-2 font-mono text-[11px] font-medium text-white"
          :style="{
            width: fillWidth(s.rate),
            background: s.isLeak ? 'var(--color-warning)' : 'var(--color-accent)',
          }"
        >{{ s.count }}</div>
      </div>
      <div class="text-right flex flex-col gap-px">
        <span class="font-mono text-[14px] font-semibold text-[var(--color-fg)]">{{ pct(s.rate, 0) }}</span>
        <span
          v-if="s.drop !== null"
          class="font-mono text-[11px]"
          :class="s.drop > 0 ? 'text-[var(--color-success)]' : 'text-[var(--color-fg-muted)]'"
        >{{ dropLabel(s.drop) }}</span>
      </div>
    </div>
  </div>
</template>
