// B-side M4-01 consumer review using A's generated mock fixtures.
// Pagination exercises below are isolated contract examples, not a shipped controller.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, afterEach, before, test } from "node:test";
import { createServer } from "vite";
import { h } from "vue";
import { renderToString } from "@vue/server-renderer";
import { request, ApiError } from "../src/api.js";
import { validateTaskDetail } from "../src/task-detail.js";

const docs = new URL("../../docs/", import.meta.url);
const json = async (name) => JSON.parse(await readFile(new URL(name, docs), "utf8"));
const fixture = (name) => json(`examples/observability/${name}.json`);
const originalFetch = globalThis.fetch;
const originalWindow = globalThis.window;
let server, LossChart, workspace, supports, index, limits, openapi;
before(async () => {
  globalThis.window = { location: { origin: "http://localhost" } };
  server = await createServer({
    server: { middlewareMode: true, hmr: false, ws: false, watch: null },
    appType: "custom",
    optimizeDeps: { noDiscovery: true, include: [] },
  });
  ({ default: LossChart } = await server.ssrLoadModule("/src/components/LossChart.vue"));
  ({ workspace, supports } = await server.ssrLoadModule("/src/workspace.js"));
  index = await fixture("index");
  limits = (await json("contracts/observability.schema.json"))["x-limits"];
  openapi = await json("api/tasks.openapi.json");
});
afterEach(() => { globalThis.fetch = originalFetch; });
after(async () => {
  await server?.close();
  globalThis.window = originalWindow;
});
const chart = (points) => renderToString(h(LossChart, { points }));

test("M4 样例明确区分 JSON、HTTP 头和内部 DTO，不把 mock 当运行能力", async () => {
  assert.equal(index.mock, true);
  assert.equal(index.http_evidence, false);
  assert.equal(Object.keys(index.fixtures).length, 27);
  assert.equal(index.fixtures["metrics-first-page.json"].usage, "json_body");
  assert.equal(index.fixtures["adapter-headers.json"].usage, "header_description_not_json_body");
  assert.equal(index.fixtures["completed-artifact-spec.json"].usage, "internal_snapshot");
  workspace.paths = {};
  assert.equal(supports("/tasks/{id}/metrics"), false, "有样例也不启用未发现的接口");
});

test("正式分页查询可由现有 request 发送；cursor 使用返回值且非 step/数组长度", async () => {
  const first = await fixture("metrics-first-page"), next = await fixture("metrics-next-page");
  const initialQuery = await fixture("metrics-query-initial");
  const nextQuery = await fixture("metrics-query-next");
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url, "http://localhost"));
    return Response.json(calls.length === 1 ? first : next);
  };
  const path = `/tasks/${first.task_id}/metrics`;
  const page1 = await request(`${path}?${new URLSearchParams(initialQuery)}`);
  assert.equal(page1.next_cursor, nextQuery.cursor);
  const page2 = await request(`${path}?${new URLSearchParams({
    cursor: page1.next_cursor, source_id: page1.source_id, limit: nextQuery.limit,
  })}`);
  assert.equal(calls[1].searchParams.get("cursor"), "304");
  assert.equal(calls[1].searchParams.get("source_id"), first.source_id);
  assert.equal(calls[1].searchParams.has("after_step"), false);
  assert.notEqual(page1.next_cursor, page1.items.length);
  assert.notEqual(page1.next_cursor, page1.items.at(-1).step);
  assert.equal(page2.items[0].offset, page1.next_cursor);
  assert.equal(page2.has_more, false);
});

