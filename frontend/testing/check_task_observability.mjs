// Isolated UI/HTTP fixture harness. Not the production backend or GPU acceptance.
import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium, expect } from "@playwright/test";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = async (name) => JSON.parse(await readFile(path.join(root, "..", "docs", name), "utf8"));
const detail = await read("examples/tasks/detail-running-progress.json");
const first = await read("examples/observability/metrics-first-page.json");
const next = await read("examples/observability/metrics-next-page.json");
const zero = await read("examples/observability/metrics-zero-loss.json");
const api = await read("api/tasks.openapi.json");
api.paths = Object.fromEntries(Object.entries(api.paths).map(([key, value]) => [`/api/v1${key}`, value]));
api.paths["/api/v1/datasets"] = { get: {} };
const A = detail.id, B = "55555555-5555-4555-8555-555555555555";
// Keep these outside Playwright's test-results cleanup when old E2E checks run.
const output = path.join(root, "..", "data", "acceptance", "b-review", "m4-04", String(Date.now()));
const history = [];
let completed = false, appended = false, logVersion = 1, delayA = false, heldResponse = null;
const status = (id) => id === A && completed ? "COMPLETED" : "RUNNING";
function metrics(id, cursor) {
  if (id === B) return cursor === 0 ? { ...zero, task_id: B } :
    { ...zero, task_id: B, items: [], next_cursor: zero.next_cursor };
  const page = cursor === 0 ? structuredClone(first) : cursor === 304 ? structuredClone(next) :
    { ...structuredClone(next), items: [], next_cursor: cursor };
  for (const point of page.items) point.total_steps = 20;
  if (cursor === 602 && appended) {
    page.items = ["train", "eval"].map((kind, index) => ({ ...first.items[index],
      total_steps: 20, kind, step: 3, loss: index ? 0.6 : 0.5, offset: cursor + index * 150 }));
    page.next_cursor = 902;
  }
  page.task_id = id;
  page.task_status = status(id);
  return page;
}
const server = await createServer({
  root,
  server: { host: "127.0.0.1", port: 15474, strictPort: true, hmr: false, ws: false },
  plugins: [{ name: "isolated-m4-observability-check", configureServer(vite) {
    vite.middlewares.use(async (req, res, nextMiddleware) => {
      const url = new URL(req.url, "http://localhost");
      const send = (data, code = 200) => {
        res.writeHead(code, { "Content-Type": "application/json" });
        res.end(JSON.stringify(data));
      };
      if (url.pathname === "/__m4_04_check__") {
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.end(await vite.transformIndexHtml(url.pathname, `<!doctype html><html lang="zh-CN">
          <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
          <link rel="icon" href="data:,"><title>M4-04 隔离浏览器检查</title>
          <div style="position:fixed;bottom:4px;right:4px;background:#fff3d6;padding:4px;z-index:99">隔离 UI 测试数据，非 GPU 证据</div>
          <div id="app"></div><script type="module" src="/src/main.js"></script></html>`));
        return;
      }
      if (!url.pathname.startsWith("/api/") && url.pathname !== "/openapi.json") return nextMiddleware();
      history.push({ path: url.pathname, query: url.search, method: req.method });
      if (url.pathname === "/openapi.json") return send(api);
      if (url.pathname.endsWith("/health")) return send({ status: "ok", service: "isolated M4 fixture server" });
      if (url.pathname.endsWith("/models")) return send([]);
      const empty = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
      if (url.pathname.endsWith("/datasets")) return send(empty);
      const task = (id) => ({ ...detail, id, status: status(id), total_steps: id === B ? 1 : 20,
        progress: completed && id === A ? 1 : 0.05 });
      if (url.pathname === "/api/v1/tasks") return send({ ...empty, items: [task(A), task(B)], total: 2, total_pages: 1 });
      const match = url.pathname.match(/^\/api\/v1\/tasks\/([^/]+)(?:\/(metrics|logs))?$/);
      if (!match) return send({ error: { code: "TASK_NOT_FOUND", message: "fixture route" } }, 404);
      const [, id, kind] = match;
      if (!kind) return send(task(id));
      if (kind === "metrics") {
        if (id === A && delayA) { heldResponse = { res, data: metrics(id, Number(url.searchParams.get("cursor"))) }; return; }
        return send(metrics(id, Number(url.searchParams.get("cursor"))));
      }
      return send({ contract_version: "1.0.0", task_id: id, task_status: status(id), source_state: "ready",
        lines: Array.from({ length: 100 }, (_, index) => `隔离测试日志 ${logVersion}-${index}: <img src=x onerror="window.__xss=true">`),
        truncated: true, tail_incomplete: !completed, filtered_lines: 2 });
    });
  } }],
});

