import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { ApiError } from "../src/api.js";
import { createInference, createInferenceTasks, fetchInference, inferenceInput,
  inferenceResult, inferenceError, unicodeLength } from "../src/inference.js";

const fixture = JSON.parse(readFileSync(new URL("./fixtures/inference-draft.json", import.meta.url)));
const input = fixture.request;
const other = "992aa53a-a246-45de-a8f1-4d4164d9b42f";
const clone = (value) => structuredClone(value);
const held = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tick = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const page = (id = input.task_id, number = 1, total = 1) => ({
  items: [{ id, status: "COMPLETED" }], page: number, page_size: 20, total, total_pages: Math.ceil(total / 20),
});

test("mock fixture exactly follows the three JSON examples in the draft", () => {
  const draft = readFileSync(new URL("../../docs/api/inference.md", import.meta.url), "utf8");
  const examples = [...draft.matchAll(/```json\s*([\s\S]*?)```/g)].map((match) => JSON.parse(match[1]));
  assert.deepEqual([input, fixture.response, fixture.busy], examples);
  assert.equal(fixture.mock, true);
});

test("input preserves prompt whitespace and counts Unicode code points", () => {
  assert.equal(inferenceInput({ ...input, prompt: "  问题  " }).prompt, "  问题  ");
  assert.equal(unicodeLength("😀"), 1);
  assert.equal(inferenceInput({ ...input, prompt: "😀".repeat(8192) }).prompt.length, 16384);
  assert.throws(() => inferenceInput({ ...input, prompt: "😀".repeat(8193) }), /检查/);
  assert.equal(inferenceInput({ ...input, prompt: '问' + '\u0000'.repeat(8191) }).prompt.length, 8192);
});

test("input rejects invalid task, blank/long prompts, modes and token limits", () => {
  for (const patch of [{ task_id: "bad" }, { prompt: "  " }, { prompt: "a".repeat(8193) },
    { max_new_tokens: 0 }, { max_new_tokens: 257 }, { max_new_tokens: true },
    { max_new_tokens: 1.5 }, { max_new_tokens: "128" }, { mode: "base" }]) {
    assert.throws(() => inferenceInput({ ...input, ...patch }), (e) => e.code === "VALIDATION_ERROR" && e.details.length > 0);
  }
  assert.equal(inferenceInput({ ...input, max_new_tokens: 256 }).max_new_tokens, 256);
});

test("compare and adapter responses have distinct, validated answers", () => {
  assert.equal(inferenceResult(fixture.response, input).base.generated_tokens, 12);
  const single = { ...fixture.response, mode: "adapter", base: null };
  assert.equal(inferenceResult(single, { ...input, mode: "adapter" }).base, null);
  assert.throws(() => inferenceResult(single, input));
  for (const patch of [{ task_id: other }, { task_id: 5 }, { mode: "adapter" },
    { max_new_tokens: 256 }, { base: null }, { adapter: null }, { model_revision: "main" },
    { input_tokens: 2049 }, { adapter: { generated_text: "x", generated_tokens: 129 } }]) {
    assert.throws(() => inferenceResult({ ...fixture.response, ...patch }, input), (e) => e.code === "INVALID_RESPONSE");
  }
});

test("transport sends only draft fields and reads sample JSON", async () => {
  const data = await fetchInference(input, { fetchImpl: async (url, options) => {
    assert.equal(url, "/api/v1/inference");
    assert.equal(options.method, "POST");
    assert.equal(options.cache, "no-store");
    assert.deepEqual(JSON.parse(options.body), input);
    return Response.json(fixture.response);
  } });
  assert.equal(data.adapter.generated_tokens, 28);
});

for (const [code, text] of [["GPU_BUSY", "GPU 当前忙碌"], ["ARTIFACT_NOT_READY", "训练尚未完成"]]) {
  test(`409 ${code} is distinct and keeps error context`, async () => {
    const payload = clone(fixture.busy); payload.error.code = code;
    payload.error.details = [{ loc: ["body", "task_id"], message: "detail" }];
    await assert.rejects(fetchInference(input, { fetchImpl: async () => Response.json(payload, { status: 409 }) }), (e) => {
      assert.ok(e.message.includes(text)); assert.equal(e.code, code);
      assert.equal(e.requestId, payload.error.request_id); assert.equal(e.details.length, 1);
      assert.equal(e.uncertain, false); return true;
    });
  });
}

test("other errors are not relabelled as GPU busy or uncertain training submissions", () => {
  const error = inferenceError(new ApiError("unknown conflict", { status: 409, code: "OTHER" }));
  assert.equal(error.message, "unknown conflict");
  for (const code of ["INFERENCE_TIMEOUT", "INFERENCE_UNAVAILABLE", "DATABASE_UNAVAILABLE", "MODEL_NOT_CACHED", "INVALID_ARTIFACT", "INFERENCE_FAILED"]) {
    const result = inferenceError(new ApiError("original", { status: 500, code, uncertain: true, requestId: "req" }));
    assert.equal(result.uncertain, false); assert.equal(result.requestId, "req"); assert.notEqual(result.message, "original");
  }
});

