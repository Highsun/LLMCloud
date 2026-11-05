import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { ApiError } from "../src/api.js";
import { createTaskObservability, OBSERVABILITY_LIMITS, validateLogsPage, validateMetricsPage } from "../src/task-observability.js";

const fixture = async (name) => JSON.parse(await readFile(new URL(`../../docs/examples/observability/${name}.json`, import.meta.url), "utf8"));
const first = await fixture("metrics-first-page"), next = await fixture("metrics-next-page");
const log = await fixture("logs-ready");
const A = first.task_id, B = "55555555-5555-4555-8555-555555555555";
const clone = structuredClone;
const metric = (path) => path.includes("/metrics?");
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function setup(request, status = "RUNNING", supports = () => true) {
  const state = {};
  const observer = createTaskObservability({ state, request, supports });
  observer.select(A, status);
  return { state, observer };
}
const logs = (id = A, status = "RUNNING") => ({ ...clone(log), task_id: id, task_status: status });
const single = (cursor, status = "RUNNING", more = false) => ({
  ...clone(first), task_status: status,
  items: [{ ...first.items[0], offset: cursor, step: cursor / 10 + 1, total_steps: 20000 }],
  next_cursor: cursor + 10, has_more: more,
});

test("观测常量与正式生成上限一致", async () => {
  const schema = JSON.parse(await readFile(new URL("../../docs/contracts/observability.schema.json", import.meta.url), "utf8"));
  const limits = schema["x-limits"];
  assert.deepEqual(OBSERVABILITY_LIMITS, { interval: limits.poll_interval_ms, pageSize: limits.default_metrics_limit,
    pagesPerRound: limits.max_metric_pages_per_poll, visibleRecords: limits.max_visible_metrics, logTail: limits.default_log_tail });
});

test("真实 fixture 双页按游标读取且保留同 step 两 kind；重复刷新空页不丢记录", async () => {
  const calls = [], pages = [first, next, await fixture("metrics-terminal-drained")];
  const { state, observer } = setup(async (path) => {
    calls.push(path);
    return metric(path) ? clone(pages.shift()) : logs();
  });
  await observer.refresh();
  assert.equal(state.metrics.points.length, 4);
  assert.equal(state.metrics.cursor, 602);
  assert.equal(state.metrics.latestTrain.loss, 0.75);
  assert.equal(new URL(calls[1], "http://test").searchParams.get("cursor"), "304");
  assert.ok(calls.every((path) => !path.includes("after_step")));
  await observer.refresh();
  assert.equal(state.metrics.points.length, 4);
});

test("每轮最多补 5 页；详情终态仍补第六页并在其后读取最终日志再停止", async () => {
  let metricsCalls = 0, logsCalls = 0;
  const events = [];
  const { state, observer } = setup(async (path) => {
    if (metric(path)) {
      events.push(`metrics-${++metricsCalls}`);
      const cursor = Number(new URL(path, "http://test").searchParams.get("cursor"));
      return single(cursor, "COMPLETED", metricsCalls < 6);
    }
    events.push(`logs-${++logsCalls}`);
    return logs(A, "COMPLETED");
  }, "COMPLETED");
  await observer.refresh();
  assert.equal(metricsCalls, 5);
  assert.equal(state.metrics.hasMore, true);
  assert.equal(state.logs.done, false);
  await observer.refresh();
  assert.deepEqual(events.slice(-2), ["metrics-6", "logs-2"]);
  assert.equal(state.metrics.points.length, 6);
  assert.equal(state.metrics.done, true);
  assert.equal(state.logs.done, true);
  assert.equal(observer.needsRefresh(), false);
  await observer.refresh();
  assert.equal(metricsCalls, 6);
});

test("迟到 RUNNING 快照不会覆盖详情终态，也不会提前停止尾部读取", async () => {
  let rounds = 0;
  const { state, observer } = setup(async (path) => metric(path)
    ? (rounds++ === 0 ? { ...clone(first), has_more: false } : { ...clone(next), items: [], next_cursor: 304 })
    : logs(A, rounds === 1 ? "RUNNING" : "COMPLETED"), "COMPLETED");
  await observer.refresh();
  assert.equal(state.taskStatus, "COMPLETED");
  assert.equal(state.metrics.done, false);
  assert.equal(state.logs.done, false);
  await observer.refresh();
  assert.equal(state.metrics.done, true);
  assert.equal(state.logs.done, true);
});

test("HTTP 409 游标失效后清除旧源，重置一次并读取新源", async () => {
  let calls = 0;
  const queries = [];
  const source = "b".repeat(64);
  const { state, observer } = setup(async (path) => {
    if (!metric(path)) return logs();
    queries.push(new URL(path, "http://test").searchParams);
    if (++calls === 1) return { ...clone(first), has_more: false };
    if (calls === 2) throw new ApiError("changed", { status: 409, code: "METRICS_CURSOR_INVALID" });
    return { ...clone(first), has_more: false, source_id: source };
  });
  await observer.refresh();
  await observer.refresh();
  assert.equal(queries[2].get("cursor"), "0");
  assert.equal(queries[2].has("source_id"), false);
  assert.equal(state.metrics.sourceId, source);
  assert.equal(state.metrics.points.length, 2);
  assert.equal(state.metrics.resetNotice, true);
  assert.equal(state.metrics.error, null);
});

