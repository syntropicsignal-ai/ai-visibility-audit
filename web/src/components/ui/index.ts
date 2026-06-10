/**
 * Single import point for all UI primitives.
 *
 * Encourages consistent usage across views:
 *
 *   import { Button, Card, Badge, Table, TableRow } from "@/components/ui";
 *
 * over per-file imports. Prevents the situation where one view imports
 * Button from "primevue/button" while another imports our custom one.
 */
export { default as Button } from "./Button.vue";
export { default as Card } from "./Card.vue";
export { default as CardHeader } from "./CardHeader.vue";
export { default as Badge } from "./Badge.vue";
export { default as Input } from "./Input.vue";
export { default as Textarea } from "./Textarea.vue";
export { default as Select } from "./Select.vue";
export { default as Switch } from "./Switch.vue";
export { default as Checkbox } from "./Checkbox.vue";
export { default as Dialog } from "./Dialog.vue";
export { default as Tabs } from "./Tabs.vue";
export { default as Tooltip } from "./Tooltip.vue";

export { default as Table } from "./Table.vue";
export { default as TableHeader } from "./TableHeader.vue";
export { default as TableBody } from "./TableBody.vue";
export { default as TableRow } from "./TableRow.vue";
export { default as TableHead } from "./TableHead.vue";
export { default as TableCell } from "./TableCell.vue";
