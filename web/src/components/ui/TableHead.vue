<script setup lang="ts">
import { computed } from "vue";
import { cn } from "@/lib/utils";

const props = defineProps<{
  align?: "left" | "right" | "center";
  class?: string;
  /** Width — applied as the column's min/max so flex layout is stable */
  width?: string;
}>();

const klass = computed(() =>
  cn(
    "label-eyebrow px-3 py-2.5 align-middle font-semibold",
    props.align === "right"
      ? "text-right"
      : props.align === "center"
      ? "text-center"
      : "text-left",
    props.class,
  ),
);

const styleAttr = computed(() =>
  props.width ? { width: props.width, minWidth: props.width } : undefined,
);
</script>

<template>
  <th :class="klass" :style="styleAttr">
    <slot />
  </th>
</template>
