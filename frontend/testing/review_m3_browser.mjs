// B-side production UI review of real persisted SQL records. No mocks, new jobs or GPU.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";

const require = createRequire(new URL("../package.json", import.meta.url));
const { chromium, expect } = require("@playwright/test");
const pairs = process.argv.slice(2);
assert(pairs.length % 2 === 0, "Arguments must be --name value pairs");
const args = Object.fromEntries(pairs.reduce((result, item, index) => {
  if (index % 2 === 0) result.push([item.replace(/^--/, ""), pairs[index + 1]]);
  return result;
}, []));
assert(args.url && args.run && args.output, "--url, --run and --output are required");
const rawReport = await readFile(path.join(args.run, "report.json"));
const report = JSON.parse(rawReport);
const cases = report.cases;
const tasks = [...cases.two_serial_gpu_tasks_and_browser.tasks, cases.after_commit.task,
  cases.before_commit.after, cases.saving.task, cases.gpu_interruption_and_queued_abandonment.interrupted,
  cases.gpu_interruption_and_queued_abandonment.queued, cases.controlled_dataset_tamper, cases.isolated_missing_cache];
assert.equal(new Set(tasks.map(t => t.id)).size, 9);
await mkdir(args.output); // Existing evidence/output must never be overwritten.
const browser = await chromium.launch({ headless: true, channel: args.channel || process.env.PLAYWRIGHT_CHANNEL || undefined });
const context = await browser.newContext({ baseURL: args.url, viewport: { width: 1440, height: 1000 } });
await context.tracing.start({ screenshots: true, snapshots: true });
const page = await context.newPage();
const errors = [], requests = [], checked = [];
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => requests.push({ url: request.url(), method: request.method() }));
const detail = page.locator(".task-detail");
const result = { mode: "persisted_real_sql_cpu_review", gpu_rerun: false, new_training: false,
  report_sha256: createHash("sha256").update(rawReport).digest("hex"), mocked_routes: false };
try {
  await page.goto("/#tasks");
  await expect(page.getByRole("row")).toHaveCount(10);
  for (const [status, label, total] of [["COMPLETED", "已完成", 4], ["FAILED", "失败", 5],
    ["PENDING", "待派发", 0], ["QUEUED", "排队中", 0], ["RUNNING", "训练中", 0], ["ALL", "全部", 9]]) {
    const response = page.waitForResponse(r => {
      const url = new URL(r.url());
      return url.pathname === "/api/v1/tasks" && (status === "ALL" ? !url.searchParams.has("status") : url.searchParams.get("status") === status);
    });
    await page.getByRole("button", { name: label, exact: true }).click();
    assert.equal((await (await response).json()).total, total);
    await expect(page.getByRole("row")).toHaveCount(total ? total + 1 : 0);
    if (!total) await expect(page.locator(".pagination")).toContainText("0 / 0");
  }
  for (const task of tasks) {
    const api = await page.request.get(`/api/v1/tasks/${task.id}`);
    assert.equal(api.status(), 200);
    assert.deepEqual(await api.json(), task, "Real API differs from original evidence snapshot");
    await page.getByRole("row").filter({ hasText: task.id.slice(0, 8) }).getByRole("button", { name: "查看详情" }).click();
    await expect(detail.locator(".mono").first()).toHaveText(task.id);
    await expect.poll(async () => JSON.parse(await detail.locator(".config-snapshot").innerText())).toEqual(task.config);
    await expect(detail).toContainText(task.status === "COMPLETED" ? "已完成" : task.error_code);
    await expect(detail.getByRole("tab", { name: "Loss 曲线" })).toBeDisabled();
    await expect(detail.getByRole("tab", { name: "运行日志" })).toBeDisabled();
    await expect(detail.getByRole("button", { name: "下载 Adapter" })).toBeDisabled();
    await page.screenshot({ path: path.join(args.output, `${task.id}-desktop.png`), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.locator(".sidebar").evaluate(node => node.getBoundingClientRect().right)).toBeLessThanOrEqual(0);
    if (!checked.length) {
      await page.getByRole("button", { name: "切换导航菜单" }).click();
      await page.locator('nav[aria-label="主导航"]').getByRole("link", { name: "数据集", exact: true }).click();
      await expect(page.getByRole("heading", { name: "数据集", exact: true })).toBeVisible();
      await page.getByRole("button", { name: "切换导航菜单" }).click();
      await page.locator('nav[aria-label="主导航"]').getByRole("link", { name: /^训练任务/ }).click();
      await expect(page.getByRole("row")).toHaveCount(10);
    } else {
      await detail.getByRole("button", { name: "关闭任务详情" }).click();
    }
    await page.locator(".table-scroll").evaluate(node => { node.scrollLeft = node.scrollWidth; });
    await page.getByRole("row").filter({ hasText: task.id.slice(0, 8) }).getByRole("button", { name: "查看详情" }).click();
    await expect(detail.locator(".mono").first()).toHaveText(task.id);
    await expect.poll(async () => JSON.parse(await detail.locator(".config-snapshot").innerText())).toEqual(task.config);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Mobile page overflow");
    if (task.error_code) {
      const lines = await detail.locator(".task-failure-notice strong").evaluate(node => {
        const range = document.createRange(); range.selectNodeContents(node); return range.getClientRects().length;
      });
      assert.equal(lines, 1, "Failure code is squeezed into multiple lines on mobile");
    }
    await page.screenshot({ path: path.join(args.output, `${task.id}-mobile.png`), fullPage: true });
    checked.push({ id: task.id, status: task.status, code: task.error_code, desktop: true, mobile: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
  }
  const current = tasks.at(-1).id;
  const before = requests.filter(r => new URL(r.url).pathname === `/api/v1/tasks/${current}`).length;
  await page.waitForTimeout(2300);
  assert.equal(requests.filter(r => new URL(r.url).pathname === `/api/v1/tasks/${current}`).length, before, "Terminal detail kept polling");
  await page.reload();
  await expect(page.getByRole("row")).toHaveCount(10);
  assert(!requests.some(r => r.method !== "GET" || r.url.includes("/__test__/")), "Page used writes or test controls");
  assert.deepEqual(errors, []);
  const writeProbe = await page.request.post("/api/v1/tasks", { data: {} });
  assert.equal(writeProbe.status(), 405, "Review harness must reject mutation before production routes");
  const finalPage = await (await page.request.get("/api/v1/tasks?page=1&page_size=20")).json();
  assert.equal(finalPage.total, 9);
  Object.assign(result, { status: "passed", checked_tasks: checked, filters: 6, terminal_detail_polling: "stopped",
    page_errors: errors, page_mutations: 0, write_guard: "405", visual_review: "inspect_generated_screenshots_separately" });
  await writeFile(path.join(args.output, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify({ status: "passed", tasks: checked.length, actual_http_sql: true, gpu_rerun: false }));
} finally {
  await context.tracing.stop({ path: path.join(args.output, "trace.zip") });
  await browser.close();
}
