import { randomUUID } from "node:crypto";
import { mkdtemp, rm, truncate, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";

const base = "/api/v1/datasets";
const control = "http://127.0.0.1:18000/__test__";
const raw = Buffer.from('{"instruction":"云计算是什么？","output":"通过网络按需提供资源。"}\n');
const file = (buffer = raw, name = "failure-check.jsonl") => ({ name, mimeType: "application/x-ndjson", buffer });
const uploadButton = (page) => page.getByRole("button", { name: "上传并校验", exact: true });

async function audit(request) {
  const response = await request.get(`${control}/audit`);
  expect(response.ok()).toBe(true);
  for (const candidates of Object.values(await response.json())) expect(candidates).toEqual([]);
}

test.beforeEach(async ({ page, request }) => {
  expect((await request.post(`${control}/fault`, { data: { mode: "none" } })).ok()).toBe(true);
  await page.goto("/#datasets");
  await expect(page.getByText("服务端将完成格式校验；传输达到 100% 后仍需等待确认。")).toBeVisible();
});

test.afterEach(async ({ request }) => {
  await request.post(`${control}/fault`, { data: { mode: "none" } });
  await audit(request);
});

for (const [mode, status, code] of [
  ["storage", 503, "STORAGE_UNAVAILABLE"],
  ["database", 503, "DATABASE_UNAVAILABLE"],
  ["internal", 500, "INTERNAL_ERROR"],
]) {
  test(`真实服务故障 ${mode}：安全错误、没有残留、不自动重试并可恢复`, async ({ page, request }) => {
    const before = await (await request.get(base)).json();
    const name = `故障恢复-${randomUUID()}`;
    await page.locator('input[type="file"]').setInputFiles(file());
    await page.getByLabel("数据集名称").fill(name);
    expect((await request.post(`${control}/fault`, { data: { mode } })).ok()).toBe(true);
    let posts = 0;
    page.on("request", (request) => { if (request.url().endsWith(base) && request.method() === "POST") posts++; });
    const pending = page.waitForResponse((response) => response.url().endsWith(base) && response.request().method() === "POST");
    await uploadButton(page).click();
    const response = await pending;
    expect(response.status()).toBe(status);
    const { error } = await response.json();
    expect(error.code).toBe(code);
    expect(error.request_id).toBe(response.headers()["x-request-id"]);
    expect(JSON.stringify(error)).not.toContain("injected test");
    await expect(page.getByRole("alert")).toContainText(error.request_id);
    await expect(uploadButton(page)).toBeEnabled();
    expect((await (await request.get(base)).json()).total).toBe(before.total);
    await audit(request);
    expect(posts).toBe(1);
    const recovered = page.waitForResponse((response) => response.url().endsWith(base) && response.status() === 201);
    await uploadButton(page).click(); // Explicit user retry, never automatic.
    await recovered;
    await expect(page.getByRole("row").filter({ hasText: name })).toBeVisible();
    expect(posts).toBe(2);
  });
}

test("列表数据库失败不显示旧数据为新结果，刷新后恢复", async ({ page, request }) => {
  await request.post(`${control}/fault`, { data: { mode: "list_database" } });
  const pending = page.waitForResponse((response) => response.url().includes(`${base}?`) && response.status() === 503);
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  const response = await pending;
  const { error } = await response.json();
  await expect(page.getByRole("alert")).toContainText(error.request_id);
  await expect(page.getByText("数据暂时无法读取", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.getByText("数据暂时无法读取", { exact: true })).toHaveCount(0);
});

for (const [label, buffer, code] of [
  ["错误 JSON", Buffer.from("{bad}"), "invalid_json"],
  ["错误编码", Buffer.from([0xff]), "invalid_encoding"],
  ["重复键", Buffer.from('{"instruction":"x","output":"a","output":"b"}'), "duplicate_key"],
  ["超限物理行", Buffer.alloc(1024 * 1024 + 1, 32), "line_too_large"],
]) {
  test(`${label}：服务端拒绝，页面展示真实错误且存储保持一致`, async ({ page }) => {
    await page.locator('input[type="file"]').setInputFiles(file(buffer));
    const pending = page.waitForResponse((response) => response.url().endsWith(base) && response.request().method() === "POST");
    await uploadButton(page).click();
    const response = await pending;
    expect(response.status()).toBe(code === "line_too_large" ? 413 : 422);
    const { error } = await response.json();
    expect(error.details[0].code).toBe(code);
    await expect(page.getByRole("alert")).toContainText(error.request_id);
  });
}

test("伪造文件路径只保留原始文件名，响应不含服务器路径", async ({ page, request }) => {
  const name = `路径检查-${randomUUID()}`;
  const response = await request.post(base, { multipart: { file: file(raw, "../../outside.jsonl"), name } });
  expect(response.status()).toBe(201);
  const detail = await response.json();
  expect(detail.original_filename).toBe("outside.jsonl");
  expect(detail).not.toHaveProperty("storage_path");
  expect(detail).not.toHaveProperty("user_id");
  await page.getByRole("button", { name: "刷新数据", exact: true }).click();
  await page.getByRole("row").filter({ hasText: name }).getByRole("button", { name: "详情" }).click();
  await expect(page.getByRole("dialog")).toContainText("outside.jsonl");
  await expect(page.getByRole("dialog")).not.toContainText("../");
});

test("超过 50 MiB 的文件在浏览器预检阶段拒绝", async ({ page }) => {
  const directory = await mkdtemp(join(tmpdir(), "llmcloud-limit-"));
  try {
    const path = join(directory, "large.jsonl");
    await writeFile(path, "");
    await truncate(path, 50 * 1024 * 1024 + 1); // Sparse file; no large buffer or upload.
    await page.locator('input[type="file"]').setInputFiles(path);
    await expect(page.getByRole("alert")).toContainText("不得超过 50 MiB");
    await expect(uploadButton(page)).toBeDisabled();
  } finally {
    await rm(directory, { recursive: true });
  }
});

test("mock 上游代理 HTML 错误有兜底提示，不重传 POST", async ({ page }) => {
  let posts = 0;
  await page.route(`**${base}`, async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    posts++;
    await route.fulfill({ status: 502, contentType: "text/html", body: "<html>Mock bad gateway</html>" });
  });
  await page.locator('input[type="file"]').setInputFiles(file());
  await uploadButton(page).click();
  await expect(page.getByRole("alert")).toContainText("HTTP 502");
  await expect(page.getByRole("alert")).toContainText("保存结果尚不确定");
  expect(posts).toBe(1);
});
