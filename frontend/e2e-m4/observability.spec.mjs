import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";

// No page.route, response fixtures or fake observability endpoints. Real production
// API + SQLite + Linux file reader + ZIP service. Only execution inputs are CPU doubles.
const api = process.env.LLMCLOUD_M4_TEST_API || "http://127.0.0.1:18006";
const panel = (page) => page.locator(".task-detail");
const circles = (page, kind = "train") => panel(page).locator(`svg g[data-kind="${kind}"] circle`);
const downloadButton = (page) => panel(page).getByRole("button", { name: "下载 Adapter", exact: true });

async function control(request, id, mode, extra = {}) {
  const response = await request.post(`${api}/__test__/tasks/${id}`, { data: { mode, ...extra } });
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}
async function createTask(request, publishMode = "accepted") {
  expect((await request.post(`${api}/__test__/publisher`, { data: { mode: publishMode } })).status()).toBe(200);
  const uploaded = await request.post(`${api}/api/v1/datasets`, { multipart: {
    file: { name: "m4-cpu-fixture.jsonl", mimeType: "application/x-ndjson",
      buffer: Buffer.from('{"instruction":"CPU test fixture","output":"not training evidence"}\n') },
    name: `M4-06-${randomUUID()}`,
  } });
  expect(uploaded.status()).toBe(201);
  const response = await request.post(`${api}/api/v1/tasks`, { data: {
    dataset_id: (await uploaded.json()).id, config: { lora_r: 1, target_modules: ["q_proj"] },
  } });
  expect(response.status(), await response.text()).toBe(publishMode === "accepted" ? 202 : 503);
  const body = await response.json();
  return body.id ?? body.error.task_id;
}
async function openTask(page, id) {
  await page.goto("/#tasks");
  const row = page.locator("tr").filter({ has: page.locator(`button`, { hasText: "查看详情" }) }).filter({ hasText: id.slice(0, 8) });
  await row.getByRole("button", { name: "查看详情", exact: true }).click();
  await expect(panel(page)).toContainText(id);
  await expect(panel(page).getByRole("button", { name: "刷新任务详情", exact: true })).toBeEnabled();
}
async function refresh(page) {
  const button = panel(page).getByRole("button", { name: "刷新指标与日志", exact: true });
  await expect(button).toBeEnabled();
  await button.click();
  await expect(button).toBeEnabled();
}
async function metricsTab(page) { await panel(page).getByRole("tab", { name: "Loss 曲线", exact: true }).click(); }
async function logsTab(page) { await panel(page).getByRole("tab", { name: "运行日志", exact: true }).click(); }
async function errorResponse(request, path, status, code) {
  const response = await request.get(`${api}/api/v1${path}`);
  expect(response.status()).toBe(status);
  const body = await response.json();
  expect(body.error.code).toBe(code);
  expect(body.error.request_id).toBe(response.headers()["x-request-id"]);
  return response;
}
async function uiError(page, id, kind, code, action) {
  const pending = page.waitForResponse((r) => r.url().includes(`/tasks/${id}/${kind}`) && r.status() >= 400);
  await action();
  const response = await pending, { error } = await response.json();
  expect(error.code).toBe(code);
  expect(error.request_id).toBe(response.headers()["x-request-id"]);
  await expect(panel(page).getByRole("alert").filter({ hasText: error.message })).toBeVisible();
  await expect(panel(page)).toContainText(error.request_id);
}

test.beforeEach(async ({ page, request }, info) => {
  const state = await (await request.get(`${api}/__test__/state`)).json();
  expect(state.gpu).toBe(false);
  expect(state.training_imports).toEqual([]);
  const errors = [], observations = [], responses = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (!/\/api\/v1\/tasks\/[^/]+\/(metrics|logs|adapter)/.test(response.url())) return;
    responses.push((async () => {
      const record = { url: response.url(), status: response.status(), request_id: response.headers()["x-request-id"] };
      if (response.headers()["content-type"]?.includes("json")) {
        const body = await response.json();
        Object.assign(record, body.error ? { code: body.error.code } : {
          task_status: body.task_status, source_id: body.source_id, next_cursor: body.next_cursor,
          count: body.items?.length ?? body.lines?.length, has_more: body.has_more, tail_incomplete: body.tail_incomplete,
        });
      }
      observations.push(record);
    })().catch(() => {})); // A deliberately aborted body need not parse as JSON.
  });
  info.m4 = { errors, observations, responses };
});
test.afterEach(async ({ request }, info) => {
  await Promise.all(info.m4.responses);
  await info.attach("real-http-observations.json", { body: JSON.stringify({
    scope: "M4-06 real Linux HTTP/SQL/files, synthetic CPU events/bundles; no GPU", ...info.m4,
    responses: undefined,
  }, null, 2), contentType: "application/json" });
  expect(info.m4.errors).toEqual([]);
  expect((await (await request.get(`${api}/__test__/state`)).json()).training_imports).toEqual([]);
});

