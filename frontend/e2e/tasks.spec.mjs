import { randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

// Real TCP API, upload validation, SQLite, runtime OpenAPI and idempotency.
// Publisher and repository progress controls are explicitly synthetic: no Redis/GPU.
const raw = Buffer.from('{"instruction":"云计算是什么？","output":"按需提供计算资源。"}\n');
const submitButton = (page) => page.getByRole("button", { name: "提交训练任务", exact: true });
const detail = (page) => page.locator(".task-detail");
const isPost = (response) => response.url().endsWith("/api/v1/tasks") && response.request().method() === "POST";
const taskReads = (page, id) => page.waitForResponse((r) => r.url().endsWith(`/api/v1/tasks/${id}`) && r.request().method() === "GET");
let dataset;

test.beforeEach(async ({ page, request }) => {
  await request.post("http://127.0.0.1:18000/__test__/publisher", { data: { mode: "accepted" } });
  const response = await request.post("/api/v1/datasets", { multipart: {
    file: { name: "m3-browser.jsonl", mimeType: "application/x-ndjson", buffer: raw }, name: `M3-${randomUUID()}`,
  } });
  expect(response.status()).toBe(201);
  dataset = await response.json();
  await page.goto("/#training");
  await expect(page.locator("#training-dataset")).toBeEnabled();
  await page.locator("#training-dataset").selectOption(dataset.id);
  await expect(submitButton(page)).toBeEnabled();
});

async function submit(page) {
  const pending = page.waitForResponse(isPost);
  await submitButton(page).click();
  return pending;
}
async function openOriginal(page, id) {
  const pending = taskReads(page, id);
  await page.getByRole("link", { name: "查看原任务", exact: true }).click();
  await pending;
  await expect(detail(page)).toContainText(id);
}

test("真实 202/去重头/详情 config，刷新后查询原任务且不 POST", async ({ page, request }, info) => {
  let posts = 0;
  page.on("request", (r) => { if (r.method() === "POST" && r.url().endsWith("/api/v1/tasks")) posts++; });
  const response = await submit(page);
  expect(response.status()).toBe(202);
  const task = await response.json();
  const key = response.request().headers()["idempotency-key"];
  expect(key).toMatch(/^[0-9a-f-]{36}$/);
  await openOriginal(page, task.id);
  await expect(detail(page)).toContainText("排队中");
  await expect(detail(page)).toContainText("进度待确认");
  await expect(detail(page).locator(".config-snapshot")).toContainText('"lora_r": 8');
  // M4 publishes these real GET capabilities; QUEUED still cannot download.
  await expect(detail(page).getByRole("tab", { name: "Loss 曲线" })).toBeEnabled();
  await expect(detail(page).getByRole("tab", { name: "运行日志" })).toBeEnabled();
  await expect(detail(page).getByRole("button", { name: "下载 Adapter" })).toBeDisabled();
  await page.reload();
  await expect(detail(page)).toContainText(task.id);
  expect(posts).toBe(1);
  // Actual replay through production HTTP/SQL returns 200 and does not invoke Publisher twice.
  const before = await (await request.get("http://127.0.0.1:18000/__test__/publisher")).json();
  const replay = await request.post("/api/v1/tasks", { data: response.request().postDataJSON(), headers: { "Idempotency-Key": key } });
  expect(replay.status()).toBe(200);
  expect((await replay.json()).id).toBe(task.id);
  expect((await (await request.get("http://127.0.0.1:18000/__test__/publisher")).json()).calls.length).toBe(before.calls.length);
  await page.screenshot({ path: info.outputPath("m3-real-http-detail.png"), fullPage: true });
});

for (const [mode, code, label] of [["unknown", "DISPATCH_UNCERTAIN", "待派发"], ["not_sent", "DISPATCH_FAILED", "失败"]]) {
  test(`真实 503 ${code} 读取专用 task_id，查询同一条持久化记录`, async ({ page, request }) => {
    await request.post("http://127.0.0.1:18000/__test__/publisher", { data: { mode } });
    const response = await submit(page);
    expect(response.status()).toBe(503);
    const { error } = await response.json();
    expect(error.code).toBe(code);
    await expect(page.getByRole("alert")).toContainText(error.request_id);
    await expect(submitButton(page)).toBeDisabled();
    await openOriginal(page, error.task_id);
    await expect(detail(page)).toContainText(label);
    await expect(detail(page)).toContainText(code);
    expect((await (await request.get(`/api/v1/tasks/${error.task_id}`)).json()).id).toBe(error.task_id);
  });
}

test("服务端已提交但浏览器确认丢失：刷新不重发，手动同键确认得到 200 原任务", async ({ page, request }) => {
  await page.locator('#lora_r').fill('16');
  let first = true, originalId;
  const keys = [], bodies = [];
  await page.route("**/api/v1/tasks", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    keys.push(route.request().headers()["idempotency-key"]);
    bodies.push(route.request().postDataJSON());
    if (first) {
      first = false;
      const saved = await route.fetch(); // Commit through the real API before dropping its response.
      originalId = (await saved.json()).id;
      return route.abort("connectionfailed");
    }
    return route.continue();
  });
  await submitButton(page).click();
  await expect(page.getByRole("button", { name: "确认原提交", exact: true })).toBeEnabled();
  await expect(page.locator("#lora_r")).toBeDisabled();
  expect(keys.length).toBe(1);
  await page.reload();
  await expect(page.getByRole("button", { name: "确认原提交", exact: true })).toBeVisible();
  await expect(page.locator('#lora_r')).toHaveValue('16');
  expect(keys.length).toBe(1);
  const before = (await (await request.get("http://127.0.0.1:18000/__test__/publisher")).json()).calls.length;
  const pending = page.waitForResponse(isPost);
  await page.getByRole("button", { name: "确认原提交", exact: true }).click();
  expect((await pending).status()).toBe(200);
  expect(keys[0]).toBe(keys[1]);
  expect(bodies[0]).toEqual(bodies[1]);
  await openOriginal(page, originalId);
  await expect(detail(page).locator('.config-snapshot')).toContainText('"lora_r": 16');
  expect((await (await request.get("http://127.0.0.1:18000/__test__/publisher")).json()).calls.length).toBe(before);
});