test("连续游标错误每轮只重置一次，日志仍可读取", async () => {
  let metricsCalls = 0;
  const { state, observer } = setup(async (path) => {
    if (!metric(path)) return logs();
    metricsCalls++;
    throw new ApiError("changed", { status: 409, code: "METRICS_CURSOR_INVALID" });
  });
  await observer.refresh();
  assert.equal(metricsCalls, 2);
  assert.equal(state.metrics.error.code, "METRICS_CURSOR_INVALID");
  assert.ok(state.logs.page);
});

for (const outcome of ["success", "failure"]) {
  test(`切换任务后旧 ${outcome}/finally 不写入新任务，不清除新 loading`, async () => {
    const old = deferred(), current = deferred();
    const { state, observer } = setup((path) => metric(path)
      ? (path.includes(A) ? old.promise : current.promise)
      : Promise.resolve(logs(B)));
    const oldRead = observer.refresh();
    observer.select(B, "RUNNING");
    const newRead = observer.refresh();
    if (outcome === "success") old.resolve(clone(first));
    else old.reject(new ApiError("old failure"));
    await oldRead;
    assert.equal(state.taskId, B);
    assert.equal(state.metrics.loading, true);
    assert.equal(state.metrics.error, null);
    current.resolve({ ...clone(first), task_id: B, has_more: false });
    await newRead;
    assert.equal(state.metrics.points.length, 2);
    assert.equal(state.logs.page.task_id, B);
  });
}

test("隐藏暂停立即 abort，保留游标；恢复时无视旧结果并从原位置补拉", async () => {
  const pending = deferred();
  let count = 0, oldSignal;
  const queries = [];
  const { state, observer } = setup(async (path, options) => {
    if (!metric(path)) return logs();
    queries.push(new URL(path, "http://test").searchParams.get("cursor"));
    count++;
    if (count === 1) return { ...clone(first), has_more: false };
    if (count === 2) { oldSignal = options.signal; return pending.promise; }
    return clone(next);
  });
  await observer.refresh();
  const hiddenRead = observer.refresh();
  observer.pause();
  assert.equal(oldSignal.aborted, true);
  assert.equal(state.metrics.loading, false);
  await observer.refresh();
  assert.equal(count, 2);
  observer.resume();
  await observer.refresh();
  pending.resolve({ ...clone(first), has_more: false });
  await hiddenRead;
  assert.deepEqual(queries, ["0", "304", "304"]);
  assert.equal(state.metrics.cursor, 602);
  assert.equal(state.metrics.points.length, 4);
});

for (const outcome of ["success", "failure"]) {
  test(`旧日志 ${outcome}/finally 不污染新任务的日志或 loading`, async () => {
    const old = deferred(), current = deferred();
    const { state, observer } = setup((path) => path.includes(A) ? old.promise : current.promise,
      "RUNNING", (path) => path.endsWith("/logs"));
    const oldRead = observer.refresh();
    await Promise.resolve(); // readLogs follows the skipped metrics lane.
    observer.select(B, "RUNNING");
    const newRead = observer.refresh();
    await Promise.resolve();
    if (outcome === "success") old.resolve(logs(A));
    else old.reject(new ApiError("old log failure"));
    await oldRead;
    assert.equal(state.logs.loading, true);
    assert.equal(state.logs.error, null);
    assert.equal(state.logs.page, null);
    current.resolve(logs(B));
    await newRead;
    assert.equal(state.logs.page.task_id, B);
    assert.equal(state.logs.loading, false);
  });
}

test("同轮刷新去重；关闭详情或卸载后旧请求不能重新产生状态", async () => {
  const pending = deferred();
  let calls = 0, signal;
  const { state, observer } = setup((_path, options) => { calls++; signal = options.signal; return pending.promise; });
  const one = observer.refresh(), two = observer.refresh();
  assert.equal(one, two);
  assert.equal(calls, 1);
  observer.select(null);
  assert.equal(signal.aborted, true);
  pending.resolve(clone(first));
  await one;
  assert.equal(state.taskId, null);
  assert.equal(state.metrics.points.length, 0);
  observer.dispose();
  await observer.refresh();
  assert.equal(calls, 1);
});

