import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "vite";
import { h } from "vue";
import { renderToString } from "@vue/server-renderer";

let server, LossChart;
before(async () => {
  server = await createServer({
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  ({ default: LossChart } = await server.ssrLoadModule("/src/components/LossChart.vue"));
});
after(async () => { await server?.close(); });

const render = (points) => renderToString(h(LossChart, { points }));
const group = (html, kind) =>
  html.match(new RegExp(`<g[^>]*data-kind="${kind}"[^>]*>([\\s\\S]*?)</g>`))?.[1] ?? "";
const summary = (html, kind) =>
  html.match(new RegExp(`<div[^>]*data-kind="${kind}"[^>]*>([\\s\\S]*?)</div>`))?.[1] ?? "";
const circles = (html) => [...html.matchAll(/<circle\b[^>]*>/g)].map(([tag]) => tag);
const coordinates = (html) => circles(html).map((tag) =>
  ["cx", "cy"].map((attr) => Number(tag.match(new RegExp(`${attr}="([^"]+)"`))[1])),
);

test("相同 step 的 train/eval 独立连线、图例及提示，不互相覆盖", async () => {
  // 以下均为隔离组件测试数据，不是训练或效果证据。
  const html = await render([
    { kind: "train", step: 1, loss: 1.8 },
    { kind: "eval", step: 1, loss: 2.1 },
    { kind: "train", step: 2, loss: 1.2 },
    { kind: "eval", step: 2, loss: 1.6 },
  ]);
  const train = group(html, "train"), evaluation = group(html, "eval");
  assert.equal(circles(train).length, 2);
  assert.equal(circles(evaluation).length, 2);
  assert.equal((html.match(/<polyline\b/g) ?? []).length, 2);
  assert.match(train, /stroke="#138d79"/);
  assert.match(evaluation, /stroke="#7862b3"/);
  assert.match(evaluation, /stroke-dasharray="6 4"/);
  assert.match(train, /训练 Loss · Step 1 · Loss 1.8/);
  assert.match(evaluation, /验证 Loss · Step 1 · Loss 2.1/);
  assert.match(html, /共 4 个指标点/);
  const trainXY = coordinates(train), evalXY = coordinates(evaluation);
  assert.equal(trainXY[0][0], evalXY[0][0]);
  assert.equal(trainXY[1][0], evalXY[1][0]);
  assert.ok(evalXY[0][1] < trainXY[0][1], "两系列共用 Loss 纵轴");
});

test("乱序输入按 step 展示，末尾 eval 不冒充最新训练 Loss", async () => {
  const points = [
    { kind: "train", step: 3, loss: 0.8 },
    { kind: "train", step: 1, loss: 1.4 },
    { kind: "eval", step: 4, loss: 0.6 },
  ];
  const original = structuredClone(points);
  const html = await render(points);
  assert.match(summary(html, "train"), /0.8000/);
  assert.match(summary(html, "eval"), /0.6000/);
  const train = group(html, "train");
  assert.ok(train.indexOf("Step 1") < train.indexOf("Step 3"));
  assert.deepEqual(points, original, "展示不排序或改写调用方记录");
});

test("只有 train 时不生成 eval 图例、零线或补点", async () => {
  const html = await render([
    { kind: "train", step: 1, loss: 1.4 },
    { kind: "train", step: 5, loss: 0.8 },
  ]);
  assert.equal(circles(html).length, 2);
  assert.equal(group(html, "eval"), "");
  assert.equal(summary(html, "eval"), "");
  assert.doesNotMatch(html, /验证 Loss|<path\b/);
  assert.equal(group(html, "train").match(/<polyline[^>]*points="([^"]+)"/)[1].split(" ").length, 2);
});

test("只有 eval 时不标成训练 Loss", async () => {
  const html = await render([{ kind: "eval", step: 2, loss: 0.9 }]);
  assert.equal(group(html, "train"), "");
  assert.equal(summary(html, "train"), "");
  assert.match(html, /验证 Loss/);
  assert.doesNotMatch(html, /最新训练记录|训练 Loss/);
});

test("单个零 Loss 是有效点，坐标有限且不连接虚构记录", async () => {
  const html = await render([{ kind: "train", step: 7, loss: 0 }]);
  assert.match(summary(html, "train"), /0.0000/);
  assert.equal(circles(html).length, 1);
  assert.doesNotMatch(html, /<polyline|NaN|Infinity|暂无 Loss/);
  assert.ok(coordinates(html).flat().every(Number.isFinite));
  assert.equal(coordinates(html)[0][0], 363, "单步居中");
});

test("同 step 同 Loss 的两种点均保留，可用实心与空心标识辨认", async () => {
  const html = await render([
    { kind: "train", step: 2, loss: 0 },
    { kind: "eval", step: 2, loss: 0 },
  ]);
  assert.equal(circles(html).length, 2);
  assert.deepEqual(coordinates(group(html, "train")), coordinates(group(html, "eval")));
  assert.match(group(html, "train"), /r="3.5"[^>]*fill="#138d79"/);
  assert.match(group(html, "eval"), /r="5"[^>]*fill="none"/);
  assert.doesNotMatch(html, /<polyline|NaN|Infinity/);
});

test("空记录使用中性提示，不暗示任务仍在训练，不生成 SVG", async () => {
  const html = await render([]);
  assert.match(html, /暂无 Loss 记录/);
  assert.doesNotMatch(html, /<polyline|<circle|class="loss-chart"|等待第一条|正在训练/);
});

test("无效展示记录不变成零点，也不猜测缺失或未知的 kind", async () => {
  const html = await render([
    null,
    { kind: "train", step: 1, loss: null },
    { kind: "train", step: 2, loss: NaN },
    { kind: "eval", step: 3, loss: Infinity },
    { kind: "train", step: 4, loss: -1 },
    { kind: "train", step: 0, loss: 0.3 },
    { kind: "train", step: 1.5, loss: 0.3 },
    { kind: "train", step: "2", loss: 0.3 },
    { kind: "other", step: 2, loss: 0.3 },
    { step: 2, loss: 0.3 },
    { kind: "train", step: 2, loss: "0.3" },
    { kind: "eval", step: 2, loss: 0.4 },
  ]);
  assert.equal(circles(html).length, 1);
  assert.match(html, /共 1 个指标点/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});