test("真实详情加载/100% RUNNING/失败保留步数；终态停止详情轮询", async ({ page, request }) => {
  const task = await (await submit(page)).json();
  expect((await request.post(`http://127.0.0.1:18000/__test__/tasks/${task.id}`, { data: { mode: "loading" } })).ok()).toBe(true);
  await openOriginal(page, task.id);
  await expect(detail(page)).toContainText("训练中");
  await expect(detail(page)).toContainText("进度待确认");
  expect((await request.post(`http://127.0.0.1:18000/__test__/tasks/${task.id}`, { data: { mode: "progress" } })).ok()).toBe(true);
  await detail(page).getByRole("button", { name: "刷新任务详情" }).click();
  await expect(detail(page)).toContainText("100% · 等待产物校验与状态提交");
  await expect(detail(page)).toContainText("训练中");
  expect((await request.post(`http://127.0.0.1:18000/__test__/tasks/${task.id}`, { data: { mode: "failed" } })).ok()).toBe(true);
  await detail(page).getByRole("button", { name: "刷新任务详情" }).click();
  await expect(detail(page)).toContainText("TRAINING_FAILED");
  await expect(detail(page)).toContainText("2 / 2");
  let reads = 0;
  page.on("request", (r) => { if (r.url().endsWith(`/api/v1/tasks/${task.id}`)) reads++; });
  await page.waitForTimeout(2400);
  expect(reads).toBe(0);
});

