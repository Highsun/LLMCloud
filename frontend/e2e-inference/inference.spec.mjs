import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const fixture = JSON.parse(readFileSync(new URL("../tests/fixtures/inference-draft.json", import.meta.url)));
const id = fixture.request.task_id;
const other = "992aa53a-a246-45de-a8f1-4d4164d9b42f";
const task = (taskId) => ({ id: taskId, status: "COMPLETED", created_at: "2026-11-13T10:00:00Z" });
const json = (route, body, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
function response(input, text) {
  return { ...fixture.response, task_id: input.task_id, mode: input.mode,
    max_new_tokens: input.max_new_tokens,
    base: input.mode === "compare" ? fixture.response.base : null,
    adapter: text ? { generated_text: text, generated_tokens: 1 } : fixture.response.adapter };
}
async function setup(page, { available = true, total = 2 } = {}) {
  await page.route("**/openapi.json", (route) => json(route, { paths: {
    "/api/v1/tasks": { get: {} }, "/api/v1/datasets": { get: {} },
    ...(available ? { "/api/v1/inference": { post: {} } } : {}),
  } }));
  await page.route("**/api/v1/**", (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/health")) return json(route, { status: "ok", service: "mock-inference-draft" });
    if (url.pathname.endsWith("/models")) return json(route, []);
    if (url.pathname.endsWith("/datasets")) return json(route, { items: [], page: 1, page_size: 20, total: 0, total_pages: 0 });
    if (url.pathname.endsWith("/tasks")) {
      const pageNumber = Number(url.searchParams.get("page"));
      const items = total > 20 ? Array.from({ length: 21 }, (_, i) => task(
        `992aa53a-a246-45de-a8f1-${String(i + 1).padStart(12, "0")}`)) : [task(id), task(other)];
      return json(route, { items: items.slice((pageNumber - 1) * 20, pageNumber * 20),
        page: pageNumber, page_size: 20, total, total_pages: Math.ceil(total / 20) });
    }
    // Any unexpected API use fails instead of falling through to a real service.
    return json(route, { error: { code: "MOCK_UNEXPECTED_REQUEST", message: url.pathname } }, 501);
  });
  await page.goto("/#inference");
  await expect(page.locator("#inference-task option")).toHaveCount(Math.min(total, 20) + 1);
}
async function fill(page, taskId = id) {
  await page.locator("#inference-task").selectOption(taskId);
  await page.locator("#prompt").fill(fixture.request.prompt);
}
const submit = (page) => page.getByRole("button", { name: /^(生成回答|重新生成)$/ });
const held = () => { let resolve; const promise = new Promise((yes) => { resolve = yes; }); return { resolve, promise }; };

test("mock compare draft renders both answers, metadata and narrow layout", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/inference", (route) => {
    expect(route.request().postDataJSON()).toEqual(fixture.request);
    return json(route, fixture.response);
  });
  await fill(page); await submit(page).click();
  await expect(page.locator('[data-answer="base"] .model-output')).toHaveText(fixture.response.base.generated_text);
  await expect(page.locator('[data-answer="adapter"] .model-output')).toHaveText(fixture.response.adapter.generated_text);
  await expect(page.getByText(`revision ${fixture.response.model_revision}`)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("mock-compare-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator(".sidebar").evaluate((element) => element.getBoundingClientRect().right)).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath("mock-compare-mobile.png"), fullPage: true });
});

test("adapter mode sends mode and shows no base result; generated HTML is escaped", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/inference", (route) => {
    const input = route.request().postDataJSON(); expect(input.mode).toBe("adapter");
    return json(route, response(input, '<img src=x onerror="window.mockXss=true">'));
  });
  await fill(page); await page.locator("#inference-mode").selectOption("adapter");
  await submit(page).click();
  await expect(page.locator('[data-answer="adapter"] .model-output')).toContainText("<img");
  await expect(page.locator('[data-answer="adapter"] img')).toHaveCount(0);
  await expect(page.getByText("仅 Adapter 模式不生成基础模型回答。")).toBeVisible();
  expect(await page.evaluate(() => window.mockXss)).toBeUndefined();
});

