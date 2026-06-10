<script setup lang="ts">
/**
 * TopicsSankey (Option B).
 *
 * Bipartite Sankey of topics → brands. Band thickness = number of
 * responses in the topic where the brand was mentioned. The Cytoscape
 * force-directed attempt produced an unreadable hairball for this
 * data shape (every topic connected to most brands AND all sources);
 * a Sankey is bipartite by construction, can't hairball, and shows
 * "who owns what topic" at a glance.
 *
 * Self-brand band gets the accent colour so it pops against the
 * grey competitor bands. Click a topic node to filter the table view
 * below to that topic; click a brand to highlight only its bands;
 * click a band itself to filter to that specific topic+brand pair.
 */
import { computed, ref, watch } from "vue";
import {
  sankey,
  sankeyJustify,
  sankeyLinkHorizontal,
  type SankeyGraph,
  type SankeyNode,
  type SankeyLink,
} from "d3-sankey";
import type { TopicGraph } from "@/api/types";

interface NodeDatum {
  id: string;
  kind: "topic" | "brand";
  label: string;
  isSelf: boolean;
}

interface LinkDatum {
  source: string;
  target: string;
  value: number;
}

type LaidOutNode = SankeyNode<NodeDatum, LinkDatum>;
type LaidOutLink = SankeyLink<NodeDatum, LinkDatum>;

const props = defineProps<{ data: TopicGraph | null; loading: boolean }>();
const emit = defineEmits<{ (e: "select-topic", topic: string | null): void }>();

const width = 1100;
const height = 640;
const margin = { top: 12, right: 200, bottom: 12, left: 12 };

// Hover highlight state — null means no highlight (everything full opacity).
// Hovering a node fades all unrelated nodes & links; hovering a link fades
// every other link and the two unrelated nodes.
const hoveredId = ref<string | null>(null);

// Selected topic — emitted up so the parent can filter the table.
// Visually the selected topic node also gets a highlight ring.
const selectedTopicId = ref<string | null>(null);

// Custom tooltip — replaces the SVG <title> default which is slow to
// show and easy to miss. Positioned in container-local coords so it
// follows the cursor. `null` = hidden.
interface TooltipState {
  x: number;        // px relative to the component root
  y: number;
  title: string;    // bold heading line
  detail: string;   // grey detail line
  accent?: boolean; // tint heading with the self-brand colour
}
const tooltip = ref<TooltipState | null>(null);
const containerEl = ref<HTMLDivElement | null>(null);

function tooltipPosition(evt: MouseEvent): { x: number; y: number } {
  const rect = containerEl.value?.getBoundingClientRect();
  if (!rect) return { x: evt.clientX, y: evt.clientY };
  return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
}

const layout = computed(() => {
  if (!props.data) return null;

  // Sankey requires unique node ids and link source/target referencing
  // those ids (or array indices). We feed our backend ids verbatim.
  // Filter out brand nodes that have zero links — they'd render as
  // floating zero-height rects.
  const linkedNodeIds = new Set<string>();
  for (const e of props.data.edges) {
    linkedNodeIds.add(e.source);
    linkedNodeIds.add(e.target);
  }
  const nodes: NodeDatum[] = props.data.nodes
    .filter((n) => linkedNodeIds.has(n.id))
    .map((n) => ({
      id: n.id,
      kind: n.kind as "topic" | "brand",
      label: n.label,
      isSelf: n.is_self,
    }));
  const links: LinkDatum[] = props.data.edges.map((e) => ({
    source: e.source,
    target: e.target,
    value: e.weight,
  }));

  if (nodes.length === 0 || links.length === 0) return null;

  const sk = sankey<NodeDatum, LinkDatum>()
    .nodeId((n) => n.id)
    .nodeAlign(sankeyJustify)
    .nodeWidth(14)
    .nodePadding(10)
    .extent([
      [margin.left, margin.top],
      [width - margin.right, height - margin.bottom],
    ]);

  const graph: SankeyGraph<NodeDatum, LinkDatum> = sk({
    nodes: nodes.map((n) => ({ ...n })),
    links: links.map((l) => ({ ...l })),
  });

  return graph;
});

const linkPath = sankeyLinkHorizontal<NodeDatum, LinkDatum>();

// Per-node fill: self brand = accent teal; competitors = neutral grey;
// topics = soft graphite. We pull straight hexes here rather than CSS
// vars so SVG fill resolves predictably (no var-resolution surprises
// like the Cytoscape canvas had).
function nodeFill(n: LaidOutNode): string {
  if (n.kind === "brand" && n.isSelf) return "#0E7888";
  if (n.kind === "brand") return "#6E7888";
  return "#3D434F";
}

