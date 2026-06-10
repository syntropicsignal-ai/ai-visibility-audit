<script setup lang="ts">
/**
 * Donut chart — small SVG, used in the Sentiment card.
 *
 * Segments are drawn as stroked arcs around a single circle using
 * stroke-dasharray + dashoffset (stable trick that avoids any need for
 * SVG path math). The center label is optional and rendered in Inter
 * to match the rest of the dashboard.
 */
import { computed } from "vue";

interface Segment {
  value: number;
  color: string;
}

const props = withDefaults(
  defineProps<{
    segments: Segment[];
    size?: number;
    thickness?: number;
    centerValue?: string;
    centerLabel?: string;
  }>(),
  {
    size: 120,
    thickness: 16,
  },
);

const total = computed(() => props.segments.reduce((s, x) => s + x.value, 0));

interface RenderedSeg {
  color: string;
  dasharray: string;
  dashoffset: number;
}

const rendered = computed<RenderedSeg[]>(() => {
  const r = props.size / 2 - props.thickness / 2;
  const C = 2 * Math.PI * r;
  let acc = 0;
  return props.segments.map((s) => {
    const frac = total.value > 0 ? s.value / total.value : 0;
    const dasharray = `${C * frac} ${C}`;
    const dashoffset = -C * acc;
    acc += frac;
    return { color: s.color, dasharray, dashoffset };
  });
});

const radius = computed(() => props.size / 2 - props.thickness / 2);
</script>

<template>
  <svg :width="size" :height="size" :viewBox="`0 0 ${size} ${size}`">
    <circle
      :cx="size / 2"
      :cy="size / 2"
      :r="radius"
      fill="none"
      stroke="var(--color-surface-3)"
      :stroke-width="thickness"
    />
    <circle
      v-for="(seg, i) in rendered"
      :key="i"
      :cx="size / 2"
      :cy="size / 2"
      :r="radius"
      fill="none"
      :stroke="seg.color"
      :stroke-width="thickness"
      :stroke-dasharray="seg.dasharray"
      :stroke-dashoffset="seg.dashoffset"
      :transform="`rotate(-90 ${size / 2} ${size / 2})`"
      stroke-linecap="butt"
    />
    <text
      v-if="centerValue"
      :x="size / 2"
      :y="size / 2 - 2"
      text-anchor="middle"
      font-size="20"
      font-weight="600"
      fill="var(--color-fg)"
      style="letter-spacing: -0.02em; font-family: var(--font-sans);"
    >{{ centerValue }}</text>
    <text
      v-if="centerLabel"
      :x="size / 2"
      :y="size / 2 + 14"
      text-anchor="middle"
      font-size="10"
      fill="var(--color-fg-muted)"
      style="font-family: var(--font-sans);"
    >{{ centerLabel }}</text>
  </svg>
</template>
