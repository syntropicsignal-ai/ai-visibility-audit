<script setup lang="ts">
/**
 * App shell. Routes opt out of the shell with `meta.layout = "blank"`
 * (used by the printable report).
 */
import { computed, onMounted } from "vue";
import { RouterView, useRoute } from "vue-router";
import { Toaster } from "vue-sonner";
import Sidebar from "./components/Sidebar.vue";
import Topbar from "./components/Topbar.vue";
import SetupDialog from "./components/SetupDialog.vue";
import { api } from "@/api/client";
import { useSetupDialog } from "@/stores/setup";

const route = useRoute();
const blank = computed(() => route.meta?.layout === "blank");
const { open } = useSetupDialog();

const ONBOARDING_SEEN_KEY = "ai-visibility-audit.onboarding_seen";

// First run only: a couple seconds after load, if keys are missing and the
// user isn't already exploring demo data, surface the setup modal once.
// Setup is never mandatory — they dismiss it and reopen from the topbar.
onMounted(async () => {
  if (route.meta?.layout === "blank") return;
  if (localStorage.getItem(ONBOARDING_SEEN_KEY)) return;
  try {
    const [cfg, demo] = await Promise.all([api.configStatus(), api.demoStatus()]);
    if (cfg.setup_required && !demo.is_demo) {
      setTimeout(() => {
        localStorage.setItem(ONBOARDING_SEEN_KEY, "1");
        open();
      }, 2500);
    } else {
      localStorage.setItem(ONBOARDING_SEEN_KEY, "1");
    }
  } catch {
    /* api offline — no nag; topbar button still opens setup manually */
  }
});
</script>

<template>
  <RouterView v-if="blank" />
  <div v-else class="flex min-h-screen bg-[var(--color-bg)]">
    <Sidebar />
    <main class="flex-1 min-w-0 flex flex-col">
      <Topbar />
      <div class="flex-1 min-w-0 px-7 pt-6 pb-9 overflow-auto bg-[var(--color-bg)]">
        <div class="max-w-[1400px] mx-auto">
          <RouterView />
        </div>
      </div>
    </main>
    <Toaster
      position="bottom-right"
      :toast-options="{
        class: 'sonner-toast',
      }"
    />
    <SetupDialog />
  </div>
</template>

<style>
/* Sonner gets its own scoped CSS vars. We want it to feel like our system. */
[data-sonner-toaster][data-theme] {
  --normal-bg: var(--color-surface);
  --normal-border: var(--color-line);
  --normal-text: var(--color-fg);
  --success-bg: var(--color-success-soft);
  --success-border: color-mix(in srgb, var(--color-success), transparent 70%);
  --success-text: var(--color-success);
  --error-bg: var(--color-danger-soft);
  --error-border: color-mix(in srgb, var(--color-danger), transparent 70%);
  --error-text: var(--color-danger);
  font-family: var(--font-sans);
}
.sonner-toast {
  border-radius: var(--radius-md) !important;
  box-shadow: var(--shadow-md) !important;
}
</style>
