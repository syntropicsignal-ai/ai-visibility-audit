import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge classnames intelligently.
 *
 * `clsx` flattens arrays/objects into a class string; `tailwind-merge`
 * resolves conflicting Tailwind utilities (e.g. last `p-2` wins over `p-4`).
 * Together they're the standard shadcn-vue utility — every component
 * primitive in `src/components/ui/` accepts a `class` prop and routes it
 * through `cn()` so callers can override defaults safely.
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