test("按 source_id/offset 演练重放去重：四记录保留同 step 的 train/eval", async () => {
  const first = await fixture("metrics-first-page"), next = await fixture("metrics-next-page");
  const records = new Map();
  for (const page of [first, next, first]) {
    for (const point of page.items) records.set(`${page.source_id}:${point.offset}`, point);
  }
  assert.equal(records.size, 4);
  assert.deepEqual([...records.values()].map((point) => [point.step, point.kind]),
    [[1, "train"], [1, "eval"], [2, "train"], [2, "eval"]]);
  assert.equal(new Map([...records.values()].map((point) => [point.step, point])).size, 2,
    "旧 Map(step) 会丢掉一半记录，须在 M4-04 替换");
  assert.ok(records.has(`${first.source_id}:0`), "offset=0 是有效身份");
  const otherSource = "b".repeat(64);
  assert.notEqual(`${otherSource}:0`, `${first.source_id}:0`, "换源不可复用旧记录身份");
});

test("浏览器重序列化无法重建源字节位置，必须使用服务端 next_cursor", async () => {
  const first = await fixture("metrics-first-page"), next = await fixture("metrics-next-page");
  const encodedBytes = [...first.items, ...next.items].reduce((bytes, record) => {
    const { offset, ...event } = record;
    return bytes + new TextEncoder().encode(`${JSON.stringify(event)}\n`).length;
  }, 0);
  assert.notEqual(encodedBytes, next.next_cursor,
    "JSON.parse/stringify 使 0.0/1.0 规范化；offset 不能由浏览器猜算");
  assert.equal(next.next_cursor, 602);
  assert.equal(limits.max_safe_integer, Number.MAX_SAFE_INTEGER);
});

test("正式双页样例直接供给原图表：四点及独立最新训练/验证 Loss", async () => {
  const first = await fixture("metrics-first-page"), next = await fixture("metrics-next-page");
  const html = await chart([...first.items, ...next.items]);
  assert.equal((html.match(/<circle\b/g) ?? []).length, 4);
  assert.match(html, /训练 Loss：2 个点，最新 0.75/);
  assert.match(html, /验证 Loss：2 个点，最新 1/);
  assert.match(html, /0.7500/);
  assert.match(html, /1.0000/);
});

test("未创建、ready 空文件、终态空页及半行可以区别，空页不要求清空旧指标", async () => {
  const absent = await fixture("metrics-not-created"), empty = await fixture("metrics-empty");
  const drained = await fixture("metrics-terminal-drained"), partial = await fixture("metrics-incomplete-tail");
  assert.equal(absent.source_state, "not_created");
  assert.equal(absent.source_id, null);
  assert.equal(empty.source_state, "ready");
  assert.ok(empty.source_id);
  assert.equal(drained.task_status, "COMPLETED");
  assert.equal(drained.next_cursor, 602);
  assert.equal(drained.has_more, false);
  assert.equal(partial.tail_incomplete, true);
  assert.equal(partial.task_status, "FAILED");
  for (const page of [absent, empty, drained]) {
    assert.equal(page.items.length, 0);
    assert.match(await chart(page.items), /暂无 Loss 记录/);
  }
  const lastPage = await fixture("metrics-next-page");
  assert.equal([...lastPage.items, ...drained.items].filter((point) => point.kind === "train").at(-1).loss, 0.75);
  assert.match(await chart(partial.items), /共 2 个指标点/);
});

test("正式零值样例不被 truthy 判断丢弃，轮询/窗口上限有明确来源", async () => {
  const page = await fixture("metrics-zero-loss");
  assert.equal(page.items[0].loss, 0);
  assert.equal(page.items[0].learning_rate, 0);
  const html = await chart(page.items);
  assert.match(html, /0.0000/);
  assert.equal((html.match(/<circle\b/g) ?? []).length, 1);
  assert.equal(limits.poll_interval_ms, 2000);
  assert.equal(limits.max_metric_pages_per_poll, 5);
  assert.equal(limits.max_visible_metrics, 10000);
  // These are agreed limits; the production bounded polling/window UI belongs to M4-04.
});

