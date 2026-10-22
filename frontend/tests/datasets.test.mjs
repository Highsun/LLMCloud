import assert from "node:assert/strict";
import { after, afterEach, before, test } from "node:test";
import { createServer } from "vite";

let server, loadDatasets, workspace;
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;

before(async () => {
  globalThis.window = { location: { origin: "http://localhost" } };
  server = await createServer({
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    appType: "custom",
  });
  ({ loadDatasets, workspace } = await server.ssrLoadModule("/src/workspace.js"));
});
afterEach(() => { globalThis.fetch = originalFetch; });
after(async () => {
  await server?.close();
  globalThis.window = originalWindow;
});

function datasetPage(page, name = "saved") {
  return { items: [{ id: name, name }], total: 2, page, page_size: 1, total_pages: 2 };
}

function delayedFetch() {
  const requests = [];
  globalThis.fetch = (url, { signal }) => new Promise((resolve, reject) => {
    requests.push({ url, signal, resolve: (value) => resolve(Response.json(value)), reject });
  });
  return requests;
}

test("上传后的第一页刷新不会被正在进行的列表请求丢弃，旧响应不会覆盖新数据", async () => {
  const calls = delayedFetch();
  const first = loadDatasets(2, 1);
  const latest = loadDatasets(1, 1);
  try {
    assert.equal(calls.length, 2);
    assert.equal(calls[0].signal.aborted, true);
    calls[1].resolve(datasetPage(1, "new-upload"));
    await latest;
    calls[0].resolve(datasetPage(2, "old-page"));
    await first;
    assert.equal(workspace.datasetPage, 1);
    assert.equal(workspace.datasets.items[0].name, "new-upload");
    assert.equal(workspace.datasetLoading, false);
  } finally {
    calls.forEach((call) => call.resolve(datasetPage(1)));
    await Promise.allSettled([first, latest]);
  }
});

test("旧请求失败不会清空较新请求的成功结果", async () => {
  const calls = delayedFetch();
  const first = loadDatasets(2, 1);
  const latest = loadDatasets(1, 1);
  try {
    assert.equal(calls.length, 2);
    calls[1].resolve(datasetPage(1));
    await latest;
    calls[0].reject(new TypeError("old connection failed"));
    await first;
    assert.equal(workspace.datasetError, null);
    assert.equal(workspace.datasets.page, 1);
  } finally {
    calls.forEach((call) => call.resolve(datasetPage(1)));
    await Promise.allSettled([first, latest]);
  }
});

test("旧请求结束时保留新请求的加载状态", async () => {
  const calls = delayedFetch();
  const first = loadDatasets(2, 1);
  const latest = loadDatasets(1, 1);
  try {
    assert.equal(calls.length, 2);
    calls[0].resolve(datasetPage(2));
    await first;
    assert.equal(workspace.datasetLoading, true);
    calls[1].resolve(datasetPage(1));
    await latest;
    assert.equal(workspace.datasetLoading, false);
  } finally {
    calls.forEach((call) => call.resolve(datasetPage(1)));
    await Promise.allSettled([first, latest]);
  }
});

test("当前请求失败会展示错误，后续手动刷新可以恢复", async () => {
  globalThis.fetch = async () => { throw new TypeError("connection failed"); };
  await loadDatasets(1, 1);
  assert.equal(workspace.datasetError.code, "NETWORK_ERROR");
  assert.equal(workspace.datasets, null);
  assert.equal(workspace.datasetLoading, false);
  globalThis.fetch = async () => Response.json(datasetPage(1));
  await loadDatasets(1, 1);
  assert.equal(workspace.datasetError, null);
  assert.equal(workspace.datasets.page, 1);
});