test("非法指标整页报 INVALID_RESPONSE，不推进游标且保留已有点；日志独立成功", async () => {
  const corruptions = [
    (page) => { page.task_id = B; },
    (page) => { page.source_id = "b".repeat(64); },
    (page) => { page.next_cursor = 304; },
    (page) => { page.items[0].loss = null; },
    (page) => { page.items[0].loss = Infinity; },
    (page) => { page.items[0].offset = "304"; },
    (page) => { page.items.reverse(); },
    (page) => { page.items[0].total_steps = 4; },
    (page) => { page.items[0].kind = "unknown"; },
    (page) => { page.items[0].recorded_at = "yesterday"; },
    (page) => { page.items = []; page.has_more = true; },
    (page) => { page.unknown = true; },
  ];
  for (const corrupt of corruptions) {
    let count = 0;
    const broken = clone(next);
    corrupt(broken);
    const { state, observer } = setup(async (path) => !metric(path) ? logs() :
      (++count === 1 ? { ...clone(first), has_more: false } : broken));
    await observer.refresh();
    await observer.refresh();
    assert.equal(state.metrics.error.code, "INVALID_RESPONSE");
    assert.equal(state.metrics.cursor, 304);
    assert.equal(state.metrics.points.length, 2);
    assert.equal(state.logs.error, null);
  }
});

test("日志错误不清掉旧快照、指标成功仍可推进，之后重试可恢复", async () => {
  let logCalls = 0, metricCalls = 0;
  const { state, observer } = setup(async (path) => {
    if (metric(path)) return ++metricCalls === 1 ? { ...clone(first), has_more: false } :
      metricCalls === 2 ? clone(next) : { ...clone(next), items: [], next_cursor: 602 };
    if (++logCalls === 2) throw new ApiError("logs unavailable", { code: "LOGS_UNAVAILABLE", status: 500 });
    return { ...logs(), lines: [`snapshot-${logCalls}`] };
  });
  await observer.refresh();
  await observer.refresh();
  assert.deepEqual(state.logs.page.lines, ["snapshot-1"]);
  assert.equal(state.logs.error.code, "LOGS_UNAVAILABLE");
  assert.equal(state.metrics.points.length, 4);
  observer.setStatus("COMPLETED");
  await observer.refresh();
  assert.deepEqual(state.logs.page.lines, ["snapshot-3"]);
  assert.equal(state.logs.error, null);
});

test("日志正式响应严格校验，三个告警和 FAILED 自然缺日志均合法", async () => {
  const filtered = await fixture("logs-filtered-tail");
  assert.equal(validateLogsPage(filtered, A), filtered);
  const absent = { ...await fixture("logs-not-created"), task_status: "FAILED" };
  assert.equal(validateLogsPage(absent, A), absent);
  for (const change of [
    (page) => { page.lines = ["<script>not executed</script>\nsecond"]; },
    (page) => { page.lines = ["\ud800"]; },
    (page) => { page.filtered_lines = 101; },
    (page) => { page.truncated = 1; },
    (page) => { page.task_id = B; },
    (page) => { page.source_state = "not_created"; },
  ]) {
    const page = logs(); change(page);
    assert.throws(() => validateLogsPage(page, A), (error) => error.code === "INVALID_RESPONSE");
  }
});

test("窗口最多保留 10000 条，游标独立前进且最新训练值不因淘汰消失", async () => {
  const { state, observer } = setup(async (path) => {
    if (!metric(path)) return logs();
    const cursor = Number(new URL(path, "http://test").searchParams.get("cursor"));
    const items = Array.from({ length: 200 }, (_, index) => ({
      ...first.items[0], offset: cursor + index * 10, step: cursor / 10 + index + 1, total_steps: 20000,
    }));
    return { ...clone(first), items, next_cursor: cursor + 2000, has_more: cursor + 2000 < 110000 };
  });
  for (let round = 0; round < 11; round++) await observer.refresh();
  assert.equal(state.metrics.points.length, 10000);
  assert.equal(state.metrics.dropped, 1000);
  assert.equal(state.metrics.cursor, 110000);
  assert.equal(state.metrics.points[0].step, 1001);
  assert.equal(state.metrics.latestTrain.step, 11000);
});

test("不支持的观测接口不请求；暂停自动刷新时允许显式单轮手动重试", async () => {
  let available = false, calls = 0;
  const { state, observer } = setup(async (path) => {
    calls++; return metric(path) ? { ...clone(first), has_more: false } : logs();
  }, "RUNNING", () => available);
  await observer.refresh();
  assert.equal(calls, 0);
  available = true;
  observer.pause();
  await observer.refresh();
  assert.equal(calls, 0);
  await observer.refresh({ force: true });
  assert.equal(calls, 2);
  assert.equal(state.metrics.points.length, 2);
});

test("零 Loss 和 FAILED 半行保留完整点；空终态不清空此前完整记录", async () => {
  const zero = await fixture("metrics-zero-loss");
  assert.equal(validateMetricsPage(zero, A, { cursor: 0, limit: 200 }), zero);
  const partial = await fixture("metrics-incomplete-tail");
  const { state, observer } = setup(async (path) => metric(path) ? partial : { ...logs(), task_status: "FAILED" }, "FAILED");
  await observer.refresh();
  assert.equal(state.metrics.points.length, 2);
  assert.equal(state.metrics.tailIncomplete, true);
  assert.equal(state.metrics.done, true);
});
