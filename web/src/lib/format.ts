export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(digits);
}

/**
 * Format an estimated USD cost for display in tables.
 *   null/undefined → "—" (older runs that ran before token capture)
 *   0              → "$0.00"
 *   < $0.01        → "<$0.01"
 *   otherwise      → "$1.23"
 */
export function usd(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (v === 0) return "$0.00";
  if (v < 0.01) return "<$0.01";
  return `$${v.toFixed(2)}`;
}

export function date(v: string | Date): string {
  const d = typeof v === "string" ? new Date(v) : v;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortDate(v: string | Date): string {
  const d = typeof v === "string" ? new Date(v) : v;
  return d.toLocaleString(undefined, { month: "short", day: "numeric" });
}

export function timeAgo(v: string | Date): string {
  const d = typeof v === "string" ? new Date(v) : v;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function deltaPct(curr: number, prev: number | null | undefined): number | null {
  if (prev === null || prev === undefined) return null;
  return (curr - prev) * 100; // percentage points
}
