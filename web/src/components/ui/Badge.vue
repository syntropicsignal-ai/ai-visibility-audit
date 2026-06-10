<script setup lang="ts">
/**
 * Badge — a soft pill for metadata.
 *
 * Six tones: neutral / accent / success / warning / danger / info. All
 * use a tinted background paired with a darker foreground from the same
 * hue. Borderless (the tint reads enough on the warm page background).
 *
 * For status indicators that need a leading dot (e.g. run status
 * "Running"), pass `dot` to render a 6px circle in the foreground color.
 */
import { computed } from "vue";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-[var(--radius-xs)] " +
    "text-[11.5px] font-medium tracking-tight leading-none " +
    "px-1.5 py-1 whitespace-nowrap font-variant-numeric:tabular-nums",
  {
    variants: {
      tone: {
        neutral:
          "bg-[var(--color-surface-2)] text-[var(--color-fg-2)]",
        accent:
          "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
        success:
          "bg-[var(--color-success-soft)] text-[var(--color-success)]",
        warning:
          "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
        danger:
          "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
        info:
          "bg-[var(--color-info-soft)] text-[var(--color-info)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

type Tone = VariantProps<typeof badgeVariants>["tone"];

const props = defineProps<{
  tone?: Tone;
  dot?: boolean;
  /** Set true to make the dot pulse (for "running" / live states) */
  pulse?: boolean;
  class?: string;
}>();

const klass = computed(() =>
  cn(badgeVariants({ tone: props.tone }), props.class),
);
</script>

<template>
  <span :class="klass">
    <span
      v-if="dot"
      :class="[
        'h-1.5 w-1.5 rounded-full bg-current',
        pulse ? 'animate-pulse' : '',
      ]"
    />
    <slot />
  </span>
</template>
