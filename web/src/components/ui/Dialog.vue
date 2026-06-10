<script setup lang="ts">
/**
 * Dialog (modal) — radix-vue with our overlay/content styling.
 *
 * Usage:
 *   <Dialog v-model:open="open" title="Edit brand">
 *     <slot content goes here />
 *     <template #footer>
 *       <Button>Save</Button>
 *     </template>
 *   </Dialog>
 *
 * The overlay uses a soft warm-tinted backdrop matching the page bg
 * rather than the typical pure-black scrim — keeps the editorial mood.
 */
import {
  DialogRoot,
  DialogTrigger,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "radix-vue";
import { X } from "lucide-vue-next";
import { cn } from "@/lib/utils";

const open = defineModel<boolean>("open");

defineProps<{
  title: string;
  description?: string;
  /** Wider modal for forms with multiple fields. md (default) / lg / xl */
  size?: "md" | "lg" | "xl";
  class?: string;
}>();
</script>

<template>
  <DialogRoot v-model:open="open">
    <DialogTrigger v-if="$slots.trigger" as-child>
      <slot name="trigger" />
    </DialogTrigger>
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 z-40 bg-[color-mix(in_srgb,var(--color-fg)_30%,transparent)] backdrop-blur-[2px]
               data-[state=open]:animate-in data-[state=open]:fade-in-0
               data-[state=closed]:animate-out data-[state=closed]:fade-out-0"
      />
      <DialogContent
        :class="
          cn(
            'fixed z-50 left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2',
            'w-[calc(100vw-2rem)] max-h-[calc(100vh-3rem)] overflow-auto',
            'bg-[var(--color-surface)] border border-[var(--color-line)] rounded-[var(--radius-lg)] shadow-lg',
            'p-6',
            size === 'xl' ? 'max-w-3xl' : size === 'lg' ? 'max-w-xl' : 'max-w-md',
            'data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95',
            'data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95',
            $props.class,
          )
        "
      >
        <header class="flex items-start justify-between gap-3 mb-5">
          <div class="min-w-0">
            <DialogTitle class="font-display text-lg font-medium tracking-tight">
              {{ title }}
            </DialogTitle>
            <DialogDescription
              v-if="description"
              class="text-xs text-[var(--color-fg-muted)] mt-1"
            >
              {{ description }}
            </DialogDescription>
          </div>
          <DialogClose
            class="shrink-0 -mr-1 -mt-1 inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)]
                   text-[var(--color-fg-muted)] hover:text-[var(--color-fg)] hover:bg-[var(--color-surface-2)] focus-ring"
            aria-label="Close"
          >
            <X class="h-4 w-4" />
          </DialogClose>
        </header>

        <div class="text-sm">
          <slot />
        </div>

        <footer
          v-if="$slots.footer"
          class="mt-6 pt-4 border-t border-[var(--color-line)] flex justify-end gap-2"
        >
          <slot name="footer" />
        </footer>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
