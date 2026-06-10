<script setup lang="ts">
/**
 * Card header — title + optional subtitle + optional trailing actions slot.
 *
 * Used as the top section of a Card. Title is rendered in the display
 * serif at a controlled size (no h-tag bumping) so cards across the
 * dashboard share a consistent header rhythm.
 */
import { cn } from "@/lib/utils";

defineProps<{
  title: string;
  subtitle?: string;
  /** Stack title/subtitle to the left of the actions slot when true. */
  inline?: boolean;
  class?: string;
}>();
</script>

<template>
  <header
    :class="
      cn(
        'flex items-start justify-between gap-3 mb-4',
        inline ? 'items-center' : '',
        $props.class,
      )
    "
  >
    <div class="min-w-0">
      <h3 class="font-display text-[1.0625rem] font-medium leading-tight tracking-tight">
        {{ title }}
      </h3>
      <p
        v-if="subtitle"
        class="text-[13.5px] text-[var(--color-fg-2)] mt-1 leading-snug"
      >
        {{ subtitle }}
      </p>
    </div>
    <div v-if="$slots.actions" class="shrink-0 flex items-center gap-1.5">
      <slot name="actions" />
    </div>
  </header>
</template>