let browser;
try {
  await mkdir(output, { recursive: true });
  await server.listen();
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:15474/__m4_04_check__#tasks");
  await page.getByRole("button", { name: "查看详情", exact: true }).first().click();
  const panel = page.locator(".task-detail");
  const capture = async (name) => {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, name), fullPage: true, animations: "disabled" });
  };
  await panel.getByRole("tab", { name: "Loss 曲线" }).click();
  await expect(panel.locator("circle")).toHaveCount(4);
  await expect(panel.locator(".detail-stats")).toContainText("0.7500");
  await capture("metrics-desktop.png");
  await panel.getByRole("tab", { name: "运行日志" }).click();
  await expect(panel).toContainText("更早的日志已省略");
  await expect(panel).toContainText("日志尾部有未完成行");
  await expect(panel).toContainText("2 条源记录被过滤或调整");
  assert.equal(await page.evaluate(() => window.__xss), undefined);
  await expect(panel.locator(".terminal img")).toHaveCount(0);
  const terminal = panel.locator(".terminal");
  await terminal.evaluate((element) => { element.scrollTop = 0; element.dispatchEvent(new Event("scroll")); });
  await expect(panel.getByRole("button", { name: "回到底部" })).toBeVisible();
  logVersion++;
  await panel.getByRole("button", { name: "刷新指标与日志" }).click();
  await expect(terminal).toContainText("隔离测试日志 2-0");
  assert.equal(await terminal.evaluate((element) => element.scrollTop), 0, "刷新不抢走历史滚动位置");
  await panel.getByRole("button", { name: "回到底部" }).click();
  await expect.poll(() => terminal.evaluate((element) => element.scrollHeight - element.clientHeight - element.scrollTop)).toBeLessThan(16);
  await capture("logs-desktop.png");
  await page.setViewportSize({ width: 390, height: 1000 });
  await capture("logs-mobile.png");
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "页面不横向溢出");

  // Simulate visibilitychange in this isolated page; the real component owns cancellation.
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  const beforeHidden = history.length;
  await page.waitForTimeout(2200);
  assert.equal(history.length, beforeHidden);
  appended = true;
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(panel.locator(".detail-stats")).toContainText("0.5000");
  await panel.getByRole("tab", { name: "Loss 曲线" }).click();
  await expect(panel.locator("circle")).toHaveCount(6);
  await capture("metrics-mobile.png");

  completed = true;
  await panel.getByRole("button", { name: "刷新任务详情", exact: true }).click();
  await expect(panel.locator("h2")).toContainText("已完成");
  await expect(panel.getByRole("button", { name: "刷新指标与日志" })).toBeEnabled();
  const observations = () => history.filter((entry) => entry.path.includes(A) && /\/(metrics|logs)$/.test(entry.path)).length;
  const afterTerminal = observations();
  await page.waitForTimeout(2300);
  assert.equal(observations(), afterTerminal, "终态最终快照取齐后停止观测周期查询");

  // Hold an old response, select another task, then release it after the switch.
  delayA = true;
  await panel.getByRole("button", { name: "刷新指标与日志" }).click();
  await expect.poll(() => Boolean(heldResponse)).toBe(true);
  await page.getByRole("button", { name: "查看详情", exact: true }).nth(1).click();
  await expect(panel.locator("p.mono")).toContainText(B);
  heldResponse.res.end(JSON.stringify(heldResponse.data));
  delayA = false;
  await expect(panel.locator(".detail-stats")).toContainText("0.0000");
  await expect(panel.locator("circle")).toHaveCount(1);
  await expect(panel).not.toContainText("INVALID_RESPONSE");
  await panel.getByRole("button", { name: "关闭任务详情" }).click();
  await expect(panel).toHaveCount(0);
  const afterClose = history.filter((entry) => entry.path.includes(B)).length;
  await page.waitForTimeout(2200);
  assert.equal(history.filter((entry) => entry.path.includes(B)).length, afterClose);
  await page.getByRole("button", { name: "查看详情", exact: true }).nth(1).click();
  await expect(panel.locator(".detail-stats")).toContainText("0.0000");
  await page.evaluate(() => { location.hash = "datasets"; });
  await expect(page.locator("h1")).toHaveText("数据集");
  const afterLeave = history.filter((entry) => /\/(metrics|logs)$/.test(entry.path)).length;
  await page.waitForTimeout(2200);
  assert.equal(history.filter((entry) => /\/(metrics|logs)$/.test(entry.path)).length, afterLeave);
  assert.equal(history.some((entry) => entry.query.includes("after_step")), false);
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({
    mode: "isolated_frontend_fixture_server", production_backend: false, gpu: false,
    mock_data: true, checks_passed: true, history,
  }, null, 2));
  console.log(`M4-04 browser checks passed (isolated fixtures): ${output}`);
} finally {
  if (heldResponse && !heldResponse.res.writableEnded) heldResponse.res.end();
  await browser?.close();
  await server.close();
}
