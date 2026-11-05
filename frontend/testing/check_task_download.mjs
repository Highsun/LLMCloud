// Independent HTTP fixture server for the real Vue download UI. No GPU/backend audit.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium, expect } from "@playwright/test";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = async (name) => JSON.parse(await readFile(path.join(root, "..", "docs", name), "utf8"));
const detail = await read("examples/tasks/detail-running-progress.json");
const metrics = await read("examples/observability/metrics-first-page.json");
const last = await read("examples/observability/metrics-next-page.json");
const log = await read("examples/observability/logs-ready.json");
const api = await read("api/tasks.openapi.json");
api.paths = Object.fromEntries(Object.entries(api.paths).map(([key, value]) => [`/api/v1${key}`, value]));
api.paths["/api/v1/datasets"] = { get: {} };
const A = detail.id, B = "55555555-5555-4555-8555-555555555555", C = "66666666-6666-4666-8666-666666666666";
// Deterministic valid ZIP_STORED, generated with Python zipfile: fixture.txt, no trained artifacts.
const zip = Buffer.from("UEsDBBQAAAAAAAAAZV3f5srbLwAAAC8AAAALAAAAZml4dHVyZS50eHRJc29sYXRlZCBkb3dubG9hZCB0ZXN0IG9ubHkuIE5vIG1vZGVsIHdlaWdodHMuClBLAQIUABQAAAAAAAAAZV3f5srbLwAAAC8AAAALAAAAAAAAAAAAAACAAQAAAABmaXh0dXJlLnR4dFBLBQYAAAAAAQABADkAAABYAAAAAAA=", "base64");
const output = path.join(root, "..", "data", "acceptance", "b-review", "m4-05", String(Date.now()));
const requests = [], held = [];
let mode = "zip", closed = 0;
const status = (id) => id === C ? "RUNNING" : "COMPLETED";
const server = await createServer({ root,
  server: { host: "127.0.0.1", port: 15475, strictPort: true, hmr: false, ws: false },
  plugins: [{ name: "isolated-download-check", configureServer(vite) {
    vite.middlewares.use(async (req, res, nextMiddleware) => {
      const url = new URL(req.url, "http://localhost");
      const send = (data, code = 200, extra = {}) => {
        res.writeHead(code, { "Content-Type": "application/json", ...extra }); res.end(JSON.stringify(data));
      };
      if (url.pathname === "/__m4_05_check__") {
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        return res.end(await vite.transformIndexHtml(url.pathname, `<!doctype html><html lang="zh-CN"><meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,">
          <div style="position:fixed;bottom:4px;right:4px;background:#fff3d6;padding:4px;z-index:99">隔离下载测试，非训练产物</div>
          <div id="app"></div><script type="module" src="/src/main.js"></script></html>`));
      }
      if (!url.pathname.startsWith("/api/") && url.pathname !== "/openapi.json") return nextMiddleware();
      if (url.pathname === "/openapi.json") return send(api);
      if (url.pathname.endsWith("/health")) return send({ status: "ok", service: "isolated download fixture server" });
      if (url.pathname.endsWith("/models")) return send([]);
      const empty = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
      if (url.pathname.endsWith("/datasets")) return send(empty);
      const task = (id) => ({ ...detail, id, status: status(id), current_step: 2, total_steps: 2, progress: 1 });
      if (url.pathname === "/api/v1/tasks") return send({ ...empty, items: [task(A), task(B), task(C)], total: 3, total_pages: 1 });
      const match = url.pathname.match(/^\/api\/v1\/tasks\/([^/]+)(?:\/(metrics|logs|adapter))?$/);
      if (!match) return send({}, 404);
      const [, id, kind] = match;
      if (!kind) return send(task(id));
      if (kind === "logs") return send({ ...log, task_id: id, task_status: status(id) });
      if (kind === "metrics") {
        const cursor = Number(url.searchParams.get("cursor"));
        const page = cursor === 0 ? metrics : cursor === 304 ? last : { ...last, items: [], next_cursor: cursor };
        return send({ ...page, task_id: id, task_status: status(id) });
      }
      requests.push({ id, mode, method: req.method, query: url.search });
      if (mode === "busy") return send({ error: { code: "DOWNLOAD_BUSY", message: "隔离测试：下载服务忙", request_id: "fixture-busy-request" } }, 429, { "Retry-After": "2" });
      if (mode === "json") return send({ error: { code: "INVALID_ARTIFACT", message: "incorrect 200 JSON" } }, 200, { "X-Request-ID": "fixture-wrong-mime" });
      if (mode === "html") { res.writeHead(200, { "Content-Type": "text/html" }); return res.end("<html>not a zip</html>"); }
      if (mode === "slowheaders" || mode === "slowbody") {
        res.on("close", () => { closed++; });
        if (mode === "slowbody") {
          res.writeHead(200, { "Content-Type": "application/zip", "Content-Length": zip.length });
          res.write(zip.subarray(0, 4)); // Headers and some bytes arrive; body deliberately remains pending.
        }
        held.push({ res, mode, id }); return;
      }
      res.writeHead(200, { "Content-Type": "application/zip", "Content-Length": zip.length,
        "Content-Disposition": 'attachment; filename="server-provided-name.zip"' });
      res.end(zip);
    });
  } }],
});

