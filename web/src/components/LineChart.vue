<script setup lang="ts">
import {
  CategoryScale,
  type ChartOptions,
  Chart as ChartJS,
  Filler,
  Legend,
  LineElement,
  LinearScale,
  PointElement,
  Tooltip,
} from "chart.js";
import { Line } from "vue-chartjs";
import { computed } from "vue";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
);

interface Series {
  label: string;
  data: number[];
  color: string;
  /** Render as a dashed line — useful for distinguishing a derived series
   *  (e.g. sentiment) from primary metrics on the same chart. */
  dashed?: boolean;
}

const props = defineProps<{
  labels: string[];
  series: Series[];
  /** Format y-axis ticks (e.g. percent). */
  yFormat?: (v: number) => string;
}>();

const data = computed(() => ({
  labels: props.labels,
  datasets: props.series.map((s) => ({
    label: s.label,
    data: s.data,
    borderColor: s.color,
    backgroundColor: s.color + "22",
    borderWidth: 2,
    borderDash: s.dashed ? [4, 4] : undefined,
    tension: 0.35,
    pointRadius: 0,
    pointHoverRadius: 4,
    pointBackgroundColor: s.color,
    pointBorderColor: s.color,
    fill: false,
  })),
}));

const options = computed<ChartOptions<"line">>(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: { mode: "index", intersect: false },
  plugins: {
    legend: {
      position: "top",
      align: "end",
      labels: {
        boxWidth: 6,
        boxHeight: 6,
        usePointStyle: true,
        padding: 16,
        font: { family: "Outfit Variable, system-ui, sans-serif", size: 11, weight: 500 },
        color: "#5C5F66",
      },
    },
    tooltip: {
      backgroundColor: "#1A1B1F",
      titleFont: { family: "Outfit Variable, system-ui, sans-serif", size: 11, weight: 600 },
      bodyFont: { family: "Outfit Variable, system-ui, sans-serif", size: 11 },
      padding: 10,
      cornerRadius: 6,
      displayColors: true,
      boxPadding: 4,
      callbacks: {
        label: (ctx) => {
          const v = ctx.parsed.y ?? 0;
          const formatted = props.yFormat ? props.yFormat(v) : String(v);
          return `  ${ctx.dataset.label ?? ""}  ${formatted}`;
        },
      },
    },
  },
  scales: {
    y: {
      beginAtZero: true,
      border: { display: false },
      ticks: {
        callback: (v) => (props.yFormat ? props.yFormat(Number(v)) : String(v)),
        font: { family: "JetBrains Mono Variable, monospace", size: 10 },
        color: "#8B8E94",
        padding: 6,
      },
      grid: { color: "#E8E5DD" },
    },
    x: {
      border: { display: false },
      ticks: {
        font: { family: "Outfit Variable, system-ui, sans-serif", size: 10 },
        color: "#8B8E94",
      },
      grid: { display: false },
    },
  },
}));
</script>

<template>
  <div class="relative h-64">
    <Line :data="data" :options="options" />
  </div>
</template>
