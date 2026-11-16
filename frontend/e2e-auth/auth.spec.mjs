import { test, expect } from "@playwright/test";

test("real account registration, refresh, logout, isolation and narrow login", async ({ page }) => {
  const suffix = Date.now().toString(36);
  const alice = `alice_${suffix}`, bob = `bob_${suffix}`;
  const password = "separate-test-password-2026";
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "登录工作空间" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "主导航" })).toHaveCount(0);
  const register = async (username) => {
    await page.getByRole("button", { name: "没有账户？注册" }).click();
    await page.getByLabel("用户名", { exact: true }).fill(username);
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: "注册并登录", exact: true }).click();
    await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
    await expect(page.locator(".auth-account")).toContainText(username);
  };
  await register(alice);
  const created = await page.evaluate(async () => {
    const body = new FormData();
    body.append("file", new Blob(['{"instruction":"cloud?","output":"on demand"}\n'], { type: "application/jsonl" }), "owner.jsonl");
    const response = await fetch("/api/v1/datasets", { method: "POST", body });
    return { status: response.status, data: await response.json() };
  });
  expect(created.status).toBe(201);
  await page.reload();
  await expect(page.locator(".auth-account")).toContainText(alice);
  const aliceList = await page.evaluate(() => fetch("/api/v1/datasets").then(r => r.json()));
  expect(aliceList.total).toBe(1);
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "登录工作空间" })).toBeVisible();
  await register(bob);
  const bobAccess = await page.evaluate(async (id) => ({
    list: await fetch("/api/v1/datasets").then(r => r.json()),
    forbidden: (await fetch(`/api/v1/datasets/${id}`)).status,
  }), created.data.id);
  expect(bobAccess.list.total).toBe(0);
  expect(bobAccess.forbidden).toBe(404);
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByRole("heading", { name: "登录工作空间" })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByLabel("用户名", { exact: true }).fill(alice);
  await page.getByLabel("密码", { exact: true }).fill("wrong-but-long-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("用户名或密码错误");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.locator(".auth-account")).toContainText(alice);
  expect((await page.evaluate(() => fetch("/api/v1/datasets").then(r => r.json()))).total).toBe(1);
});
