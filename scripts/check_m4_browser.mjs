// Production pages/HTTP only. GPU execution is arranged by check_m4_acceptance.py.
// --check launches Chromium and exits: no app, services, GPU, or passing acceptance claim.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, mkdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const root = fileURLToPath(new URL("..", import.meta.url));
const args = process.argv.slice(2);
if (args.length === 1 && args[0] === "--check") {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.setContent('<p lang="zh">LLMCloud 浏览器环境检查</p>');
    assert.equal(await page.locator("p").innerText(), "LLMCloud 浏览器环境检查");
    console.log(JSON.stringify({ status: "browser_preflight_passed", gpu_started: false }));
  } finally { await browser.close(); }
  process.exit(0);
}
assert(args.length % 2 === 0, "Expected --name value pairs");
const options = {};
for (let i = 0; i < args.length; i += 2) {
  assert(["--url", "--output", "--timeout"].includes(args[i]) && !(args[i] in options), "Unknown/duplicate option");
  options[args[i]] = args[i + 1];
}
assert(options["--url"] && options["--output"], "--url and --output are required");
const url = new URL(options["--url"]);
assert(url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname), "Only local acceptance services supported");
const output = path.resolve(options["--output"]);
const timeout = Number(options["--timeout"] ?? 600) * 1000;
assert(Number.isFinite(timeout) && timeout >= 30000 && timeout <= 3600000);
await mkdir(output, { recursive: true });
async function save(name, value) {
  await writeFile(path.join(output, `${name}.tmp`), JSON.stringify(value, null, 2) + "\n");
  await rename(path.join(output, `${name}.tmp`), path.join(output, name));
}
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ baseURL: url.href, viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
await context.tracing.start({ screenshots: true, snapshots: true });
const page = await context.newPage();
const detail = page.locator(".task-detail");
const circles = () => detail.locator('svg g[data-kind="train"] circle');
const button = () => detail.getByRole("button", { name: "下载 Adapter", exact: true });
const tasks = [], pendingReads = [], points = new Map();
const result = { status: "running", actual_services: true, mocked_routes: false,
  joint_human_acceptance: "pending", page_errors: [], requests: [], responses: [], live_ui: [], final: {} };
page.on("pageerror", error => result.page_errors.push(error.message));
page.on("request", request => result.requests.push(request.url()));
page.on("response", response => {
  const match = new URL(response.url()).pathname.match(/^\/api\/v1\/tasks\/([^/]+)\/(metrics|logs)$/);
  if (!match) return;
  const observed = Date.now();
  pendingReads.push((async () => {
    const body = await response.json();
    const record = { at_ms: observed, url: response.url(), task_id: match[1], endpoint: match[2],
      status: response.status(), request_id: response.headers()["x-request-id"],
      task_status: body.task_status, source_id: body.source_id, next_cursor: body.next_cursor,
      has_more: body.has_more, count: body.items?.length ?? body.lines?.length };
    result.responses.push(record);
    if (match[2] === "metrics" && body.items) {
      if (!points.has(match[1])) points.set(match[1], new Map());
      for (const item of body.items) points.get(match[1]).set(`${body.source_id}:${item.offset}`, item);
    }
  })().catch(error => {
    // A navigation/selection can intentionally abort a read. Preserve the fact;
    // final completed views are asserted separately, never silently accepted.
    result.responses.push({ at_ms: observed, task_id: match[1], endpoint: match[2],
      status: response.status(), aborted_or_unreadable: error.name });
  }));
});

async function task(id) {
  const response = await page.request.get(`/api/v1/tasks/${id}`);
  assert.equal(response.status(), 200);
  return response.json();
}
async function openTask(id) {
  await page.goto("/#tasks");
  const row = page.getByRole("row").filter({ hasText: id.slice(0, 8) });
  await row.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(detail).toContainText(id);
  await detail.getByRole("tab", { name: "Loss 曲线", exact: true }).click();
}
async function waitTask(id, predicate) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const state = await task(id);
    assert.notEqual(state.status, "FAILED", JSON.stringify(state));
    if (id === tasks[0] && state.status === "RUNNING") {
      result.live_ui.push({ at_ms: Date.now(), task_id: id, sql_step: state.current_step,
        visible_train_points: await circles().count(),
        displayed_loss: await detail.locator(".detail-stats > div").nth(1).locator("strong").innerText() });
      await expect(button()).toBeDisabled();
    }
    if (predicate(state)) return state;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw Error(`Actual task ${id} timed out`);
}
async function finalView(id) {
  // A full reload intentionally restores the product's default config tab.
  await detail.getByRole("tab", { name: "Loss 曲线", exact: true }).click();
  await expect(detail.locator("h2")).toContainText("已完成", { timeout: 15000 });
  const response = await page.request.get(`/api/v1/tasks/${id}/metrics?limit=200`);
  assert.equal(response.status(), 200);
  const metrics = await response.json();
  assert.equal(metrics.has_more, false); // The bounded tool permits at most 200 optimizer steps.
  const train = metrics.items.filter(item => item.kind === "train");
  assert(train.length >= 5, "At least five actual train points required");
  await expect(circles()).toHaveCount(train.length, { timeout: 15000 });
  await expect(detail.locator(".detail-stats > div").nth(1).locator("strong"))
    .toHaveText(train.at(-1).loss.toFixed(4));
  await Promise.all(pendingReads);
  const received = [...(points.get(id)?.values() ?? [])].filter(item => item.kind === "train")
    .sort((a, b) => a.step - b.step);
  assert.deepEqual(received, train, "Page cursor reads must equal the final real HTTP records");
  await page.screenshot({ path: path.join(output, `${id}-desktop.png`), fullPage: true });
  await detail.getByRole("tab", { name: "运行日志", exact: true }).click();
  await expect(detail.locator(".terminal")).toContainText("training_and_save_finished", { timeout: 15000 });
  const logs = await page.request.get(`/api/v1/tasks/${id}/logs?tail=100`);
  assert.equal(logs.status(), 200);
  assert.equal(await detail.locator(".terminal").innerText(), (await logs.json()).lines.join("\n"));
  result.final[id] = { train_points: train.length, last_loss: train.at(-1).loss,
    final_logs_match_http: true, source_id: metrics.source_id };
}
async function download(id) {
  await expect(button()).toBeEnabled();
  const downloaded = page.waitForEvent("download", { timeout: 65000 });
  await button().click();
  const file = await downloaded;
  const filename = `llmcloud-adapter-${id}.zip`;
  assert.equal(file.suggestedFilename(), filename);
  await file.saveAs(path.join(output, filename));
  assert.equal(await file.failure(), null);
}

