<script setup lang="ts">
/**
 * Card surface.
 *
 * Default: white surface, 1px warm border, md radius. No shadow — the
 * border + warm-paper page background gives enough separation, and
 * unshadowed cards read as more editorial than the standard floaty SaaS
 * card stack.
 *
 * Padding lives on the card itself rather than being delegated to slots
 * because nearly every consumer wants the same padding. Override via
 * `class` when needed (e.g. tables that fill edge-to-edge).
 *
 * Header / Title / Content slots are intentionally minimal — most usage
 * just needs the surface and types its own h2/p directly.
 */
import { computed } from "vue";
import { cn } from "@/lib/utils";

const props = defineProps<{
  /** Removes the inner padding so the consumer can lay out edge-to-edge. */
  flush?: boolean;
  /** Tighter padding for compact contexts (sidebars, popovers). */
  compact?: boolean;
  class?: string;
}>();

const klass = computed(() =>
  cn(
    "bg-[var(--color-surface)] border border-[var(--color-line)] rounded-[var(--radius-md)]",
    props.flush ? "" : props.compact ? "p-4" : "p-5",
    props.class,
  ),
);
</script>

<template>
  <section :class="klass">
    <slot />
  </section>
</template>
