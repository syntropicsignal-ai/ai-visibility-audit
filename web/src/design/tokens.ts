/**
 * Chart-only design tokens.
 *
 * Anything CSS lives in `style.css` (the @theme block + custom utilities).
 * This module exists for the small set of values that JavaScript needs as
 * concrete strings — Chart.js doesn't accept `var(--color-…)`.
 *
 * Keep these in lockstep with the CSS palette. If you change petrol in
 * style.css, change accent here too.
 */

/**
 * Multi-series chart palette — five visually distinct colors that read
 * well against the warm-paper background. Order is intentional: the
 * first slot is the brand accent so the most-important series matches
 * the rest of the UI's accent.
 */
export const chartPalette = [
  "#1A4A52", // petrol — primary (matches --color-accent)
  "#B8632F", // burnt orange — secondary
  "#3D6A86", // muted slate-blue — info
  "#2D6A4F", // forest — success
  "#7A4E8E", // muted plum — extra
  "#A23E2A", // brick — danger
] as const;

/**
 * Status palette for run lifecycle. Pulled from the semantic tokens so
 * "completed" badges read the same color whether they're rendered by
 * <Badge tone="success"> in markup or by the chart axis annotation.
 */
export const statusColors = {
  completed: "#2D6A4F",
  failed: "#A23E2A",
  running: "#3D6A86",
  pending: "#8B8E94",
} as const;

/**
 * Sentiment palette. Used only in the Responses inline indicators.
 */
export const sentimentColors = {
  positive: "#2D6A4F",
  neutral: "#8B8E94",
  negative: "#A23E2A",
  not_mentioned: "#C9C3B6",
} as const;
