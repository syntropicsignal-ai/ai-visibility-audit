<script setup lang="ts">
import { computed } from "vue";
import { cn } from "@/lib/utils";

const props = defineProps<{
  align?: "left" | "right" | "center";
  class?: string;
  /** Use mono font (for ids, hashes, code-y values). */
  mono?: boolean;
  /** Use display serif (for big tabular numbers). */
  display?: boolean;
}>();

const klass = computed(() =>
  cn(
    "px-3 py-2.5 align-middle text-sm",
    props.align === "right"
      ? "text-right"
      : props.align === "center"
      ? "text-center"
      : "text-left",
    props.mono ? "font-mono text-[12.5px]" : "",
    props.display ? "font-display tracking-tight" : "",
    props.class,
  ),
);
</script>

<template>
  <td :class="klass">
    <slot />
  </td>
</template>
