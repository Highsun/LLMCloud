import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, afterEach, before, beforeEach, test } from "node:test";
import { createServer } from "vite";
import { h } from "vue";
import { renderToString } from "@vue/server-renderer";

// Generated contract fixtures and fetch substitutes are test-only, never product fallback data.
const fixture = JSON.parse(
  await readFile(
    new URL("../../docs/examples/tasks/list-response.json", import.meta.url),
    "utf8",
  ),
);
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
let server,
  workspace,
  loadTasks,
  selectTaskStatus,
  pollTasks,
  cancelTaskRequest,
  refreshWorkspace;
let calls, jobs;

before(async () => {
  globalThis.window = { location: { origin: "http://localhost" } };
  server = await createServer({
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
    appType: "custom",
  });
  ({
    workspace,
    loadTasks,
    selectTaskStatus,
    pollTasks,
    cancelTaskRequest,
    refreshWorkspace,
  } = await server.ssrLoadModule("/src/workspace.js"));
});
beforeEach(() => {
  cancelTaskRequest();
  Object.assign(workspace, {
    tasks: null,
    taskPagination: null,
    taskPage: 1,
    taskStatus: "ALL",
    taskLoading: false,
    taskError: null,
    paths: null,
  });
  calls = [];
  jobs = [];
});
afterEach(async () => {
  // Release even deliberately abort-ignoring substitutes, including after an assertion failure.
  for (const call of calls)
    call.resolve(emptyPage(Number(params(call.url).get("page"))));
  await Promise.allSettled(jobs);
  cancelTaskRequest();
  globalThis.fetch = originalFetch;
});
after(async () => {
  await server?.close();
  globalThis.window = originalWindow;
});

const params = (url) => new URL(url, "http://localhost").searchParams;
const emptyPage = (page = 1) => ({
  items: [],
  total: 0,
  page,
  page_size: 20,
  total_pages: 0,
});
function pageData(page = 1, status = "ALL", total = 41, suffix = "001") {
  const item = structuredClone(
    fixture.items.find((item) => status === "ALL" || item.status === status),
  );
  item.id = `22222222-2222-4222-8222-000000000${suffix}`;
  return {
    items: page <= Math.ceil(total / 20) && total ? [item] : [],
    total,
    page,
    page_size: 20,
    total_pages: Math.ceil(total / 20),
  };
}
function immediateFetch() {
  globalThis.fetch = async (url) => {
    const query = params(url);
    return Response.json(
      pageData(Number(query.get("page")), query.get("status") || "ALL"),
    );
  };
}
function delayedFetch() {
  globalThis.fetch = (url, { signal }) =>
    new Promise((resolve, reject) => {
      // Intentionally ignore abort to prove the sequence guard, not just transport cancellation.
      calls.push({
        url,
        signal,
        resolve: (data) => resolve(Response.json(data)),
        respond: (data, status) => resolve(Response.json(data, { status })),
        reject,
      });
    });
}
function track(job) {
  jobs.push(job);
  return job;
}
async function renderTasks() {
  const { default: TasksPanel } = await server.ssrLoadModule(
    "/src/components/TasksPanel.vue",
  );
  return renderToString(h(TasksPanel));
}

test("ALL 省略 status，默认 page=1、page_size=20", async () => {
  delayedFetch();
  const job = track(loadTasks());
  assert.equal(params(calls[0].url).has("status"), false);
  assert.equal(params(calls[0].url).get("page"), "1");
  assert.equal(params(calls[0].url).get("page_size"), "20");
  calls[0].resolve(pageData());
  await job;
});

test("五种状态均作为服务端查询参数发送，返回 ALL 后不残留状态", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    return Response.json(pageData(1, params(url).get("status") || "ALL"));
  };
  for (const status of [
    "PENDING",
    "QUEUED",
    "RUNNING",
    "COMPLETED",
    "FAILED",
  ]) {
    await selectTaskStatus(status);
    assert.equal(params(urls.at(-1)).get("status"), status);
    assert.equal(workspace.taskStatus, status);
  }
  await selectTaskStatus("ALL");
  assert.equal(params(urls.at(-1)).has("status"), false);
});

test("切换状态立即回第一页并清掉旧筛选数据，加载中也不丢弃请求", async () => {
  immediateFetch();
  await loadTasks(3);
  delayedFetch();
  const job = track(selectTaskStatus("RUNNING"));
  assert.equal(workspace.taskPage, 1);
  assert.equal(workspace.taskStatus, "RUNNING");
  assert.equal(workspace.tasks, null);
  assert.equal(workspace.taskLoading, true);
  assert.equal(params(calls[0].url).get("page"), "1");
  calls[0].resolve(pageData(1, "RUNNING"));
  await job;
});

