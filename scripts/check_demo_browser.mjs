// Real local services only. New account, upload, training, download and compare.
// Video/screenshots/answers/ZIP remain in the caller's E-backed output directory.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { randomBytes } from "node:crypto";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const options = {};
for (let index = 2; index < process.argv.length; index += 2) {
  assert(["--url", "--output"].includes(process.argv[index]), "Unknown option");
  options[process.argv[index]] = process.argv[index + 1];
}
const url = new URL(options["--url"]);
assert(url.protocol === "http:" && ["127.0.0.1", "localhost"].includes(url.hostname), "Local restricted deployment only");
const output = path.resolve(options["--output"]);
await mkdir(output, { recursive: false });
const report = { status: "running", actual_services: true, mocked_routes: false,
  scope: "new account real browser/GPU engineering demo, not E01 or cloud", started_at: new Date().toISOString() };
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined, slowMo: 100 });
const context = await browser.newContext({ baseURL: url.href, viewport: { width: 1440, height: 1000 },
  acceptDownloads: true, recordVideo: { dir: output, size: { width: 1440, height: 1000 } } });
const page = await context.newPage();
const failures = [];
page.on("pageerror", error => failures.push(error.message));
const screenshot = name => page.screenshot({ path: path.join(output, name + ".png"), fullPage: true });
try {
  await page.goto("/#datasets");
  await expect(page.getByRole("heading", { name: "登录工作空间" })).toBeVisible();
  await page.getByRole("button", { name: "没有账户？注册" }).click();
  await page.getByLabel("用户名", { exact: true }).fill("demo_" + randomBytes(6).toString("hex"));
  await page.getByLabel("密码", { exact: true }).fill(randomBytes(24).toString("base64url"));
  await page.getByRole("button", { name: "注册并登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "数据集", exact: true })).toBeVisible({ timeout: 15000 });
  const me = await page.request.get("/api/v1/auth/me");
  assert.equal(me.status(), 200); report.account_id = (await me.json()).id;
  const example = await readFile(new URL("../docs/examples/train.jsonl", import.meta.url));
  await page.locator('input[type="file"]').setInputFiles({ name: "demo-engineering.jsonl", mimeType: "application/x-ndjson", buffer: example });
  await page.getByLabel("数据集名称").fill("课程演示工程样例（非 E01）");
  const uploaded = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/datasets");
  await page.getByRole("button", { name: "上传并校验", exact: true }).click();
  const upload = await uploaded; assert.equal(upload.status(), 201);
  report.dataset_id = (await upload.json()).id;
  await screenshot("01-upload");
  await page.goto("/#training");
  await page.locator("#training-dataset").selectOption(report.dataset_id);
  for (const [field, value] of Object.entries({ gradient_accumulation_steps: "1", max_seq_length: "128", logging_steps: "1" }))
    await page.locator(`#${field}`).fill(value);
  const accepted = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/tasks");
  await page.getByRole("button", { name: "提交训练任务", exact: true }).click();
  const submitted = await accepted; assert.equal(submitted.status(), 202);
  report.task_id = (await submitted.json()).id;
  await page.goto("/#tasks");
  const row = page.getByRole("row").filter({ hasText: report.task_id.slice(0, 8) });
  await row.getByRole("button", { name: "查看详情", exact: true }).click();
  const detail = page.locator(".task-detail");
  await detail.getByRole("tab", { name: "Loss 曲线", exact: true }).click();
  await expect.poll(async () => {
    const response = await page.request.get(`/api/v1/tasks/${report.task_id}`);
    assert.equal(response.status(), 200);
    const state = await response.json();
    assert.notEqual(state.status, "FAILED", JSON.stringify(state));
    report.task_status = state.status; report.training_summary = state.training_summary;
    return state.status;
  }, { timeout: 360000, intervals: [1000] }).toBe("COMPLETED");
  await expect(detail.locator('svg g[data-kind="train"] circle')).not.toHaveCount(0, { timeout: 15000 });
  report.visible_train_points = await detail.locator('svg g[data-kind="train"] circle').count();
  await screenshot("02-real-loss");
  await detail.getByRole("tab", { name: "运行日志", exact: true }).click();
  await expect(detail.locator(".terminal")).toContainText("training_and_save_finished", { timeout: 15000 });
  await screenshot("03-real-logs");
  const download = page.waitForEvent("download", { timeout: 65000 });
  await detail.getByRole("button", { name: "下载 Adapter", exact: true }).click();
  const zip = await download; assert.equal(await zip.failure(), null);
  await zip.saveAs(path.join(output, `llmcloud-adapter-${report.task_id}.zip`));
  report.download_filename = zip.suggestedFilename();
  await page.goto("/#inference");
  await page.locator("#inference-task").selectOption(report.task_id);
  await page.locator("#prompt").fill("请简洁解释什么是云计算。");
  await page.locator('input[type="number"]').fill("64");
  const generated = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/inference", { timeout: 110000 });
  await page.getByRole("button", { name: "生成回答", exact: true }).click();
  const response = await generated; assert.equal(response.status(), 200);
  const answer = await response.json();
  assert.equal(answer.task_id, report.task_id); assert(answer.base && answer.adapter);
  await expect(page.locator('[data-answer="base"] .model-output')).toBeVisible();
  await expect(page.locator('[data-answer="adapter"] .model-output')).toBeVisible();
  report.inference = { http_status: 200, request_id: response.headers()["x-request-id"],
    base_tokens: answer.base.generated_tokens, adapter_tokens: answer.adapter.generated_tokens };
  await screenshot("04-real-compare");
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await screenshot("05-narrow-compare");
  report.narrow_width = 390;
  assert.deepEqual(failures, []);
  report.status = "passed_for_local_real_demo";
} catch (error) {
  report.status = "failed"; report.failure = error.message;
  await screenshot("failed").catch(() => {});
  throw error;
} finally {
  report.finished_at = new Date().toISOString();
  await context.close();
  report.video = await page.video()?.path();
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2) + "\n");
  await browser.close();
}
