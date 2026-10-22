import { createHash, randomUUID } from "node:crypto";
import { expect, test } from "@playwright/test";

// Real API + disposable SQLite/files. No synthetic task state or training metrics.
const raw = Buffer.from('{"instruction":"什么是云计算？","output":"按需提供计算资源。"}\n');
const inputFile = (buffer = raw, name = "browser.jsonl") => ({
  name, mimeType: "application/x-ndjson", buffer,
});
const uploadButton = (page) => page.getByRole("button", { name: "上传并校验", exact: true });
const row = (page, name) => page.getByRole("row").filter({ hasText: name });
const isUpload = (response) => response.url().endsWith("/api/v1/datasets") && response.request().method() === "POST";
const scriptErrors = new WeakMap();

test.beforeEach(async ({ page }) => {
  const errors = [];
  scriptErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/#datasets");
  await expect(uploadButton(page)).toBeDisabled(); // No file chosen yet.
  await expect(page.getByText("服务端将完成格式校验；传输达到 100% 后仍需等待确认。")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "正在读取数据集" })).toHaveCount(0);
});

test.afterEach(async ({ page }) => {
  expect(scriptErrors.get(page)).toEqual([]);
});

async function chooseFile(page, name, buffer = raw) {
  await page.locator('input[type="file"]').setInputFiles(inputFile(buffer));
  await page.getByLabel("数据集名称").fill(name);
}

async function upload(page, name, buffer = raw) {
  await chooseFile(page, name, buffer);
  const pending = page.waitForResponse(isUpload);
  await uploadButton(page).click();
  return pending;
}