try {
  await page.goto("/#datasets");
  await page.locator('input[type="file"]').setInputFiles({ name: "m4-engineering-draft.jsonl",
    mimeType: "application/x-ndjson", buffer: await readFile(path.join(root, "docs/examples/train.jsonl")) });
  await page.getByLabel("数据集名称").fill("M4-07 工程草稿 / 未审核 / 非效果实验");
  const uploaded = page.waitForResponse(response => response.request().method() === "POST" &&
    new URL(response.url()).pathname === "/api/v1/datasets");
  await page.getByRole("button", { name: "上传并校验", exact: true }).click();
  const datasetResponse = await uploaded;
  assert.equal(datasetResponse.status(), 201);
  result.dataset_id = (await datasetResponse.json()).id;
  await page.goto("/#training");
  await expect(page.locator("#training-dataset")).toBeEnabled();
  await page.locator("#training-dataset").selectOption(result.dataset_id);
  for (const [field, value] of Object.entries({ gradient_accumulation_steps: "1", max_seq_length: "256", logging_steps: "1" }))
    await page.locator(`#${field}`).fill(value);
  result.submissions = [];
  for (let index = 0; index < 2; index++) {
    if (index) await page.getByRole("button", { name: "准备新的训练任务", exact: true }).click();
    const accepted = page.waitForResponse(response => response.request().method() === "POST" &&
      new URL(response.url()).pathname === "/api/v1/tasks");
    await page.getByRole("button", { name: "提交训练任务", exact: true }).click();
    const response = await accepted;
    assert.equal(response.status(), 202);
    const state = await response.json();
    tasks.push(state.id);
    result.submissions.push({ task_id: state.id, request_id: response.headers()["x-request-id"],
      key: response.request().headers()["idempotency-key"], body: response.request().postDataJSON() });
  }
  assert.notEqual(tasks[0], tasks[1]);
  assert.notEqual(result.submissions[0].key, result.submissions[1].key);
  result.task_ids = tasks;
  await save("submitted.json", { task_ids: tasks, dataset_id: result.dataset_id, submissions: result.submissions });
  await openTask(tasks[0]);
  await expect(button()).toBeDisabled();
  await save("observing.json", { task_id: tasks[0] });
  // The production worker is now started by Python; no injected timing/events.
  await waitTask(tasks[0], state => state.status === "COMPLETED");
  await finalView(tasks[0]);
  await waitTask(tasks[1], state => {
    assert.notEqual(state.status, "COMPLETED", "Second task finished too quickly; increase real max_steps");
    return state.status === "RUNNING" && state.current_step >= 2;
  });
  const start = new Date().toISOString();
  await download(tasks[0]);
  result.download_during_training = { task_id: tasks[0], running_task_id: tasks[1],
    started_at: start, finished_at: new Date().toISOString(), running_after_download: (await task(tasks[1])).status };
  assert.equal(result.download_during_training.running_after_download, "RUNNING");
  await save("downloaded-first.json", result.download_during_training);
  await waitTask(tasks[1], state => state.status === "COMPLETED");
  await openTask(tasks[1]);
  await page.reload();
  await expect(detail).toContainText(tasks[1], { timeout: 15000 });
  await finalView(tasks[1]);
  await download(tasks[1]); // Reacquires the download slot after the first response cleanup.
  await detail.getByRole("tab", { name: "Loss 曲线", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().right))
    .toBeLessThanOrEqual(0);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Mobile page overflow");
  await expect(circles()).toHaveCount(result.final[tasks[1]].train_points);
  await page.screenshot({ path: path.join(output, "mobile-metrics.png"), fullPage: true });
  await detail.getByRole("tab", { name: "运行日志", exact: true }).click();
  await page.screenshot({ path: path.join(output, "mobile-logs.png"), fullPage: true });
  await Promise.all(pendingReads);
  assert.deepEqual(result.page_errors, []);
  assert(!result.requests.some(request => request.includes("/__test__/")), "Test control route used");
  result.status = "browser_checks_passed";
} catch (error) {
  result.status = "failed";
  result.error = { name: error.name, message: error.message };
  throw error;
} finally {
  try {
    await Promise.all(pendingReads);
    await save("result.json", result);
    await context.tracing.stop({ path: path.join(output, "trace.zip") });
  } finally { await browser.close(); }
}
