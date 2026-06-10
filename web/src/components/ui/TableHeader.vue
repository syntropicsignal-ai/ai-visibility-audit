<script setup lang="ts">
import { cn } from "@/lib/utils";
defineProps<{ class?: string }>();
</script>

<template>
  <thead :class="cn('bg-[var(--color-surface-2)]/50', $props.class)">
    <slot />
  </thead>
</template>