test("翻页、手动刷新、轮询均保留当前状态与页码", async () => {
  const urls = [];
  globalThis.fetch = async (url) => {
    urls.push(url);
    const p = params(url);
    return Response.json(
      pageData(Number(p.get("page")), p.get("status") || "ALL"),
    );
  };
  await selectTaskStatus("QUEUED");
  await loadTasks(2);
  await loadTasks();
  await pollTasks();
  assert.deepEqual(
    urls.map((url) => [params(url).get("status"), params(url).get("page")]),
    [
      ["QUEUED", "1"],
      ["QUEUED", "2"],
      ["QUEUED", "2"],
      ["QUEUED", "2"],
    ],
  );
});

test("连续翻页保留同一筛选的分页按钮，不因 loading 丢弃后续翻页", async () => {
  workspace.paths = { "/api/v1/tasks": { get: {} } };
  immediateFetch();
  await selectTaskStatus("RUNNING");
  delayedFetch();
  const second = track(loadTasks(2));
  const html = await renderTasks();
  assert.equal(workspace.taskPagination.total_pages, 3);
  assert.match(html, /aria-label="下一页任务"/);
  assert.doesNotMatch(html, /aria-label="下一页任务"[^>]*disabled/);
  const third = track(loadTasks(3));
  assert.equal(calls.length, 2);
  assert.equal(workspace.taskPage, 3);
  calls[1].resolve(pageData(3, "RUNNING"));
  await third;
  calls[0].resolve(pageData(2, "RUNNING"));
  await second;
  assert.equal(workspace.tasks.page, 3);
});

test("全局服务刷新也保留任务筛选和页码", async () => {
  immediateFetch();
  await selectTaskStatus("FAILED");
  await loadTasks(2);
  const urls = [];
  globalThis.fetch = async (url) => {
    if (url.endsWith("/health"))
      return Response.json({ status: "ok", service: "test", version: "test" });
    if (url.endsWith("/models")) return Response.json([]);
    if (url.endsWith("/openapi.json"))
      return Response.json({ paths: { "/api/v1/tasks": { get: {} } } });
    urls.push(url);
    return Response.json(pageData(2, "FAILED"));
  };
  await refreshWorkspace();
  assert.equal(params(urls[0]).get("status"), "FAILED");
  assert.equal(params(urls[0]).get("page"), "2");
});

test("乱序成功：旧页结果不能覆盖新的筛选结果", async () => {
  delayedFetch();
  const old = track(loadTasks(3));
  const latest = track(selectTaskStatus("RUNNING"));
  assert.equal(calls.length, 2);
  assert.equal(calls[0].signal.aborted, true);
  calls[1].resolve(pageData(1, "RUNNING", 41, "002"));
  await latest;
  calls[0].resolve(pageData(3, "ALL", 41, "001"));
  await old;
  assert.equal(workspace.taskPage, 1);
  assert.equal(workspace.taskStatus, "RUNNING");
  assert.equal(workspace.tasks.items[0].id.endsWith("002"), true);
});

test("旧请求失败不能清空较新请求的成功结果", async () => {
  delayedFetch();
  const old = track(loadTasks());
  const latest = track(selectTaskStatus("COMPLETED"));
  calls[1].resolve(pageData(1, "COMPLETED"));
  await latest;
  calls[0].reject(new TypeError("stale failure"));
  await old;
  assert.equal(workspace.taskError, null);
  assert.equal(workspace.tasks.items[0].status, "COMPLETED");
});

test("旧成功不能覆盖新请求的错误，旧 finally 不能重置新状态", async () => {
  delayedFetch();
  const old = track(loadTasks());
  const latest = track(selectTaskStatus("FAILED"));
  calls[1].respond(
    {
      error: {
        code: "DATABASE_UNAVAILABLE",
        message: "测试错误",
        details: [],
        request_id: "test-request",
      },
    },
    503,
  );
  await latest;
  const error = workspace.taskError;
  calls[0].resolve(pageData());
  await old;
  assert.equal(workspace.taskError, error);
  assert.equal(error.requestId, "test-request");
  assert.equal(workspace.tasks, null);
  assert.equal(workspace.taskLoading, false);
});