for (const [code, message] of [["GPU_BUSY", "GPU 当前忙碌"], ["ARTIFACT_NOT_READY", "训练尚未完成"]]) {
  test(`mock ${code} keeps input and request ID, then manual retry succeeds`, async ({ page }) => {
    await setup(page); let count = 0;
    await page.route("**/api/v1/inference", (route) => {
      count++;
      return count === 1 ? json(route, { error: { ...fixture.busy.error, code } }, 409) :
        json(route, response(route.request().postDataJSON()));
    });
    await fill(page); await submit(page).click();
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(page.getByRole("alert")).toContainText(fixture.busy.error.request_id);
    await expect(page.locator("#prompt")).toHaveValue(fixture.request.prompt);
    expect(count).toBe(1);
    await submit(page).click();
    await expect(page.locator('[data-answer="adapter"] .model-output')).toBeVisible();
    expect(count).toBe(2);
  });
}

test("switch task while waiting aborts old wait and only displays new task result", async ({ page }) => {
  await setup(page); const gate = held(), entered = held();
  await page.route("**/api/v1/inference", async (route) => {
    const input = route.request().postDataJSON();
    if (input.task_id === id) { entered.resolve(); await gate.promise; }
    await json(route, response(input, input.task_id === id ? "OLD MOCK RESULT" : "NEW MOCK RESULT")).catch(() => {});
  });
  await fill(page); await submit(page).click(); await entered.promise;
  await expect(page.locator("#inference-task")).toBeEnabled();
  await page.locator("#inference-task").selectOption(other);
  await expect(page.getByText(/已停止原请求的等待/)).toBeVisible();
  await submit(page).click();
  await expect(page.locator('[data-answer="adapter"] .model-output')).toHaveText("NEW MOCK RESULT");
  gate.resolve();
  await expect(page.locator(".inference-answers")).not.toContainText("OLD MOCK RESULT");
  await expect(page.locator(".inference-answers .result-context")).toContainText(other);
});

test("stop waiting and cached-page navigation discard in-flight results", async ({ page }) => {
  await setup(page); let gate = held(), entered = held();
  await page.route("**/api/v1/inference", async (route) => {
    const input = route.request().postDataJSON(); entered.resolve(); await gate.promise;
    await json(route, response(input, "LATE MOCK RESULT")).catch(() => {});
  });
  await fill(page); await submit(page).click(); await entered.promise;
  await page.getByRole("button", { name: "停止等待", exact: true }).click();
  await expect(page.getByText(/已停止等待；GPU/)).toBeVisible();
  await expect(submit(page)).toBeEnabled(); gate.resolve();
  gate = held(); entered = held();
  await submit(page).click(); await entered.promise;
  await page.evaluate(() => { location.hash = "datasets"; });
  await expect(page.getByRole("heading", { name: "数据集", exact: true })).toBeVisible();
  gate.resolve();
  await page.evaluate(() => { location.hash = "inference"; });
  await expect(submit(page)).toBeEnabled();
  await expect(page.getByText(/返回页面后可手动重试/)).toBeVisible();
  await expect(page.locator(".inference-answers")).not.toContainText("LATE MOCK RESULT");
});

test("completed tasks paginate locally and do not depend on the task-page current filter", async ({ page }) => {
  await setup(page, { total: 21 });
  await page.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(page.locator("#inference-task option")).toHaveCount(2);
  await page.locator("#inference-task").selectOption({ index: 1 });
  await expect(page.locator("#inference-task")).toHaveValue("992aa53a-a246-45de-a8f1-000000000021");
  await page.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(page.locator("#inference-task")).toHaveValue("");
  await expect(page.locator("#inference-task option")).toHaveCount(21);
});

test("missing inference OpenAPI path keeps generation disabled without mock fallback", async ({ page }) => {
  await setup(page, { available: false }); await fill(page);
  await expect(submit(page)).toBeDisabled();
  await expect(page.getByText("推理服务尚未就绪，可以先准备测试问题。")).toBeVisible();
});

test("switching mode cancels compare wait before generating adapter-only answer", async ({ page }) => {
  await setup(page); const gate = held(), entered = held();
  await page.route("**/api/v1/inference", async (route) => {
    const input = route.request().postDataJSON();
    if (input.mode === "compare") { entered.resolve(); await gate.promise; }
    await json(route, response(input, input.mode === "compare" ? "OLD COMPARE" : "NEW ADAPTER")).catch(() => {});
  });
  await fill(page); await submit(page).click(); await entered.promise;
  await page.locator("#inference-mode").selectOption("adapter");
  await expect(submit(page)).toBeEnabled();
  await submit(page).click();
  await expect(page.locator('[data-answer="adapter"] .model-output')).toHaveText("NEW ADAPTER");
  gate.resolve();
  await expect(page.locator('[data-answer="base"] .model-output')).toHaveCount(0);
});
