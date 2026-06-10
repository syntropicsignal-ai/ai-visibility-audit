<script setup lang="ts">
/**
 * Tiny SVG sparkline.
 *
 * SVG instead of Chart.js because the use case is "a 28-pixel line on
 * top of a KPI tile" — Chart.js is overkill, and SVG keeps the markup
 * lightweight enough to be repeated inside a leaderboard table without
 * any perf concern.
 *
 * The optional area fill is drawn under the line in 12% of the line
 * color, matching the editorial / sparse aesthetic of the dashboard.
 */
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    data: number[];
    width?: number;
    height?: number;
    color?: string;
    area?: boolean;
    strokeWidth?: number;
  }>(),
  {
    width: 180,
    height: 28,
    color: "var(--color-fg)",
    area: false,
    strokeWidth: 1.5,
  },
);

const path = computed(() => {
  const d = props.data;
  if (d.length === 0) return { line: "", area: "" };
  const min = Math.min(...d);
  const max = Math.max(...d);
  const range = max - min || 1;
  const w = props.width;
  const h = props.height;
  const padY = 2;
  const innerH = h - padY * 2;
  const stepX = d.length > 1 ? w / (d.length - 1) : 0;

  const points = d.map((v, i) => {
    const x = i * stepX;
    const y = padY + (1 - (v - min) / range) * innerH;
    return [x, y] as const;
  });

  const line = points
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`)
    .join(" ");

  const area = `${line} L${w.toFixed(2)},${h.toFixed(2)} L0,${h.toFixed(2)} Z`;

  return { line, area };
});
</script>

<template>
  <svg
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    preserveAspectRatio="none"
    class="block"
  >
    <path
      v-if="area"
      :d="path.area"
      :fill="color"
      fill-opacity="0.12"
      stroke="none"
    />
    <path :d="path.line" fill="none" :stroke="color" :stroke-width="strokeWidth" stroke-linejoin="round" stroke-linecap="round" />
  </svg>
</template>