for (const result of ["success", "failure"]) {
  test(`旧请求先${result === "success" ? "成功" : "失败"}结束时，新请求仍保持加载中`, async () => {
    delayedFetch();
    const old = track(loadTasks());
    const latest = track(selectTaskStatus("PENDING"));
    if (result === "success") calls[0].resolve(pageData());
    else calls[0].reject(new TypeError("stale"));
    await old;
    assert.equal(workspace.taskLoading, true);
    assert.equal(workspace.taskError, null);
    calls[1].resolve(pageData(1, "PENDING"));
    await latest;
    assert.equal(workspace.taskLoading, false);
  });
}

test("轮询不抢占进行中的手动查询，手动查询可以抢占旧轮询", async () => {
  delayedFetch();
  const oldPoll = track(pollTasks());
  const user = track(selectTaskStatus("RUNNING"));
  await pollTasks();
  assert.equal(calls.length, 2);
  calls[1].resolve(pageData(1, "RUNNING"));
  await user;
  calls[0].resolve(pageData());
  await oldPoll;
  assert.equal(workspace.taskStatus, "RUNNING");
  assert.equal(workspace.tasks.items[0].status, "RUNNING");
});

test("取消或离开页面后，即使传输未响应 abort，也不能写入结果或错误", async () => {
  delayedFetch();
  const job = track(loadTasks());
  cancelTaskRequest();
  assert.equal(calls[0].signal.aborted, true);
  assert.equal(workspace.taskLoading, false);
  calls[0].resolve(pageData());
  await job;
  assert.equal(workspace.tasks, null);
  assert.equal(workspace.taskError, null);
});

test("空列表保留 total_pages=0，页面显示 0 / 0 且两侧分页禁用", async () => {
  workspace.paths = { "/api/v1/tasks": { get: {} } };
  globalThis.fetch = async () => Response.json(emptyPage());
  await selectTaskStatus("QUEUED");
  const html = await renderTasks();
  assert.match(html, /当前状态下没有任务/);
  assert.match(html, /0 \/ 0/);
  assert.match(html, /aria-label="上一页任务"[^>]*disabled/);
  assert.match(html, /aria-label="下一页任务"[^>]*disabled/);
});

test("错误与空列表区分展示，并可用同一筛选重试恢复", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("network failed");
  };
  await selectTaskStatus("RUNNING");
  assert.equal(workspace.taskError.code, "NETWORK_ERROR");
  assert.equal(workspace.taskLoading, false);
  assert.match(await renderTasks(), /任务列表读取失败/);
  immediateFetch();
  await loadTasks();
  assert.equal(workspace.taskError, null);
  assert.equal(workspace.tasks.items[0].status, "RUNNING");
});

test("越界空页保留请求页码，不伪装成没有任何任务或自动跳页", async () => {
  workspace.paths = { "/api/v1/tasks": { get: {} } };
  globalThis.fetch = async () => Response.json(pageData(3, "ALL", 1));
  await loadTasks(3);
  assert.equal(workspace.taskPage, 3);
  assert.equal(workspace.tasks.total, 1);
  assert.match(await renderTasks(), /当前页没有任务/);
});

test("不完整或不一致的分页响应报错，不静默修补或回退 mock", async () => {
  for (const data of [
    { items: [], total: 0 },
    { ...emptyPage(), total_pages: 1 },
    { ...emptyPage(), page: 2 },
  ]) {
    globalThis.fetch = async () => Response.json(data);
    await loadTasks();
    assert.equal(workspace.taskError.code, "INVALID_RESPONSE");
    assert.equal(workspace.tasks, null);
  }
});

test("后端未发布时保留能力探测，五种状态均展示但操作禁用", async () => {
  const html = await renderTasks();
  for (const label of ["全部", "待派发", "排队中", "训练中", "已完成", "失败"])
    assert.ok(html.includes(label));
  assert.match(html, /aria-label="刷新任务"[^>]*disabled/);
  assert.ok(!html.includes(fixture.items[0].id));
});

test("API 能力消失后，已取消的旧任务响应不能恢复陈旧列表", async () => {
  delayedFetch();
  const old = track(loadTasks());
  globalThis.fetch = async (url) =>
    url.endsWith("/health")
      ? Response.json({ status: "ok", service: "test" })
      : url.endsWith("/models")
        ? Response.json([])
        : Response.json({ paths: {} });
  await refreshWorkspace();
  calls[0].resolve(pageData());
  await old;
  assert.equal(workspace.tasks, null);
  assert.equal(workspace.taskLoading, false);
});
