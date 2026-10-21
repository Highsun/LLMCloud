<script setup>
import { computed } from "vue";
import EmptyState from "./EmptyState.vue";
const props = defineProps({ points: { type: Array, default: () => [] } });
const valid = computed(() =>
  props.points
    .filter((p) => Number.isFinite(p.step) && Number.isFinite(p.loss))
    .toSorted((a, b) => a.step - b.step),
);
const bounds = computed(() => {
  const xs = valid.value.map((p) => p.step),
    ys = valid.value.map((p) => p.loss);
  const low = Math.min(...ys),
    high = Math.max(...ys);
  const pad = Math.max((high - low) * 0.15, Math.abs(high) * 0.05, 0.01);
  return {
    x0: Math.min(...xs),
    x1: Math.max(...xs),
    y0: low - pad,
    y1: high + pad,
  };
});
const x = (step) =>
  56 +
  ((step - bounds.value.x0) / (bounds.value.x1 - bounds.value.x0 || 1)) * 614;
const y = (loss) =>
  224 - ((loss - bounds.value.y0) / (bounds.value.y1 - bounds.value.y0)) * 194;
const line = computed(() =>
  valid.value.map((p) => `${x(p.step)},${y(p.loss)}`).join(" "),
);
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
      <span><i />Training Loss</span
      ><strong
        >{{ valid.at(-1).loss.toFixed(4) }} <small>最新记录</small></strong
      >
    </div>
    <svg
      viewBox="0 0 700 260"
      role="img"
      :aria-label="`训练 Loss 曲线，共 ${valid.length} 个真实数据点，最新 Loss ${valid.at(-1).loss}`"
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
      <polyline
        :points="line"
        fill="none"
        stroke="#138d79"
        stroke-width="2.5"
        stroke-linejoin="round"
      />
      <circle
        v-for="point in valid"
        :key="point.step"
        :cx="x(point.step)"
        :cy="y(point.loss)"
        r="3.5"
        fill="#138d79"
      >
        <title>Step {{ point.step }} · Loss {{ point.loss }}</title>
      </circle>
      <text x="56" y="250">{{ bounds.x0 }}</text>
      <text x="670" y="250" text-anchor="end">{{ bounds.x1 }} Step</text>
    </svg>
  </div>
  <EmptyState
    v-else
    icon="activity"
    title="等待第一条训练指标"
    description="模型加载期间可能暂无 Loss，开始训练后将在这里呈现真实记录。"
  />
</template>
