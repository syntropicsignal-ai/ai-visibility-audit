<script setup lang="ts">
import { cn } from "@/lib/utils";
defineProps<{ class?: string }>();
</script>

<template>
  <tbody
    :class="
      cn(
        '[&_tr:not(:last-child)]:border-b [&_tr]:border-[var(--color-line)]',
        $props.class,
      )
    "
  >
    <slot />
  </tbody>
</template>