for (const phase of ["headers", "body"]) {
  for (const reason of ["cancel", "timeout"]) {
    test(`${reason} settles promptly during ${phase} even if transport ignores abort`, async () => {
      const caller = new AbortController(), pending = held(); let fire, cleared = false;
      const promise = fetchInference(input, {
        signal: caller.signal, setTimer: (fn, ms) => { assert.equal(ms, 120000); fire = fn; return 1; },
        clearTimer: () => { cleared = true; },
        fetchImpl: () => phase === "headers" ? pending.promise :
          Promise.resolve({ ok: true, status: 200, headers: new Headers(), json: () => pending.promise }),
      });
      const checked = assert.rejects(promise, (e) => e.code === (reason === "cancel" ? "INFERENCE_CANCELLED" : "CLIENT_INFERENCE_TIMEOUT"));
      await tick(); reason === "cancel" ? caller.abort() : fire();
      await checked; assert.ok(cleared);
      pending.resolve(phase === "headers" ? Response.json(fixture.response) : fixture.response);
      await tick();
    });
  }
}

test("pre-aborted requests never call fetch and invalid JSON fails safely", async () => {
  const controller = new AbortController(); controller.abort();
  await assert.rejects(fetchInference(input, { signal: controller.signal, fetchImpl: () => { throw Error("must not fetch"); } }),
    (e) => e.code === "INFERENCE_CANCELLED");
  await assert.rejects(fetchInference(input, { fetchImpl: async () => new Response("not json") }), (e) => e.code === "INVALID_RESPONSE");
});

test("switching tasks ignores old success, error and finally while new request runs", async () => {
  for (const rejectOld of [false, true]) {
    const state = {}, pending = [], signals = [];
    const client = createInference({ state, generate: (body, { signal }) => {
      const item = held(); pending.push(item); signals.push(signal); return item.promise;
    } });
    const first = client.start(input);
    client.cancel(); assert.ok(signals[0].aborted);
    const secondInput = { ...input, task_id: other }, second = client.start(secondInput);
    rejectOld ? pending[0].reject(new ApiError("old error")) : pending[0].resolve(fixture.response);
    await first;
    assert.equal(state.busy, true); assert.equal(state.result, null); assert.equal(state.error, null);
    pending[1].resolve({ ...fixture.response, task_id: other }); await second;
    assert.equal(state.result.task_id, other); assert.equal(state.busy, false);
  }
});

test("cancel and immediate retry on same task suppresses late old result", async () => {
  const state = {}, pending = [];
  const client = createInference({ state, generate: () => { const item = held(); pending.push(item); return item.promise; } });
  const first = client.start(input); client.cancel("stopped");
  assert.equal(state.message, "stopped"); assert.equal(state.busy, false);
  const second = client.start(input);
  pending[1].resolve(fixture.response); await second;
  pending[0].resolve({ ...fixture.response, adapter: { generated_text: "old", generated_tokens: 1 } }); await first;
  assert.notEqual(state.result.adapter.generated_text, "old");
});

test("busy prevents duplicate POST; errors allow manual retry with unchanged input", async () => {
  const state = {}, pending = held(); let count = 0;
  const client = createInference({ state, generate: (body) => { assert.deepEqual(body, input); count++; return pending.promise; } });
  const first = client.start(input); await client.start(input); assert.equal(count, 1);
  pending.reject(new ApiError("busy", { status: 409, code: "GPU_BUSY" })); await first;
  assert.equal(state.busy, false); assert.equal(state.error.code, "GPU_BUSY");
  await client.start(input); assert.equal(count, 2);
});

test("completed task queries are independent and paginated", async () => {
  const state = {}; let path;
  const list = createInferenceTasks({ state, query: async (url) => { path = url; return page(other, 2, 21); } });
  await list.load(2);
  assert.equal(path, "/tasks?page=2&page_size=20&status=COMPLETED");
  assert.equal(state.items[0].id, other); assert.equal(state.totalPages, 2);
});

test("task query cancellation and out of order replies cannot replace the latest page", async () => {
  const state = {}, pending = [], signals = [];
  const list = createInferenceTasks({ state, query: (url, { signal }) => {
    const item = held(); pending.push(item); signals.push(signal); return item.promise;
  } });
  const first = list.load(1), second = list.load(2);
  assert.ok(signals[0].aborted);
  pending[0].resolve(page()); await first; assert.equal(state.busy, true);
  pending[1].resolve(page(other, 2, 21)); await second;
  assert.equal(state.items[0].id, other);
  const third = list.load(); list.cancel(); pending[2].reject(new Error("late")); await third;
  assert.equal(state.error, null); assert.equal(state.busy, false);
});

test("task empty/failure and invalid task status cannot provide selectable entries", async () => {
  for (const response of [{ items: [], page: 1, page_size: 20, total: 0, total_pages: 0 },
    { ...page(), items: [{ id: input.task_id, status: "RUNNING" }] },
    { ...page(), items: [{ id: "invalid", status: "COMPLETED" }] }]) {
    const state = {}; let missing = false;
    const list = createInferenceTasks({ state, query: async () => response, onMissing: (items) => { missing = items.length === 0; } });
    await list.load(); assert.deepEqual(state.items, []); assert.ok(missing);
  }
});