test("真实上传、元数据详情、刷新持久化和桌面展示", async ({ page }, info) => {
  const name = `持久化-${randomUUID()}`;
  const response = await upload(page, name);
  expect(response.status()).toBe(201);
  const detail = await response.json();
  expect(detail.sha256).toBe(createHash("sha256").update(raw).digest("hex"));
  expect(detail.size_bytes).toBe(raw.length);
  await expect(page.getByRole("status").filter({ hasText: "已上传并保存" })).toBeVisible();
  await expect(row(page, name)).toBeVisible();
  await row(page, name).getByRole("button", { name: "详情" }).click();
  const dialog = page.getByRole("dialog", { name: "数据集详情" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText(detail.id, { exact: true })).toBeVisible();
  await expect(dialog.getByText(detail.sha256, { exact: true })).toBeVisible();
  await expect(dialog.getByText("browser.jsonl", { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "完成" }).click();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await expect(row(page, name)).toBeVisible();
  await page.screenshot({ path: info.outputPath("datasets-desktop.png"), fullPage: true });
});

test("服务端拒绝缺字段数据，页面展示真实行号和 request_id，列表不增加", async ({ page, request }) => {
  const before = await (await request.get("/api/v1/datasets")).json();
  const response = await upload(page, `错误数据-${randomUUID()}`, Buffer.concat([
    raw, Buffer.from('\n{"instruction":"缺少输出"}\n'),
  ]));
  expect(response.status()).toBe(422);
  const { error } = await response.json();
  expect(error.code).toBe("INVALID_DATASET");
  const notice = page.getByRole("alert");
  await expect(notice).toContainText("第 3 行");
  await expect(notice).toContainText("output");
  await expect(notice).toContainText(error.request_id);
  const after = await (await request.get("/api/v1/datasets")).json();
  expect(after.total).toBe(before.total);
});

test("本地预检拒绝空文件和错误扩展名，不发送上传请求", async ({ page }) => {
  let posts = 0;
  page.on("request", (request) => { if (request.method() === "POST") posts++; });
  await page.locator('input[type="file"]').setInputFiles(inputFile(Buffer.alloc(0)));
  await expect(page.getByRole("alert")).toContainText("文件不能为空");
  await expect(uploadButton(page)).toBeDisabled();
  await page.locator('input[type="file"]').setInputFiles(inputFile(raw, "wrong.csv"));
  await expect(page.getByRole("alert")).toContainText("扩展名为 .jsonl");
  await expect(uploadButton(page)).toBeDisabled();
  expect(posts).toBe(0);
});

test("真实分页保持服务端顺序，更换每页数量后回到第一页", async ({ page, request }) => {
  // Seed via the public upload API, keeping production validation/storage active.
  for (let index = 0; index < 21; index++) {
    const response = await request.post("/api/v1/datasets", { multipart: {
      file: inputFile(), name: `分页-${index}-${randomUUID()}`,
    } });
    expect(response.status()).toBe(201);
  }
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  const next = page.getByRole("button", { name: "下一页", exact: true });
  await expect(next).toBeEnabled();
  await next.click();
  await expect(page.locator(".pagination")).toContainText("2 / ");
  const expected = await (await request.get("/api/v1/datasets?page=2&page_size=20")).json();
  await expect(page.locator("tbody tr")).toHaveCount(expected.items.length);
  expect(await page.locator("tbody tr .table-name strong").allTextContents()).toEqual(expected.items.map((item) => item.name));
  await page.getByLabel("每页数量").selectOption("50");
  await expect(page.locator(".pagination")).toContainText("1 / 1");
  await expect(next).toBeDisabled();
});

test("上传成功会取代正在刷新的旧列表请求", async ({ page }) => {
  let held = false;
  let captured;
  const snapshotReady = new Promise((resolve) => { captured = resolve; });
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/v1/datasets?*", async (route) => {
    if (held) return route.continue();
    held = true;
    const response = await route.fetch();
    captured();
    await gate;
    await route.fulfill({ response }).catch(() => {}); // Browser may have cancelled this stale GET.
  });
  const name = `并发刷新-${randomUUID()}`;
  try {
    await page.getByRole("button", { name: "刷新数据", exact: true }).click();
    await snapshotReady;
    expect((await upload(page, name)).status()).toBe(201);
    await expect(row(page, name)).toBeVisible();
    release();
    await expect(row(page, name)).toBeVisible();
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("取消等待不自动重传，已经保存的文件可通过刷新确认", async ({ page }) => {
  let posts = 0;
  let saved;
  const committed = new Promise((resolve) => { saved = resolve; });
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route("**/api/v1/datasets", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    const response = await route.fetch();
    expect(response.status()).toBe(201);
    saved();
    await gate;
    await route.fulfill({ response }).catch(() => {});
  });
  try {
    const name = `取消后核对-${randomUUID()}`;
    await chooseFile(page, name);
    await uploadButton(page).click();
    await committed;
    await expect(page.getByRole("button", { name: "取消上传" })).toBeVisible();
    // Playwright routes hold the response outside Chromium's native upload stack,
    // so do not infer an upload percentage from the proxy's committed response.
    await expect(page.getByRole("button", { name: "上传处理中…", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "取消上传" }).click();
    await expect(page.getByRole("alert")).toContainText("保存结果尚不确定");
    await expect(uploadButton(page)).toBeEnabled();
    release();
    await page.getByRole("button", { name: "刷新数据", exact: true }).click();
    await expect(row(page, name)).toBeVisible();
    expect(posts).toBe(1);
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }
});

test("离线失败有明确提示，恢复网络后可以刷新", async ({ page, context }) => {
  await chooseFile(page, `离线-${randomUUID()}`);
  await context.setOffline(true);
  try {
    await uploadButton(page).click();
    await expect(page.getByRole("alert")).toContainText("上传连接中断");
    await expect(page.getByRole("alert")).toContainText("保存结果尚不确定");
  } finally {
    await context.setOffline(false);
  }
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  await expect(page.getByText("API 在线", { exact: true })).toBeVisible();
});

test("移动端导航、上传和详情保持可用，没有页面横向溢出", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "切换导航菜单" }).click();
  await page.getByRole("link", { name: "工作台总览", exact: true }).click();
  await expect(page.getByRole("heading", { name: "工作台总览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "切换导航菜单" }).click();
  await page.getByRole("link", { name: "数据集", exact: true }).click();
  const name = `移动端-${randomUUID()}`;
  expect((await upload(page, name)).status()).toBe(201);
  await expect(row(page, name)).toBeVisible();
  await row(page, name).getByRole("button", { name: "详情" }).click();
  const dialog = page.getByRole("dialog", { name: "数据集详情" });
  await expect(dialog.getByText(name, { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "完成" }).click();
  const layout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    overflow: [...document.querySelectorAll("body *")]
      .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
      .map((element) => ({ tag: element.tagName, className: String(element.className),
        width: element.getBoundingClientRect().width, right: element.getBoundingClientRect().right }))
      .slice(0, 12),
  }));
  expect(layout.scrollWidth, JSON.stringify(layout)).toBeLessThanOrEqual(layout.viewport);
  await page.locator(".table-scroll").evaluate((element) => { element.scrollLeft = 0; });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: info.outputPath("datasets-mobile.png"), fullPage: true });
});
