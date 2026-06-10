/**
 * Thin wrapper over `vue-sonner` so call-sites keep their existing
 * `useToasts().success(msg)` / `.error(msg)` ergonomics. The sonner
 * `<Toaster />` component is mounted once in App.vue.
 *
 * Why a wrapper at all: the call-site API isn't tied to the toast lib,
 * so swapping sonner for something else later (or muting all toasts in
 * tests) is one file's worth of change instead of dozens.
 */
import { toast } from "vue-sonner";

export function useToasts() {
  return {
    success: (message: string) => toast.success(message),
    error: (message: string) => toast.error(message),
    info: (message: string) => toast.info(message),
    warn: (message: string) => toast.warning(message),
  };
}
