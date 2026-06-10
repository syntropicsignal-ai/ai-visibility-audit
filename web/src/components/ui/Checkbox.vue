<script setup lang="ts">
/**
 * Checkbox — radix-vue Checkbox with our chrome.
 *
 * Used by the multi-select query list in the prompt generator (where a
 * Switch would be the wrong affordance — switches mean on/off settings,
 * checkboxes mean inclusion in a set).
 */
import { computed } from "vue";
import { CheckboxRoot, CheckboxIndicator } from "radix-vue";
import { Check } from "lucide-vue-next";
import { cn } from "@/lib/utils";

const model = defineModel<boolean>();

const props = defineProps<{
  disabled?: boolean;
  class?: string;
}>();

const klass = computed(() =>
  cn(
    "peer h-4 w-4 shrink-0 rounded-[3px] border border-[var(--color-line-strong)] " +
      "bg-[var(--color-surface)] focus-ring transition-colors " +
      "data-[state=checked]:bg-[var(--color-accent)] data-[state=checked]:border-[var(--color-accent)]",
    props.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
    props.class,
  ),
);
</script>

<template>
  <CheckboxRoot v-model:checked="model" :disabled="disabled" :class="klass">
    <CheckboxIndicator class="flex items-center justify-center text-white">
      <Check class="h-3 w-3 stroke-[3]" />
    </CheckboxIndicator>
  </CheckboxRoot>
</template>
