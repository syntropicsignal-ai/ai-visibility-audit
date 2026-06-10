import { ref } from "vue";

// Module-scoped so App.vue (auto-trigger) and Topbar (manual reopen)
// share one open/close state. Matches the lightweight toasts.ts pattern.
const dialogOpen = ref(false);

export function useSetupDialog() {
  return {
    dialogOpen,
    open: () => {
      dialogOpen.value = true;
    },
    close: () => {
      dialogOpen.value = false;
    },
  };
}
