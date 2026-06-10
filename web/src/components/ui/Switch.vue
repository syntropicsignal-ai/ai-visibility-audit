<script setup lang="ts">
/**
 * Switch (toggle).
 *
 * Built on radix-vue's SwitchRoot/SwitchThumb so we get keyboard handling
 * and aria-checked / aria-disabled for free.
 */
import { computed } from "vue";
import { SwitchRoot, SwitchThumb } from "radix-vue";
import { cn } from "@/lib/utils";

const model = defineModel<boolean>();

const props = defineProps<{
  disabled?: boolean;
  class?: string;
}>();

const rootClass = computed(() =>
  cn(
    "inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus-ring",
    "data-[state=checked]:bg-[var(--color-accent)] data-[state=unchecked]:bg-[var(--color-surface-3)]",
    props.disabled ? "opacity-50 cursor-not-allowed" : "cursor-pointer",
    props.class,
  ),
);
</script>

<template>
  <SwitchRoot
    v-model:checked="model"
    :disabled="disabled"
    :class="rootClass"
  >
    <SwitchThumb
      class="pointer-events-none block h-4 w-4 rounded-full bg-white shadow-sm ring-0 transition-transform translate-x-0.5 data-[state=checked]:translate-x-[18px]"
    />
  </SwitchRoot>
</template>
