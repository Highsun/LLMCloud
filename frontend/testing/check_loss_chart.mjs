// Isolated component browser checks. No product-page fixtures, API, Worker or GPU.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium, expect } from "@playwright/test";

const root = fileURLToPath(new URL("..", import.meta.url));
const output = path.join(root, "test-results", `loss-chart-${Date.now()}`);
const fixturePath = "/__loss_chart_component_check__";
const server = await createServer({
  root,
  server: { host: "127.0.0.1", port: 0, strictPort: false, hmr: false, ws: false },
  plugins: [{
    name: "isolated-loss-chart-check",
    configureServer(vite) {
      vite.middlewares.use(async (req, res, next) => {
        if (req.url !== fixturePath) return next();
        try {
          const html = await vite.transformIndexHtml(fixturePath, `<!doctype html>
            <html lang="zh-CN"><meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <link rel="icon" href="data:,">
            <title>LossChart 隔离组件检查</title>
            <style>main { max-width: 900px; margin: 24px; padding: 16px; background: white; }</style>
            <main><p>隔离组件测试数据（非训练证据）</p><div id="app"></div></main>
            <script type="module">
              import { createApp, h, ref, nextTick } from 'vue';
              import LossChart from '/src/components/LossChart.vue';
              import '/src/style.css';
              const points = ref([]);
              createApp({ render: () => h(LossChart, { points: points.value }) }).mount('#app');
              window.setChartPoints = async (value) => { points.value = value; await nextTick(); };
            </script></html>`);
          res.setHeader("Content-Type", "text/html; charset=utf-8");
          res.end(html);
        } catch (error) { next(error); }
      });
    },
  }],
});

let browser;
try {
  await server.listen();
  const address = server.httpServer.address();
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "warning" || message.type() === "error") errors.push(message.text());
  });
  await mkdir(output, { recursive: true });
  await page.goto(`http://127.0.0.1:${address.port}${fixturePath}`);
  await page.waitForFunction(() => typeof window.setChartPoints === "function");
  const setPoints = (points) => page.evaluate((value) => window.setChartPoints(value), points);
  const fixtures = [
    { kind: "train", step: 1, loss: 1.8 },
    { kind: "eval", step: 1, loss: 2.1 },
    { kind: "train", step: 3, loss: 1.2 },
    { kind: "eval", step: 3, loss: 1.6 },
  ];
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await setPoints(fixtures);
    await expect(page.locator("svg g[data-kind=train] circle")).toHaveCount(2);
    await expect(page.locator("svg g[data-kind=eval] circle")).toHaveCount(2);
    await expect(page.locator("polyline")).toHaveCount(2);
    await expect(page.locator(".chart-series-summary[data-kind=train]")).toContainText("1.2000");
    await expect(page.locator(".chart-series-summary[data-kind=eval]")).toContainText("1.6000");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "页面不横向溢出");
    for (const legend of await page.locator(".chart-series-summary").all()) {
      const box = await legend.boundingBox();
      assert(box.x >= 0 && box.x + box.width <= width, "两类图例保持在视口内");
    }
    await page.screenshot({ path: path.join(output, `two-series-${width}.png`) });
    if (width === 390) {
      assert(await page.locator(".chart-plot").evaluate((plot) => plot.scrollWidth > plot.clientWidth));
      await page.locator(".chart-plot").focus();
      await page.keyboard.press("ArrowRight");
      await expect.poll(() => page.locator(".chart-plot").evaluate((plot) => plot.scrollLeft)).toBeGreaterThan(0);
      await page.locator(".chart-plot").evaluate((plot) => { plot.scrollLeft = plot.scrollWidth; });
      await page.screenshot({ path: path.join(output, "two-series-390-end.png") });
    }
  }
  await setPoints([{ kind: "train", step: 7, loss: 0 }]);
  await expect(page.locator("circle")).toHaveCount(1);
  await expect(page.locator("polyline")).toHaveCount(0);
  await expect(page.locator("[data-kind=eval]")).toHaveCount(0);
  await expect(page.locator(".chart-legend")).toContainText("0.0000");
  assert(!await page.locator("#app").evaluate((element) => /NaN|Infinity/.test(element.innerHTML)));
  const plotBox = await page.locator(".chart-plot").boundingBox();
  const pointBox = await page.locator("circle").boundingBox();
  assert(pointBox.x >= plotBox.x && pointBox.x + pointBox.width <= plotBox.x + plotBox.width,
    "窄屏单点直接可见，无需横向寻找");
  await page.screenshot({ path: path.join(output, "single-zero-390.png") });

  // Replace existing records at the same steps, then append: exercise Vue key/update behavior.
  await setPoints(fixtures.map((point) => ({ ...point, loss: 0.5 })));
  await expect(page.locator("circle")).toHaveCount(4);
  await setPoints([...fixtures, { kind: "train", step: 5, loss: 0.7 }]);
  await expect(page.locator("circle")).toHaveCount(5);
  await expect(page.locator(".chart-series-summary[data-kind=train]")).toContainText("0.7000");
  await expect(page.locator(".chart-series-summary[data-kind=eval]")).toContainText("1.6000");

  await setPoints([]);
  await expect(page.locator(".loss-chart")).toHaveCount(0);
  await expect(page.locator("#app")).toContainText("暂无 Loss 记录");
  await setPoints([{ kind: "eval", step: 4, loss: 0.9 }]);
  await expect(page.locator("svg g[data-kind=eval] circle")).toHaveCount(1);
  await expect(page.locator("[data-kind=train]")).toHaveCount(0);
  assert.deepEqual(errors, [], "无浏览器异常或 Vue key 警告");
  console.log(`LossChart browser checks passed (isolated synthetic data). Screenshots: ${output}`);
} finally {
  await browser?.close();
  await server.close();
}