test("真实 404 详情明确错误，并允许关闭面板", async ({ page }) => {
  const task = await (await submit(page)).json();
  await openOriginal(page, task.id);
  await page.route(`**/api/v1/tasks/${task.id}`, async (route) => {
    const missing = await route.fetch({ url: route.request().url().replace(task.id, randomUUID()) });
    expect(missing.status()).toBe(404);
    await route.fulfill({ response: missing });
  });
  await detail(page).getByRole("button", { name: "刷新任务详情" }).click();
  await expect(detail(page).getByRole("alert")).toContainText("不存在");
  await detail(page).getByRole("button", { name: "关闭任务详情" }).click();
  await expect(detail(page)).toHaveCount(0);
});

test("明确准备新任务后使用新去重键，同配置也创建独立任务", async ({ page }) => {
  const first = await submit(page);
  const original = await first.json();
  await expect(submitButton(page)).toBeDisabled();
  await page.getByRole('button', { name: '准备新的训练任务', exact: true }).click();
  const second = await submit(page);
  expect(second.request().headers()['idempotency-key']).not.toBe(first.request().headers()['idempotency-key']);
  expect((await second.json()).id).not.toBe(original.id);
});

test("详情快速切换及关闭后，延迟旧响应不能覆盖选择或重开面板", async ({ page, request }) => {
  const create = async () => (await request.post('/api/v1/tasks', { data: { dataset_id: dataset.id } })).json();
  const a = await create(), b = await create();
  await page.goto('/#tasks');
  const row = (id) => page.getByRole('row').filter({ hasText: id.slice(0, 8) });
  let release, started;
  const gate = new Promise((resolve) => { release = resolve; });
  const arrived = new Promise((resolve) => { started = resolve; });
  await page.route(`**/api/v1/tasks/${a.id}`, async (route) => {
    const response = await route.fetch(); started(); await gate;
    await route.fulfill({ response }).catch(() => {});
  });
  await row(a.id).getByRole('button', { name: '查看详情' }).click();
  await arrived;
  await row(b.id).getByRole('button', { name: '查看详情' }).click();
  await expect(detail(page).locator('.config-snapshot')).toContainText('lora_r');
  release();
  await expect(detail(page).locator('.mono').first()).toHaveText(b.id);
  let finish, waiting;
  const delayed = new Promise((resolve) => { finish = resolve; });
  const pending = new Promise((resolve) => { waiting = resolve; });
  await page.route(`**/api/v1/tasks/${b.id}`, async (route) => {
    const response = await route.fetch(); waiting(); await delayed;
    await route.fulfill({ response }).catch(() => {});
  });
  await detail(page).getByRole('button', { name: '刷新任务详情' }).click();
  await pending;
  await detail(page).getByRole('button', { name: '关闭任务详情' }).click();
  finish();
  await expect(detail(page)).toHaveCount(0);
});

test("真实筛选和分页沿用服务端查询，切状态回首页", async ({ page, request }) => {
  for (let i = 0; i < 21; i++) expect((await request.post("/api/v1/tasks", { data: { dataset_id: dataset.id } })).status()).toBe(202);
  await page.goto("/#tasks");
  await page.getByRole("button", { name: "排队中", exact: true }).click();
  await expect(page.getByRole("button", { name: "下一页任务" })).toBeEnabled();
  const next = page.waitForResponse((r) => r.url().includes("page=2") && r.url().includes("status=QUEUED"));
  await page.getByRole("button", { name: "下一页任务" }).click(); await next;
  await expect(page.locator(".pagination")).toContainText("2 /");
  const filtered = page.waitForResponse((r) => r.url().includes("page=1") && r.url().includes("status=COMPLETED"));
  await page.getByRole("button", { name: "已完成", exact: true }).click(); await filtered;
  await expect(page.getByText("当前状态下没有任务", { exact: true })).toBeVisible();
  await expect(page.locator(".pagination")).toContainText("0 / 0");
});

test("窄屏提交记录和任务详情可用，无页面横向溢出", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const task = await (await submit(page)).json();
  await openOriginal(page, task.id);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath("m3-mobile-detail.png"), fullPage: true });
});
