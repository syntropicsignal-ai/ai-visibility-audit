<script setup lang="ts">
/**
 * Button primitive.
 *
 * Five variants:
 *   - `primary`   solid petrol, used for one main action per view
 *   - `secondary` outlined neutral, the default
 *   - `ghost`     no chrome, hover only — for inline / toolbar actions
 *   - `subtle`    tinted accent, soft backgrounds — for secondary CTAs
 *   - `danger`    destructive actions
 *
 * Three sizes: sm / md (default) / lg. `icon` is a square variant for
 * icon-only buttons (always pair with `aria-label`).
 *
 * Note: `as` lets the consumer render this as <RouterLink> while keeping
 * the visual treatment. Slot content is wrapped so leading/trailing icons
 * align properly without per-call layout fixes.
 */
import { computed } from "vue";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  // Base — alignment, font, focus ring, disabled state
  "inline-flex items-center justify-center gap-2 font-medium tracking-tight whitespace-nowrap " +
    "transition-colors focus-ring " +
    "disabled:opacity-50 disabled:pointer-events-none",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--color-accent)] text-[var(--color-accent-fg)] " +
          "hover:bg-[var(--color-accent-hover)] active:bg-[var(--color-accent-active)]",
        secondary:
          "bg-[var(--color-surface)] text-[var(--color-fg)] " +
          "border border-[var(--color-line)] " +
          "hover:bg-[var(--color-surface-2)] hover:border-[var(--color-line-strong)]",
        ghost:
          "bg-transparent text-[var(--color-fg-2)] " +
          "hover:bg-[var(--color-surface-2)] hover:text-[var(--color-fg)]",
        subtle:
          "bg-[var(--color-accent-soft)] text-[var(--color-accent)] " +
          "hover:bg-[color-mix(in_srgb,var(--color-accent-soft),var(--color-accent)_8%)]",
        danger:
          "bg-[var(--color-danger)] text-white " +
          "hover:bg-[color-mix(in_srgb,var(--color-danger),black_10%)]",
      },
      size: {
        sm: "text-xs h-7 px-2.5 rounded-[var(--radius-sm)]",
        md: "text-sm h-9 px-3.5 rounded-[var(--radius-md)]",
        lg: "text-sm h-10 px-5 rounded-[var(--radius-md)]",
        icon: "h-9 w-9 rounded-[var(--radius-md)]",
      },
    },
    defaultVariants: {
      variant: "secondary",
      size: "md",
    },
  },
);

type Variant = VariantProps<typeof buttonVariants>["variant"];
type Size = VariantProps<typeof buttonVariants>["size"];

const props = withDefaults(
  defineProps<{
    variant?: Variant;
    size?: Size;
    type?: "button" | "submit" | "reset";
    disabled?: boolean;
    class?: string;
  }>(),
  {
    type: "button",
  },
);

const klass = computed(() =>
  cn(buttonVariants({ variant: props.variant, size: props.size }), props.class),
);
</script>

<template>
  <button :type="type" :disabled="disabled" :class="klass">
    <slot />
  </button>
</template>
