<script setup lang="ts">
/**
 * Textarea — visually consistent with Input but supports multi-line content.
 * Auto-grows to fit content via the field-sizing CSS property; falls back
 * to a fixed `rows` count on browsers that don't support it.
 */
import { computed } from "vue";
import { cn } from "@/lib/utils";

const model = defineModel<string | undefined>();

const props = defineProps<{
  rows?: number;
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
      "px-3 py-2 text-sm leading-relaxed " +
      "resize-y [field-sizing:content]",
    props.invalid
      ? "border-[var(--color-danger)] focus:border-[var(--color-danger)]"
      : "",
    props.class,
  ),
);
</script>

<template>
  <textarea v-model="model" :rows="rows ?? 3" :class="klass" />
</template>
