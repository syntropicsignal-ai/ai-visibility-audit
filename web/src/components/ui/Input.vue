<script setup lang="ts">
/**
 * Text input.
 *
 * Single source of truth for the inline text-field aesthetic — used
 * everywhere from search bars to brand-domain editors. No labels here;
 * pair with a Label primitive (or just a <label> element) when the
 * consumer needs one.
 *
 * v-model passthrough via defineModel(). Forwards attrs so type/min/max/
 * placeholder/aria all work without explicit props.
 */
import { computed } from "vue";
import { cn } from "@/lib/utils";

const model = defineModel<string | number | undefined>();

const props = defineProps<{
  size?: "sm" | "md";
  invalid?: boolean;
  class?: string;
}>();

const klass = computed(() =>
  cn(
    "w-full bg-[var(--color-surface)] text-[var(--color-fg)] " +
      "border border-[var(--color-line)] " +
      "rounded-[var(--radius-sm)] focus-ring " +
      "placeholder:text-[var(--color-fg-muted)] " +
      "transition-colors hover:border-[var(--color-line-strong)] " +
      "focus:border-[var(--color-accent)] " +
      "disabled:opacity-50 disabled:cursor-not-allowed",
    props.size === "sm" ? "h-7 px-2 text-xs" : "h-9 px-3 text-sm",
    props.invalid
      ? "border-[var(--color-danger)] focus:border-[var(--color-danger)]"
      : "",
    props.class,
  ),
);
</script>

<template>
  <input v-model="model" :class="klass" />
</template>
