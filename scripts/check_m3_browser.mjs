// Actual Vite/API/Redis/Worker/GPU acceptance. No route interception or test controls.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => {
  if (index % 2 === 0) pairs.push([value.replace(/^--/, ""), all[index + 1]]);
  return pairs;
}, []));
assert(args.url && args.output, "--url and --output are required");
const root = fileURLToPath(new URL("..", import.meta.url));
await mkdir(args.output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ baseURL: args.url, viewport: { width: 1440, height: 1000 } });
await context.tracing.start({ screenshots: true, snapshots: true });
const page = await context.newPage();
const errors = [], requests = [], result = { actual_services: true, mocked_routes: false, task_ids: [] };
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => requests.push(request.url()));
const detail = page.locator(".task-detail");
try {
  if (args.task) {
    await page.goto("/#tasks");
    const row = page.getByRole("row").filter({ hasText: args.task.slice(0, 8) });
    await expect(row).toBeVisible({ timeout: 15000 });
    await row.getByRole("button", { name: "查看详情" }).click();
    await expect(detail.locator(".config-snapshot")).toContainText("lora_r");
    const response = await page.request.get(`/api/v1/tasks/${args.task}`);
    assert.equal(response.status(), 200);
    const task = await response.json();
    assert.equal(task.status, args.status);
    if (args.code) await expect(detail).toContainText(args.code);
    else await expect(detail).toContainText("已完成");
    result.task_ids.push(task.id);
    result.status = task.status;
  } else {
    await page.goto("/#datasets");
    await page.locator('input[type="file"]').setInputFiles({ name: "m3-engineering-draft.jsonl",
      mimeType: "application/x-ndjson", buffer: await readFile(path.join(root, "docs/examples/train.jsonl")) });
    await page.getByLabel("数据集名称").fill("M3-07 工程草稿 / 非效果实验");
    const upload = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/api/v1/datasets"));
    await page.getByRole("button", { name: "上传并校验", exact: true }).click();
    const uploaded = await upload;
    assert.equal(uploaded.status(), 201);
    const dataset = await uploaded.json();
    result.dataset_id = dataset.id;
    await page.goto("/#training");
    await expect(page.locator("#training-dataset")).toBeEnabled();
    await page.locator("#training-dataset").selectOption(dataset.id);
    for (const [field, value] of Object.entries({ gradient_accumulation_steps: "1", max_seq_length: "256", logging_steps: "1" }))
      await page.locator(`#${field}`).fill(value);
    result.submissions = [];
    for (let index = 0; index < 2; index++) {
      if (index) await page.getByRole("button", { name: "准备新的训练任务", exact: true }).click();
      const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/api/v1/tasks"));
      await page.getByRole("button", { name: "提交训练任务", exact: true }).click();
      const accepted = await response;
      assert.equal(accepted.status(), 202);
      const task = await accepted.json();
      result.task_ids.push(task.id);
      result.submissions.push({ id: task.id, body: accepted.request().postDataJSON(),
        key: accepted.request().headers()["idempotency-key"] });
    }
    assert.notEqual(result.submissions[0].key, result.submissions[1].key);
    await writeFile(path.join(args.output, "submitted.json"), JSON.stringify(result, null, 2));
    await page.getByRole("link", { name: "查看原任务", exact: true }).click();
    const observations = [], deadline = Date.now() + 240000;
    while (Date.now() < deadline) {
      const tasks = await Promise.all(result.task_ids.map(async id => {
        const response = await page.request.get(`/api/v1/tasks/${id}`);
        assert.equal(response.status(), 200);
        return response.json();
      }));
      assert(tasks.filter(task => task.status === "RUNNING").length <= 1, "Two tasks RUNNING concurrently");
      observations.push(tasks.map(({ id, status, current_step, total_steps }) => ({ id, status, current_step, total_steps })));
      assert(!tasks.some(task => task.status === "FAILED"), JSON.stringify(tasks));
      if (tasks.every(task => task.status === "COMPLETED")) { result.tasks = tasks; break; }
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    assert(result.tasks, "GPU task completion timed out");
    result.observations = observations;
    await expect(detail).toContainText("已完成", { timeout: 15000 });
    await expect(detail).toContainText("2 / 2");
    await expect(detail.locator(".config-snapshot")).toContainText('"gradient_accumulation_steps": 1');
    result.status = "COMPLETED";
  }
  await expect(detail.getByRole("tab", { name: "Loss 曲线" })).toBeDisabled();
  await expect(detail.getByRole("tab", { name: "运行日志" })).toBeDisabled();
  await expect(detail.getByRole("button", { name: "下载 Adapter" })).toBeDisabled();
  await page.screenshot({ path: path.join(args.output, "desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Mobile overflow");
  await page.screenshot({ path: path.join(args.output, "mobile.png"), fullPage: true });
  assert.deepEqual(errors, []);
  assert(!requests.some(url => url.includes("/__test__/")), "Test control route used");
  await writeFile(path.join(args.output, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ status: "ok", task_ids: result.task_ids, actual_services: true }));
} finally {
  await context.tracing.stop({ path: path.join(args.output, "trace.zip") });
  await browser.close();
}
