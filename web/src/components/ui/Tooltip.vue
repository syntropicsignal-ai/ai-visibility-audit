<script setup lang="ts">
/**
 * Tooltip — radix-vue Tooltip with our chrome.
 *
 * Usage:
 *   <Tooltip content="Total responses">
 *     <span tabindex="0">{{ stat }}</span>
 *   </Tooltip>
 *
 * The default slot is the trigger, `content` prop is the tooltip body.
 * Wrap the trigger in a focusable element if it isn't one already.
 */
import {
  TooltipProvider,
  TooltipRoot,
  TooltipTrigger,
  TooltipPortal,
  TooltipContent,
} from "radix-vue";

defineProps<{
  content: string;
  side?: "top" | "right" | "bottom" | "left";
  delay?: number;
}>();
</script>

<template>
  <TooltipProvider :delay-duration="delay ?? 200">
    <TooltipRoot>
      <TooltipTrigger as-child>
        <slot />
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent
          :side="side ?? 'top'"
          :side-offset="6"
          class="z-50 px-2 py-1 rounded-[var(--radius-xs)] bg-[var(--color-fg)] text-white text-xs shadow-md
                 data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0
                 data-[state=closed]:animate-out data-[state=closed]:fade-out-0"
        >
          {{ content }}
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>
