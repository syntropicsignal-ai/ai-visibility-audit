<script setup lang="ts">
import { cn } from "@/lib/utils";
defineProps<{
  class?: string;
  hoverable?: boolean;
}>();
</script>

<template>
  <tr
    :class="
      cn(
        'transition-colors',
        hoverable ? 'hover:bg-[var(--color-surface-2)]/40 cursor-pointer' : '',
        $props.class,
      )
    "
  >
    <slot />
  </tr>
</template>