test("八种正式 ErrorResponse 能经原 request 保留 code/status/request_id，不成为任务状态", async () => {
  for (const [name, spec] of Object.entries(index.fixtures).filter(([, value]) => value.model === "ErrorResponse")) {
    const data = await fixture(name.replace(/\.json$/, ""));
    globalThis.fetch = async () => Response.json(data, { status: spec.http_status });
    await assert.rejects(request("/tasks/44444444-4444-4444-8444-444444444444/metrics"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.code, data.error.code);
      assert.equal(error.status, spec.http_status);
      assert.equal(error.requestId, data.error.request_id);
      assert.equal(error.uncertain, false, "GET 错误不属于提交结果未知");
      assert.equal(error.taskId, "", "观测错误不附加任务创建身份");
      return true;
    });
  }
});

test("日志样例提供三个独立告警及源状态；已有 request 可保留这些字段", async () => {
  const query = await fixture("logs-query");
  assert.equal(query.tail, limits.default_log_tail);
  const snapshots = await Promise.all(["logs-not-created", "logs-empty", "logs-ready", "logs-truncated", "logs-filtered-tail"].map(fixture));
  const [absent, empty, , truncated, filtered] = snapshots;
  assert.equal(absent.source_state, "not_created");
  assert.equal(empty.source_state, "ready");
  assert.equal(truncated.truncated, true);
  assert.equal(filtered.tail_incomplete, true);
  assert.ok(filtered.filtered_lines > 0);
  for (const snapshot of snapshots) {
    globalThis.fetch = async () => Response.json(snapshot);
    assert.deepEqual(await request(`/tasks/${snapshot.task_id}/logs?${new URLSearchParams(query)}`), snapshot);
  }
  assert.ok(filtered.lines.every((line) => !/[\r\n\0]/.test(line)));
  assert.equal(JSON.parse(filtered.lines[0]).failure.message, undefined,
    "故障解释从 TaskDetail 取，日志自由异常文本不要求透传");
});

test("ZIP 成功与忙时是 HTTP 头描述；正式 OpenAPI 声明二进制 body", async () => {
  assert.deepEqual(await fixture("adapter-query"), {}, "下载不传路径或其他查询参数");
  const headers = await fixture("adapter-headers"), busy = await fixture("download-busy-headers");
  const id = headers.task_id;
  assert.equal(headers["Content-Type"], "application/zip");
  assert.equal(headers["Content-Disposition"], `attachment; filename="llmcloud-adapter-${id}.zip"`);
  assert.equal(headers["Cache-Control"], "no-store");
  assert.equal(busy["Retry-After"], "2");
  const content = openapi.paths["/tasks/{task_id}/adapter"].get.responses["200"].content;
  assert.equal(content["application/zip"].schema.format, "binary");
  assert.equal(content["application/json"], undefined);
  // MIME, fixed identity and full blob cancellation are still M4-05 production work.
});

test("内部 CompletedArtifactSpec 不可代替 TaskDetail；原任务校验会拒绝它", async () => {
  const internal = await fixture("completed-artifact-spec");
  assert.throws(() => validateTaskDetail(internal, internal.spec.task_id),
    (error) => error.code === "INVALID_RESPONSE");
});

test("现有能力探测识别正式 OpenAPI 三端点，仍保留原 M1/M3 路径规则", () => {
  workspace.paths = Object.fromEntries(Object.entries(openapi.paths)
    .map(([path, operations]) => [`${openapi.servers[0].url}${path}`, operations]));
  for (const suffix of ["metrics", "logs", "adapter"]) {
    assert.equal(supports(`/tasks/{different_id}/${suffix}`), true);
  }
  assert.equal(supports("/tasks", "post"), true);
  assert.equal(supports("/tasks/{id}"), true);
  workspace.paths = { "/api/v1/datasets": { get: {}, post: {} } };
  assert.equal(supports("/datasets"), true);
  assert.equal(supports("/datasets", "post"), true);
  assert.equal(supports("/tasks/{id}/metrics"), false);
});
