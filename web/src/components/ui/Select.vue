<script setup lang="ts">
/**
 * Select — native <select> styled to match Input.
 *
 * For most dashboard filters a native select is the right call: it's
 * accessible by default, mobile-friendly, and doesn't need JS for the
 * common case. Where we need a richer combobox (search, multi-select)
 * we'll wrap radix-vue's Combobox in a separate component.
 */
import { computed } from "vue";
import { cn } from "@/lib/utils";

interface Option {
  label: string;
  value: string | number | null;
}

const props = defineProps<{
  options: readonly Option[];
  size?: "sm" | "md";
  class?: string;
  placeholder?: string;
}>();

const model = defineModel<string | number | null>();

// Native <select> compares values as strings. We coerce on input/output
// so callers can keep numeric / null model values without surprise.
function onChange(e: Event) {
  const raw = (e.target as HTMLSelectElement).value;
  const opt = props.options.find((o) => String(o.value) === raw);
  model.value = opt ? opt.value : null;
}

const klass = computed(() =>
  cn(
    "w-full bg-[var(--color-surface)] text-[var(--color-fg)] " +
      "border border-[var(--color-line)] " +
      "rounded-[var(--radius-sm)] focus-ring " +
      "transition-colors hover:border-[var(--color-line-strong)] " +
      "focus:border-[var(--color-accent)] " +
      "appearance-none pr-7 cursor-pointer " +
      // Inline chevron via SVG background — keeps it dependency-free
      "bg-[length:14px_14px] bg-[right_0.5rem_center] bg-no-repeat " +
      "bg-[url('data:image/svg+xml;utf8,<svg%20xmlns=%22http://www.w3.org/2000/svg%22%20viewBox=%220%200%2024%2024%22%20fill=%22none%22%20stroke=%22%238B8E94%22%20stroke-width=%221.5%22%20stroke-linecap=%22round%22%20stroke-linejoin=%22round%22><polyline%20points=%226%209%2012%2015%2018%209%22/></svg>')]",
    props.size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm",
    props.class,
  ),
);
</script>

<template>
  <select :class="klass" @change="onChange">
    <option v-if="placeholder && model == null" value="" disabled selected>
      {{ placeholder }}
    </option>
    <option
      v-for="opt in options"
      :key="String(opt.value)"
      :value="opt.value === null ? '' : String(opt.value)"
      :selected="opt.value === model"
    >
      {{ opt.label }}
    </option>
  </select>
</template>