// Link colour — solid soft accent for self-brand bands so they catch
// the eye, neutral grey for competitor bands. Same hex palette as the
// node fills so a band visually inherits its target colour.
function linkStroke(l: LaidOutLink): string {
  const target = l.target as LaidOutNode;
  if (target.kind === "brand" && target.isSelf) return "#0E7888";
  return "#A8B5BD";
}

// Highlight fade: when something is hovered, everything not connected
// to it drops to low opacity. Click-selection on a topic uses the same
// dimming for its non-selected siblings (only when hover isn't active).
function nodeOpacity(n: LaidOutNode): number {
  const focus = hoveredId.value;
  if (!focus) return 1;
  if (n.id === focus) return 1;
  // A node is "lit" if it's directly connected to the focus node.
  for (const l of layout.value?.links ?? []) {
    const src = (l.source as LaidOutNode).id;
    const tgt = (l.target as LaidOutNode).id;
    if ((src === focus && tgt === n.id) || (tgt === focus && src === n.id)) {
      return 1;
    }
  }
  return 0.18;
}

function linkOpacity(l: LaidOutLink): number {
  const focus = hoveredId.value;
  if (!focus) return 0.55;
  const src = (l.source as LaidOutNode).id;
  const tgt = (l.target as LaidOutNode).id;
  if (src === focus || tgt === focus) return 0.85;
  return 0.08;
}

function isSelectedTopic(n: LaidOutNode): boolean {
  return selectedTopicId.value === n.id && n.kind === "topic";
}

function onNodeClick(n: LaidOutNode) {
  if (n.kind !== "topic") return; // brand clicks don't filter (yet)
  const topicLabel = n.label;
  if (selectedTopicId.value === n.id) {
    selectedTopicId.value = null;
    emit("select-topic", null);
  } else {
    selectedTopicId.value = n.id;
    emit("select-topic", topicLabel);
  }
}

function onSvgClick(evt: MouseEvent) {
  // Click on empty space clears selection.
  if (evt.target === evt.currentTarget) {
    selectedTopicId.value = null;
    emit("select-topic", null);
  }
}

// When the data changes (dimension toggle, source filter) clear any
// stale selection so we don't filter to a topic that no longer exists.
watch(
  () => props.data,
  () => {
    selectedTopicId.value = null;
  },
);

function showNodeTooltip(n: LaidOutNode, evt: MouseEvent) {
  const total = (n.value ?? 0) | 0;
  const pos = tooltipPosition(evt);
  if (n.kind === "topic") {
    tooltip.value = {
      ...pos,
      title: n.label,
      detail: `Topic · ${total} response${total === 1 ? "" : "s"} across kept brands`,
    };
  } else {
    tooltip.value = {
      ...pos,
      title: n.label,
      detail: `${n.isSelf ? "Self brand" : "Competitor"} · mentioned in ${total} response${total === 1 ? "" : "s"} across kept topics`,
      accent: n.isSelf,
    };
  }
}

function showLinkTooltip(l: LaidOutLink, evt: MouseEvent) {
  const src = (l.source as LaidOutNode).label;
  const tgt = (l.target as LaidOutNode).label;
  const isSelf = (l.target as LaidOutNode).isSelf;
  const w = (l.value ?? 0) | 0;
  tooltip.value = {
    ...tooltipPosition(evt),
    title: `${src} → ${tgt}`,
    detail: `${w} mention${w === 1 ? "" : "s"}`,
    accent: isSelf,
  };
}

function moveTooltip(evt: MouseEvent) {
  if (tooltip.value) {
    const pos = tooltipPosition(evt);
    tooltip.value = { ...tooltip.value, x: pos.x, y: pos.y };
  }
}

function hideTooltip() {
  tooltip.value = null;
}
</script>