test("真实文件增量、跨轮分页、同 step 双系列和零值；终态补齐后停止读取", async ({ page, request }, info) => {
  const id = await createTask(request);
  await control(request, id, "start");
  await openTask(page, id);
  await metricsTab(page);
  await expect(panel(page)).toContainText("暂无 Loss 记录");
  await page.getByRole("checkbox", { name: "每 2 秒刷新" }).uncheck();
  // 1002 records exceed the UI's five-page (1000-record) round budget.
  // Freeze UI polling while preparing the backlog, so CPU speed cannot turn
  // the pagination scenario into many smaller ordinary incremental reads.
  await control(request, id, "append", { count: 501, total: 600, both: true });
  await refresh(page);
  await expect(circles(page)).toHaveCount(500);
  await expect(circles(page, "eval")).toHaveCount(500);
  await expect(panel(page)).toContainText("仍有历史指标待补拉");
  await refresh(page);
  await expect(circles(page)).toHaveCount(501, { timeout: 15_000 });
  await expect(circles(page, "eval")).toHaveCount(501);
  await Promise.all(info.m4.responses);
  const reads = info.m4.observations.filter((r) => r.url.includes("/metrics?") && r.source_id);
  expect(reads.some((r) => r.count === 200 && r.has_more)).toBe(true);
  expect(new Set(reads.map((r) => r.source_id)).size).toBe(1);
  expect(reads.some((r) => r.url.includes("cursor=") && !r.url.includes("cursor=0&"))).toBe(true);
  await page.getByRole("checkbox", { name: "每 2 秒刷新" }).check();
  await control(request, id, "append", { count: 99, total: 600, both: true });
  await control(request, id, "complete", { total: 600 });
  await expect(panel(page).locator("h2")).toContainText("已完成", { timeout: 10_000 });
  await expect(circles(page)).toHaveCount(600);
  await expect(circles(page, "eval")).toHaveCount(600);
  await expect(panel(page).locator(".detail-stats")).toContainText("0.0000");
  await logsTab(page);
  await expect(panel(page).locator(".terminal")).toContainText('"completed_steps":600');
  await expect(panel(page).locator(".terminal")).toContainText("training_and_save_finished");
  await expect.poll(() => info.m4.observations.at(-1)?.task_status).toBe("COMPLETED");
  const count = info.m4.observations.length;
  await page.waitForTimeout(2600); // Observe one real 2-second polling interval after final drain.
  expect(info.m4.observations.length).toBe(count);
  expect(info.m4.observations.every((r) => !r.url.includes("after_step"))).toBe(true);
  await metricsTab(page);
  await page.screenshot({ path: info.outputPath("real-files-terminal-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator(".sidebar").evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("real-files-terminal-mobile.png"), fullPage: true });
});

test("真实半行补全、来源替换触发 409 重置；坏完整行报错且保留 FAILED 已读点", async ({ page, request }) => {
  const id = await createTask(request);
  await control(request, id, "append", { total: 3 });
  await control(request, id, "partial", { total: 3 });
  await openTask(page, id);
  await metricsTab(page);
  await expect(circles(page)).toHaveCount(1);
  await expect(panel(page)).toContainText("指标尾部存在未完成行");
  await control(request, id, "finish_partial");
  await refresh(page);
  await expect(circles(page)).toHaveCount(2);
  await expect(panel(page)).not.toContainText("指标尾部存在未完成行");
  await control(request, id, "replace");
  const reset = page.waitForResponse((r) => r.url().includes(`/tasks/${id}/metrics?`) && r.status() === 409);
  await refresh(page);
  await reset;
  await expect(panel(page)).toContainText("指标来源或游标已变化");
  await expect(circles(page)).toHaveCount(2);
  await control(request, id, "corrupt");
  await control(request, id, "fail");
  await uiError(page, id, "metrics", "METRICS_CORRUPTED", () => refresh(page));
  await expect(circles(page)).toHaveCount(2);
  await expect(panel(page).locator("h2")).toContainText("失败");
  await expect(panel(page)).toContainText("TRAINING_FAILED");
  await expect(downloadButton(page)).toBeDisabled();
});

test("真实日志尾部三类提示与安全过滤；缺文件/符号链接报错，旧快照保留", async ({ page, request }, info) => {
  const id = await createTask(request);
  await control(request, id, "start");
  await openTask(page, id);
  await logsTab(page);
  await expect(panel(page).locator(".terminal")).toContainText("尚未产生日志");
  await control(request, id, "logs");
  await refresh(page);
  for (const text of ["更早的日志已省略", "日志尾部有未完成行", "源记录被过滤或调整"]) await expect(panel(page)).toContainText(text);
  const log = panel(page).locator(".terminal");
  await expect(log).toContainText('"stage":"saving"');
  expect(await log.textContent()).not.toContain("private-path");
  expect(await log.textContent()).not.toContain("<img");
  await expect(log.locator("img")).toHaveCount(0);
  await page.screenshot({ path: info.outputPath("real-log-projection.png"), fullPage: true });
  await control(request, id, "log_missing");
  await uiError(page, id, "logs", "LOGS_UNAVAILABLE", () => refresh(page));
  await expect(log).toContainText('"stage":"saving"');
  await control(request, id, "log_link");
  await uiError(page, id, "logs", "LOGS_UNAVAILABLE", () => refresh(page));
  await expect(log).not.toContainText("private-path");
  await control(request, id, "log_missing");
});

test("真实 ZIP 浏览器落盘、CRC/解压后原审计及清理；五状态下载门禁与运行时 OpenAPI", async ({ page, request }, info) => {
  const id = await createTask(request);
  await errorResponse(request, `/tasks/${id}/adapter`, 409, "ARTIFACT_NOT_READY"); // QUEUED
  await control(request, id, "start");
  await errorResponse(request, `/tasks/${id}/adapter`, 409, "ARTIFACT_NOT_READY"); // RUNNING
  await control(request, id, "bundle");
  await openTask(page, id);
  const waiting = page.waitForEvent("download");
  await downloadButton(page).click();
  const download = await waiting;
  expect(download.suggestedFilename()).toBe(`llmcloud-adapter-${id}.zip`);
  const saved = info.outputPath(download.suggestedFilename());
  await download.saveAs(saved);
  const bytes = await readFile(saved);
  const audit = await request.post(`${api}/__test__/audit/${id}`, { data: bytes, headers: { "Content-Type": "application/zip" } });
  expect(audit.status(), await audit.text()).toBe(200);
  expect(await audit.json()).toMatchObject({ sha256: createHash("sha256").update(bytes).digest("hex"), metric_count: 2, crc: "passed", shared_audit: "passed" });
  await info.attach("download-audit.json", { body: JSON.stringify(await audit.json()), contentType: "application/json" });
  await expect.poll(async () => (await (await request.get(`${api}/__test__/state`)).json()).temporary_entries).toBe(0);
  const direct = await request.get(`${api}/api/v1/tasks/${id}/adapter`, { headers: { Origin: "http://localhost:5173" } });
  expect(direct.headers()["content-type"]).toBe("application/zip");
  expect(direct.headers()["content-disposition"]).toContain(download.suggestedFilename());
  expect(direct.headers()["cache-control"]).toBe("no-store");
  expect(direct.headers()["access-control-expose-headers"]).toContain("Content-Disposition");
  expect(Number(direct.headers()["content-length"])).toBe((await direct.body()).length);
  await errorResponse(request, `/tasks/${id}/adapter?path=anything`, 422, "VALIDATION_ERROR");
  await errorResponse(request, `/tasks/${randomUUID()}/adapter`, 404, "TASK_NOT_FOUND");
  const paths = (await (await request.get(`${api}/openapi.json`)).json()).paths;
  expect(paths["/api/v1/tasks/{task_id}/adapter"].get.responses["200"].content["application/zip"].schema.format).toBe("binary");
  for (const kind of ["metrics", "logs"]) expect(paths[`/api/v1/tasks/{task_id}/${kind}`]).toBeTruthy();
  await page.screenshot({ path: info.outputPath("real-download-completed.png"), fullPage: true });
  // Pending and dispatch-failed rows use the existing PublisherDouble control in M3
  // regression; here FAILED is a real repository failure with no artifact.
  const failed = await createTask(request);
  await control(request, failed, "fail");
  await errorResponse(request, `/tasks/${failed}/adapter`, 409, "ARTIFACT_NOT_READY");
  const pending = await createTask(request, "unknown");
  expect((await (await request.get(`${api}/api/v1/tasks/${pending}`)).json()).status).toBe("PENDING");
  await errorResponse(request, `/tasks/${pending}/adapter`, 409, "ARTIFACT_NOT_READY");
});

test("真实下载忙/损坏/大小预算/工作区权限错误均反馈 JSON，业务完成状态不变", async ({ page, request }) => {
  const id = await createTask(request);
  await control(request, id, "bundle");
  await openTask(page, id);
  await control(request, id, "hold");
  try {
    const busy = await errorResponse(request, `/tasks/${id}/adapter`, 429, "DOWNLOAD_BUSY");
    expect(busy.headers()["retry-after"]).toBe("2");
    await uiError(page, id, "adapter", "DOWNLOAD_BUSY", () => downloadButton(page).click());
    await expect(panel(page)).toContainText("2 秒后手动重试");
    await expect(downloadButton(page)).toBeEnabled();
  } finally { await control(request, id, "release"); }
  await control(request, id, "tamper");
  await uiError(page, id, "adapter", "INVALID_ARTIFACT", () => downloadButton(page).click());
  expect((await (await request.get(`${api}/api/v1/tasks/${id}`)).json()).status).toBe("COMPLETED");
  const oversized = await createTask(request);
  await control(request, oversized, "oversize_bundle");
  await errorResponse(request, `/tasks/${oversized}/adapter`, 413, "ARTIFACT_TOO_LARGE");
  const valid = await createTask(request);
  await control(request, valid, "bundle");
  await control(request, valid, "storage");
  try {
    await errorResponse(request, `/tasks/${valid}/adapter`, 500, "STORAGE_UNAVAILABLE");
  } finally { await control(request, valid, "storage_ok"); }
  await expect.poll(async () => (await (await request.get(`${api}/__test__/state`)).json()).temporary_entries).toBe(0);
});

test("真实下载 body 阶段取消与切任务：TCP 断开释放临时文件/槽位，随后可下载", async ({ page, request }, info) => {
  const id = await createTask(request), other = await createTask(request);
  for (const task of [id, other]) await control(request, task, "bundle");
  await openTask(page, id);
  const state = async () => (await request.get(`${api}/__test__/state`)).json();
  const before = await state();
  let downloads = 0;
  page.on("download", () => downloads++);
  await control(request, id, "stall");
  try {
    await downloadButton(page).click();
    await expect.poll(async () => (await state()).started).toBe(before.started + 1);
    await panel(page).getByRole("button", { name: "取消下载", exact: true }).click();
    await expect.poll(async () => (await state()).released).toBe(before.released + 1);
    await expect.poll(async () => (await state()).temporary_entries).toBe(0);
    await expect(downloadButton(page)).toBeEnabled();
    await downloadButton(page).click();
    await expect.poll(async () => (await state()).started).toBe(before.started + 2);
    const row = page.locator("tr").filter({ hasText: other.slice(0, 8) });
    await row.getByRole("button", { name: "查看详情", exact: true }).click();
    await expect(panel(page)).toContainText(other);
    await expect.poll(async () => (await state()).released).toBe(before.released + 2);
    await expect.poll(async () => (await state()).temporary_entries).toBe(0);
    expect(downloads).toBe(0);
  } finally { await control(request, id, "stall"); }
  const pending = page.waitForEvent("download");
  await downloadButton(page).click();
  const downloaded = await pending;
  expect(downloaded.suggestedFilename()).toContain(other);
  await downloaded.saveAs(info.outputPath("after-cancel-synthetic.zip"));
  expect(downloads).toBe(1);
});