let browser;
try {
  await mkdir(output, { recursive: true });
  await server.listen();
  browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [], downloads = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("download", (download) => downloads.push(download.suggestedFilename()));
  await page.goto("http://127.0.0.1:15475/__m4_05_check__#tasks");
  const panel = page.locator(".task-detail");
  const open = async (index) => {
    await page.getByRole("button", { name: "查看详情", exact: true }).nth(index).click();
    await expect(panel.locator("h2")).toContainText(index === 2 ? "训练中" : "已完成");
  };
  const button = () => panel.getByRole("button", { name: "下载 Adapter", exact: true });
  await open(2);
  await expect(panel).toContainText("100% · 等待产物校验与状态提交");
  await expect(button()).toBeDisabled();
  await open(0);
  const getFile = async (id, name) => {
    const pending = page.waitForEvent("download", { timeout: 10000 });
    await button().click();
    let download;
    try { download = await pending; }
    catch (error) {
      await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true });
      console.log(JSON.stringify({ requests, panel: await panel.innerText(), errors }));
      throw error;
    }
    assert.equal(download.suggestedFilename(), `llmcloud-adapter-${id}.zip`);
    const target = path.join(output, name);
    await download.saveAs(target);
    assert.deepEqual(await readFile(target), zip);
  };
  await getFile(A, "task-a-fixture.zip");
  await expect(panel).toContainText("下载已交给浏览器保存");
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, "success-desktop.png"), fullPage: true, animations: "disabled" });
  mode = "json";
  await button().click();
  await expect(panel.getByRole("alert")).toContainText("未保存该响应");
  await expect(panel).toContainText("fixture-wrong-mime");
  mode = "html";
  await button().click();
  await expect(panel.getByRole("alert")).toContainText("未保存该响应");
  mode = "busy";
  await button().click();
  await expect(panel).toContainText("2 秒后手动重试");
  await expect(panel).toContainText("fixture-busy-request");
  const busyCount = requests.length;
  await page.waitForTimeout(2200);
  assert.equal(requests.length, busyCount, "忙时没有自动重试下载");
  await page.setViewportSize({ width: 390, height: 1000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, "busy-mobile.png"), fullPage: true, animations: "disabled" });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

  for (const delay of ["slowheaders", "slowbody"]) {
    mode = delay;
    const before = held.length, beforeClosed = closed;
    await button().click();
    await expect.poll(() => held.length).toBe(before + 1);
    await expect(panel.getByRole("button", { name: "正在下载…" })).toBeDisabled();
    await expect(panel.getByRole("button", { name: "取消下载" })).toBeVisible();
    if (delay === "slowbody") {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(output, "downloading-mobile.png"), fullPage: true, animations: "disabled" });
    }
    await panel.getByRole("button", { name: "取消下载" }).click();
    await expect(panel).toContainText("下载已取消");
    await expect(button()).toBeEnabled();
    await expect.poll(() => closed).toBeGreaterThan(beforeClosed);
  }
  assert.equal(downloads.length, 1, "错误体和取消均没有生成文件");

  mode = "slowbody";
  const oldCount = held.length;
  await button().click();
  await expect.poll(() => held.length).toBe(oldCount + 1);
  await open(1);
  await expect(button()).toBeEnabled();
  await expect(panel).not.toContainText("fixture-busy-request");
  mode = "zip";
  await getFile(B, "task-b-fixture.zip");
  assert.equal(downloads.length, 2);
  assert.equal(downloads.at(-1), `llmcloud-adapter-${B}.zip`);

  // Fast-forward only the browser clock; actual HTTP cancellation is still observed by the server.
  await page.clock.install();
  mode = "slowbody";
  const beforeTimeout = held.length, beforeClosed = closed;
  await button().click();
  await expect.poll(() => held.length).toBe(beforeTimeout + 1);
  await page.clock.fastForward(61000);
  await expect(panel.getByRole("alert")).toContainText("下载超时");
  await expect(button()).toBeEnabled();
  await expect.poll(() => closed).toBeGreaterThan(beforeClosed);
  assert.equal(downloads.length, 2);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, "timeout-mobile.png"), fullPage: true, animations: "disabled" });
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ mode: "isolated_http_download_fixture",
    production_backend: false, gpu: false, trained_artifacts: false, mock_data: true, passed: true,
    zip_sha256: createHash("sha256").update(zip).digest("hex"), downloads, requests, observed_disconnects: closed,
  }, null, 2));
  console.log(`M4-05 browser checks passed (synthetic ZIP): ${output}`);
} finally {
  for (const item of held) if (!item.res.writableEnded) item.res.end();
  await browser?.close();
  await server.close();
}
