<script setup lang="ts">
/**
 * Status pill for run lifecycle.
 *
 * Wraps the Badge primitive with a status-keyed tone + dot. Running
 * status pulses gently to give an at-a-glance "live" indicator without
 * the loudness of an animated icon.
 */
import { computed } from "vue";
import { Badge } from "@/components/ui";

type RunStatus = "completed" | "failed" | "running" | "pending" | string;

const props = defineProps<{
  status: RunStatus;
  /** Hide the label text — render the colored dot only. */
  dotOnly?: boolean;
}>();

const tone = computed(() => {
  switch (props.status) {
    case "completed":
      return "success" as const;
    case "failed":
      return "danger" as const;
    case "running":
      return "info" as const;
    default:
      return "neutral" as const;
  }
});

const isRunning = computed(() => props.status === "running");
</script>

<template>
  <Badge :tone="tone" dot :pulse="isRunning">
    <span v-if="!dotOnly" class="lowercase">{{ status }}</span>
  </Badge>
</template>