<template>
  <div
    ref="containerEl"
    class="relative w-full bg-[var(--color-surface)] border border-[var(--color-line)] rounded-lg overflow-hidden"
  >
    <div
      v-if="loading"
      class="absolute inset-0 flex items-center justify-center text-[12px] text-[var(--color-fg-muted)] bg-[var(--color-surface)]/80 backdrop-blur-sm z-10"
    >Building graph…</div>

    <svg
      v-if="layout"
      :viewBox="`0 0 ${width} ${height}`"
      class="w-full h-auto"
      preserveAspectRatio="xMidYMid meet"
      @click="onSvgClick"
    >
      <!-- Links first so nodes draw on top -->
      <g class="links">
        <path
          v-for="(l, i) in layout.links"
          :key="i"
          :d="linkPath(l) ?? ''"
          fill="none"
          :stroke="linkStroke(l)"
          :stroke-width="Math.max(1, l.width ?? 1)"
          :stroke-opacity="linkOpacity(l)"
          class="transition-opacity"
          @mouseenter="(evt: MouseEvent) => { hoveredId = (l.source as LaidOutNode).id; showLinkTooltip(l, evt); }"
          @mousemove="moveTooltip"
          @mouseleave="() => { hoveredId = null; hideTooltip(); }"
        />
      </g>

      <!-- Nodes: rect + label -->
      <g class="nodes">
        <g
          v-for="n in layout.nodes"
          :key="n.id"
          :transform="`translate(${n.x0 ?? 0}, ${n.y0 ?? 0})`"
          class="cursor-pointer transition-opacity"
          :style="{ opacity: nodeOpacity(n) }"
          @mouseenter="(evt: MouseEvent) => { hoveredId = n.id; showNodeTooltip(n, evt); }"
          @mousemove="moveTooltip"
          @mouseleave="() => { hoveredId = null; hideTooltip(); }"
          @click.stop="onNodeClick(n)"
        >
          <rect
            :width="(n.x1 ?? 0) - (n.x0 ?? 0)"
            :height="Math.max(1, (n.y1 ?? 0) - (n.y0 ?? 0))"
            :fill="nodeFill(n)"
            :stroke="isSelectedTopic(n) ? '#1A1B1F' : 'none'"
            :stroke-width="isSelectedTopic(n) ? 2 : 0"
            rx="2"
          />
          <text
            :x="n.kind === 'topic' ? -6 : ((n.x1 ?? 0) - (n.x0 ?? 0)) + 6"
            :y="((n.y1 ?? 0) - (n.y0 ?? 0)) / 2"
            dy="0.35em"
            :text-anchor="n.kind === 'topic' ? 'end' : 'start'"
            :font-weight="n.isSelf ? 700 : 500"
            :fill="n.isSelf ? '#0E7888' : '#1A1B1F'"
            font-size="12"
            font-family="system-ui, -apple-system, 'Segoe UI', sans-serif"
            style="user-select: none; pointer-events: none;"
          >{{ n.label }}<tspan
            class="font-mono text-[var(--color-fg-muted)]"
            :fill="'#7C8493'"
            font-size="10"
            dx="6"
          >{{ (n.value ?? 0) | 0 }}</tspan></text>
        </g>
      </g>
    </svg>

    <p
      v-else-if="!loading && props.data"
      class="text-[var(--color-fg-muted)] text-sm text-center py-16"
    >No topic↔brand mentions in scope.</p>

    <!-- Legend -->
    <div class="absolute top-3 right-3 flex flex-col gap-1.5 bg-[var(--color-surface)]/90 backdrop-blur-sm border border-[var(--color-line)] rounded-md px-3 py-2 text-[11px] z-10">
      <div class="font-semibold text-[var(--color-fg)] uppercase tracking-wider text-[10px] mb-0.5">Legend</div>
      <div class="flex items-center gap-2">
        <span class="inline-block w-3 h-3 rounded-sm bg-[#3D434F]" />
        <span class="text-[var(--color-fg-2)]">Topic</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="inline-block w-3 h-3 rounded-sm bg-[#6E7888]" />
        <span class="text-[var(--color-fg-2)]">Competitor</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="inline-block w-3 h-3 rounded-sm bg-[#0E7888]" />
        <span class="text-[var(--color-fg)] font-medium">Self brand</span>
      </div>
    </div>

    <p class="absolute bottom-3 left-3 text-[11px] text-[var(--color-fg-muted)] bg-[var(--color-surface)]/80 backdrop-blur-sm rounded-md px-2 py-1 z-10">
      Band thickness = mentions · hover to focus · click a topic to filter the table below
    </p>

    <!-- Cursor-following tooltip. Pointer-events disabled so the
         tooltip never steals hover from the node it describes. The
         small 14/18px offset keeps it from sitting under the cursor. -->
    <div
      v-if="tooltip"
      class="absolute z-20 pointer-events-none rounded-md px-2.5 py-1.5 shadow-lg border border-black/10"
      :style="{
        left: `${tooltip.x + 14}px`,
        top: `${tooltip.y + 18}px`,
        background: '#1A1B1F',
        color: '#FFFFFF',
        maxWidth: '320px',
      }"
    >
      <div
        class="text-[12.5px] font-semibold leading-tight"
        :style="{ color: tooltip.accent ? '#5DC4D4' : '#FFFFFF' }"
      >{{ tooltip.title }}</div>
      <div
        class="text-[11px] leading-tight mt-0.5"
        style="color: #B8BEC8;"
      >{{ tooltip.detail }}</div>
    </div>
  </div>
</template>
