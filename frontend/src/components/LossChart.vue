<script setup>
import { computed } from "vue";
import EmptyState from "./EmptyState.vue";
const props = defineProps({ points: { type: Array, default: () => [] } });
const valid = computed(() =>
  props.points
    .filter(
      (p) =>
        p &&
        (p.kind === "train" || p.kind === "eval") &&
        Number.isSafeInteger(p.step) && p.step > 0 &&
        Number.isFinite(p.loss) && p.loss >= 0,
    )
    .map((point, index) => ({ ...point, key: index }))
    .toSorted((a, b) => a.step - b.step),
);
const series = computed(() =>
  [
    { kind: "train", label: "训练 Loss", color: "#138d79" },
    { kind: "eval", label: "验证 Loss", color: "#7862b3" },
  ]
    .map((entry) => ({
      ...entry,
      points: valid.value.filter((point) => point.kind === entry.kind),
    }))
    .filter((entry) => entry.points.length),
);
const chartLabel = computed(() =>
  `Loss 曲线，共 ${valid.value.length} 个指标点；` +
  series.value.map((entry) =>
    `${entry.label}：${entry.points.length} 个点，最新 ${entry.points.at(-1).loss}`,
  ).join("；"),
);
const bounds = computed(() => {
  if (!valid.value.length) return { x0: 0, x1: 0, y0: 0, y1: 1 };
  let low = Infinity, high = -Infinity;
  for (const point of valid.value) {
    low = Math.min(low, point.loss);
    high = Math.max(high, point.loss);
  }
  const pad = Math.max((high - low) * 0.15, Math.abs(high) * 0.05, 0.01);
  return {
    x0: valid.value[0].step,
    x1: valid.value.at(-1).step,
    y0: Math.max(0, low - pad),
    y1: high + pad,
  };
});
const x = (step) =>
  bounds.value.x0 === bounds.value.x1
    ? 363
    : 56 + ((step - bounds.value.x0) / (bounds.value.x1 - bounds.value.x0)) * 614;
const y = (loss) =>
  224 - ((loss - bounds.value.y0) / (bounds.value.y1 - bounds.value.y0)) * 194;
const line = (points) => points.map((p) => `${x(p.step)},${y(p.loss)}`).join(" ");
const ticks = computed(() =>
  Array.from(
    { length: 5 },
    (_, i) => bounds.value.y0 + ((bounds.value.y1 - bounds.value.y0) / 4) * i,
  ),
);
</script>
<template>
  <div v-if="valid.length" class="loss-chart">
    <div class="chart-legend">
      <div v-for="entry in series" :key="entry.kind" class="chart-series-summary"
        :data-kind="entry.kind" :style="{ '--series-color': entry.color }">
        <span><i :class="{ 'eval-swatch': entry.kind === 'eval' }" />{{ entry.label }}</span>
        <strong>{{ entry.points.at(-1).loss.toFixed(4) }} <small>最新{{ entry.kind === 'train' ? '训练' : '验证' }}记录</small></strong>
      </div>
    </div>
    <div class="chart-plot" :class="{ 'single-step': bounds.x0 === bounds.x1 }"
      role="region" aria-label="Loss 曲线绘图区，可横向滚动" tabindex="0">
    <svg
      viewBox="0 0 700 260"
      role="img"
      :aria-label="chartLabel"
    >
      <g v-for="tick in ticks" :key="tick">
        <line
          x1="56"
          x2="670"
          :y1="y(tick)"
          :y2="y(tick)"
          stroke="#e8edf1"
          stroke-dasharray="4 4"
        />
        <text x="45" :y="y(tick) + 4" text-anchor="end">
          {{ tick.toFixed(3) }}
        </text>
      </g>
      <g v-for="entry in series" :key="entry.kind" :data-kind="entry.kind">
        <polyline
          v-if="entry.points.length > 1"
          :points="line(entry.points)"
          fill="none"
          :stroke="entry.color"
          :stroke-dasharray="entry.kind === 'eval' ? '6 4' : undefined"
          stroke-width="2.5"
          stroke-linejoin="round"
        />
        <circle
          v-for="point in entry.points"
          :key="point.key"
          :cx="x(point.step)"
          :cy="y(point.loss)"
          :r="entry.kind === 'eval' ? 5 : 3.5"
          :fill="entry.kind === 'eval' ? 'none' : entry.color"
          :stroke="entry.color"
          stroke-width="2"
        >
          <title>{{ entry.label }} · Step {{ point.step }} · Loss {{ point.loss }}</title>
        </circle>
      </g>
      <text v-if="bounds.x0 === bounds.x1" x="363" y="250" text-anchor="middle">{{ bounds.x0 }} Step</text>
      <template v-else>
        <text x="56" y="250">{{ bounds.x0 }}</text>
        <text x="670" y="250" text-anchor="end">{{ bounds.x1 }} Step</text>
      </template>
    </svg>
    </div>
  </div>
  <EmptyState
    v-else
    icon="activity"
    title="暂无 Loss 记录"
    description="当前没有可展示的指标记录。"
  />
</template>

<style scoped>
.chart-legend {
  flex-wrap: wrap;
  gap: 12px 24px;
}
.chart-plot {
  overflow-x: auto;
}
.chart-plot svg {
  display: block;
  min-width: 640px;
}
.chart-plot.single-step svg {
  min-width: 0;
}
.chart-series-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 12px;
}
.chart-series-summary span,
.chart-series-summary strong {
  color: var(--series-color);
}
.chart-series-summary i {
  background: var(--series-color);
}
.chart-series-summary .eval-swatch {
  width: 18px;
  height: 0;
  border-top: 2px dashed var(--series-color);
  border-radius: 0;
  background: none;
}
</style>
