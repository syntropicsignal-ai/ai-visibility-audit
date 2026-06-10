<script setup lang="ts">
/**
 * Tabs — underline-style.
 *
 * Used wherever a view has parallel sub-views (intent filters, etc).
 * Underline rather than pill because the rest of the design leans
 * editorial; pills would feel too app-y.
 */
import { computed } from "vue";
import { cn } from "@/lib/utils";

interface TabItem {
  value: string | number | null;
  label: string;
  count?: number | null;
}

const props = defineProps<{
  items: readonly TabItem[];
  class?: string;
}>();

const model = defineModel<string | number | null>();

function isActive(v: string | number | null) {
  return model.value === v;
}
</script>

<template>
  <div
    :class="
      cn(
        'flex gap-5 border-b border-[var(--color-line)]',
        $props.class,
      )
    "
  >
    <button
      v-for="t in items"
      :key="String(t.value)"
      type="button"
      :class="[
        'relative pb-2.5 text-xs font-medium transition-colors focus-ring rounded-t-sm',
        isActive(t.value)
          ? 'text-[var(--color-fg)]'
          : 'text-[var(--color-fg-muted)] hover:text-[var(--color-fg-2)]',
      ]"
      @click="model = t.value"
    >
      <span class="inline-flex items-center gap-1.5">
        {{ t.label }}
        <span
          v-if="t.count != null"
          class="tabular-nums text-[10px] text-[var(--color-fg-muted)]"
        >
          {{ t.count }}
        </span>
      </span>
      <span
        v-if="isActive(t.value)"
        class="absolute -bottom-px left-0 right-0 h-px bg-[var(--color-fg)]"
      />
    </button>
  </div>
</template>
