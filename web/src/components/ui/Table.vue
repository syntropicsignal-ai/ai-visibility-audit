<script setup lang="ts">
/**
 * Table primitives.
 *
 * Replaces PrimeVue's DataTable. We don't need sorting / virtualization /
 * filtering wired in here — every consumer does its own data shaping.
 * What we DO need is a coherent visual treatment: thin lines, generous
 * cell padding, tabular numbers, eyebrow-style header text. That's what
 * these primitives enforce.
 *
 * Composition:
 *   <Table>
 *     <TableHeader>
 *       <TableRow>
 *         <TableHead>Source</TableHead>
 *         <TableHead align="right">Visibility</TableHead>
 *       </TableRow>
 *     </TableHeader>
 *     <TableBody>
 *       <TableRow v-for="r in rows" :key="r.id">
 *         <TableCell>{{ r.source }}</TableCell>
 *         <TableCell align="right">{{ pct(r.rate) }}</TableCell>
 *       </TableRow>
 *     </TableBody>
 *   </Table>
 *
 * Each primitive is a thin wrapper that just applies the right class. No
 * runtime cost, easy to override per-instance.
 */
import { cn } from "@/lib/utils";

defineProps<{ class?: string }>();
</script>

<template>
  <div
    :class="
      cn(
        'overflow-hidden rounded-[var(--radius-sm)] border border-[var(--color-line)]',
        $props.class,
      )
    "
  >
    <table class="w-full caption-bottom text-sm">
      <slot />
    </table>
  </div>
</template>
