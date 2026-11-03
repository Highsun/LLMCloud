import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, request } from "../src/api.js";
import { createTaskSubmission } from "../src/task-submission.js";
import { progressLabel, validateTaskDetail } from "../src/task-detail.js";
import { defaultConfig } from "../src/training-config.js";

const id = "22222222-2222-4222-8222-222222222222";
const key = "11111111-1111-4111-8111-111111111111";
const body = () => ({ dataset_id: id, config: structuredClone(defaultConfig) });
function setup(send, saved) {
  const state = {}, calls = [], values = new Map(saved ? [["intent", JSON.stringify(saved)]] : []);
  const storage = { getItem: (k) => values.get(k), setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) };
  const options = { state, storage, storageKey: "intent", createKey: () => key,
    request: async (path, opts) => { calls.push({ path, ...structuredClone(opts) }); return send(path, opts); } };
  return { state, calls, values, options, controller: createTaskSubmission(options) };
}

test("POST 带去重头并读取正式 id，重复点击不会再提交", async () => {
  let finish;
  const ctx = setup(() => new Promise((resolve) => { finish = resolve; }));
  const job = ctx.controller.submit(body());
  assert.equal(ctx.state.busy, true);
  assert.equal(JSON.parse(ctx.values.get("intent")).status, "uncertain");
  await ctx.controller.submit(body());
  finish({ id }); await job;
  await ctx.controller.submit(body());
  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.calls[0].headers["Idempotency-Key"], key);
  assert.equal(ctx.state.intent.taskId, id);
  assert.equal(ctx.state.intent.status, "accepted");
});

test("网络中断不自动重试；显式确认使用原配置和原去重键", async () => {
  let attempt = 0;
  const ctx = setup(() => { if (++attempt === 1) throw new ApiError("断网", { uncertain: true }); return { id }; });
  const payload = body();
  await ctx.controller.submit(payload);
  payload.config.lora_r = 32;
  assert.equal(ctx.calls.length, 1);
  await ctx.controller.confirm();
  assert.deepEqual(ctx.calls[0].body, ctx.calls[1].body);
  assert.deepEqual(ctx.calls[0].headers, ctx.calls[1].headers);
  assert.equal(ctx.state.intent.taskId, id);
});

for (const code of ["DISPATCH_FAILED", "DISPATCH_UNCERTAIN"]) test(`${code} 使用专用 error.task_id，确认按钮不再 POST`, async () => {
  const ctx = setup(() => { throw new ApiError("派发错误", { code, taskId: id, uncertain: true }); });
  await ctx.controller.submit(body());
  assert.equal(ctx.state.intent.taskId, id);
  await ctx.controller.confirm();
  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.state.intent.status, "recorded");
});

test("刷新只恢复提交记录，不发 POST，仍能用原键确认", async () => {
  const ctx = setup(() => { throw new ApiError("中断", { uncertain: true }); });
  await ctx.controller.submit(body());
  const restored = {};
  const controller = createTaskSubmission({ ...ctx.options, state: restored });
  assert.equal(ctx.calls.length, 1);
  assert.equal(restored.intent.key, key);
  await controller.confirm();
  assert.equal(ctx.calls.length, 2);
  assert.deepEqual(ctx.calls[0].body, ctx.calls[1].body);
});

test("有 ID 的提交刷新后只用于查询；明确新任务才清除原意图", async () => {
  const ctx = setup(() => ({ id }));
  await ctx.controller.submit(body());
  const restored = {};
  const controller = createTaskSubmission({ ...ctx.options, state: restored });
  await controller.confirm();
  assert.equal(ctx.calls.length, 1);
  assert.equal(restored.intent.taskId, id);
  controller.newTask();
  assert.equal(restored.intent, null);
  assert.equal(ctx.values.size, 0);
});

test("422 展示字段错误并允许修改后重新提交；409 保留原意图", async () => {
  for (const [code, retained] of [["VALIDATION_ERROR", false], ["IDEMPOTENCY_CONFLICT", true]]) {
    const ctx = setup(() => { throw new ApiError("拒绝", { code, status: code === 'VALIDATION_ERROR' ? 422 : 409 }); });
    await ctx.controller.submit(body());
    assert.equal(Boolean(ctx.state.intent), retained);
    assert.equal(ctx.state.error.code, code);
  }
});

test("旧 task_id 成功别名、缺失或非法 id 均保留未确认意图", async () => {
  for (const result of [{ task_id: id }, {}, { id: "not-a-uuid" }]) {
    const ctx = setup(() => result);
    await ctx.controller.submit(body());
    assert.equal(ctx.state.intent.status, "uncertain");
    assert.equal(ctx.state.error.code, "INVALID_RESPONSE");
  }
});

test("存储损坏与禁用不阻塞提交，明确提示刷新恢复不可用", async () => {
  const state = {};
  const controller = createTaskSubmission({ state, request: async () => ({ id }),
    storage: { getItem() { throw new Error(); }, setItem() { throw new Error(); } }, storageKey: "x", createKey: () => key });
  await controller.submit(body());
  assert.equal(state.intent.taskId, id);
  assert.equal(state.storageWarning, true);
});

test("request 透传自定义头并保留 task_id、request_id、字段错误", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async (_url, options) => {
      assert.equal(options.headers["Idempotency-Key"], key);
      assert.equal(options.headers["Content-Type"], "application/json");
      return Response.json({ error: { code: "DISPATCH_UNCERTAIN", task_id: id, request_id: "req", details: [{ loc: ["body", "config"], message: "字段" }] } }, { status: 503 });
    };
    await assert.rejects(request("/tasks", { method: "POST", body: body(), headers: { "Idempotency-Key": key } }), (error) =>
      error.taskId === id && error.requestId === "req" && error.details.length === 1 && error.uncertain);
  } finally { globalThis.fetch = original; }
});

test("详情仅消费 config，并保留 null/真实步数/100% RUNNING 语义", () => {
  const detail = { id, status: "RUNNING", config: defaultConfig, current_step: 0, total_steps: null, progress: null };
  assert.equal(validateTaskDetail(detail, id), detail);
  assert.equal(progressLabel(detail), "进度待确认");
  assert.match(progressLabel({ ...detail, current_step: 2, total_steps: 2, progress: 1 }), /等待产物校验/);
  assert.equal(progressLabel({ ...detail, status: "COMPLETED", progress: 1 }), "100%");
  for (const patch of [{ config: undefined, training_config: defaultConfig }, { id: key }, { total_steps: 0 }, { progress: 1.1 }, { status: "SUCCESS" }])
    assert.throws(() => validateTaskDetail({ ...detail, ...patch }, id), (error) => error.code === "INVALID_RESPONSE");
});
