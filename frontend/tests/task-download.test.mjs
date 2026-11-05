import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError } from "../src/api.js";
import { adapterFilename, createTaskDownload, fetchTaskAdapter } from "../src/task-download.js";

const A = "44444444-4444-4444-8444-444444444444", B = "55555555-5555-4555-8555-555555555555";
// Signature-only unit fixture; complete ZIP contents are verified in the browser check.
const zip = () => new Blob([new Uint8Array([0x50, 0x4b, 3, 4, 1, 2, 3, 4])], { type: "application/zip" });
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function clock() {
  let sequence = 0;
  const pending = new Map();
  return {
    pending,
    setTimer(callback) { const key = ++sequence; pending.set(key, callback); return key; },
    clearTimer(key) { pending.delete(key); },
    fire() { const [key, callback] = pending.entries().next().value; pending.delete(key); callback(); },
  };
}
function heldBody() {
  const body = deferred(), started = deferred();
  const response = { ok: true, status: 200, headers: new Headers({ "Content-Type": "application/zip" }),
    blob() { started.resolve(); return body.promise; } };
  return { response, body, started };
}
const task = (id = A, status = "COMPLETED") => ({ id, status });

test("下载只发一次 GET，无客户端路径参数，并接受 ZIP MIME 参数", async () => {
  let calls = 0;
  const blob = await fetchTaskAdapter(A, { fetchImpl: async (url, options) => {
    calls++;
    assert.equal(url, `/api/v1/tasks/${A}/adapter`);
    assert.equal(options.method, "GET");
    assert.equal(options.body, undefined);
    return new Response(zip(), { headers: { "Content-Type": "Application/ZIP; charset=binary" } });
  } });
  assert.equal(blob.size, 8);
  assert.equal(calls, 1);
  assert.equal(adapterFilename(A), `llmcloud-adapter-${A}.zip`);
});

test("非法任务 ID 不访问网络或成为文件名", async () => {
  let calls = 0;
  await assert.rejects(fetchTaskAdapter("../../private", { fetchImpl: async () => { calls++; } }),
    (error) => error.code === "INVALID_RESPONSE");
  assert.equal(calls, 0);
});

test("200 JSON/HTML/空 MIME 和非完整 206 不保存，取消未读响应体", async () => {
  for (const [type, status] of [["text/html", 200], ["application/json", 200], [null, 200], ["application/zip", 206]]) {
    let bodyRead = false, cancelled = false;
    await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => ({ ok: true, status,
      headers: new Headers(type ? { "Content-Type": type } : {}),
      body: { async cancel() { cancelled = true; } },
      blob() { bodyRead = true; return zip(); },
    }) }), (error) => error.code === "INVALID_RESPONSE");
    assert.equal(bodyRead, false);
    assert.equal(cancelled, true);
  }
});

test("声称 ZIP 的 HTML/JSON/空文件也不能通过基本签名检查", async () => {
  for (const content of ["<html>error</html>", '{"error":"failure"}', ""]) {
    await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => new Response(content,
      { headers: { "Content-Type": "application/zip", "X-Request-ID": "invalid-zip" } }) }),
    (error) => error.code === "INVALID_RESPONSE" && error.requestId === "invalid-zip");
  }
});

test("409/413/500 JSON 保留正式错误码、说明、字段与请求编号", async () => {
  for (const [status, code] of [[409, "ARTIFACT_NOT_READY"], [413, "ARTIFACT_TOO_LARGE"], [500, "INVALID_ARTIFACT"]]) {
    const error = { code, message: "下载失败", request_id: "download-request", details: [{ loc: ["body"], message: "detail" }] };
    await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => Response.json({ error }, { status }) }), (failure) => {
      assert.equal(failure.code, code);
      assert.equal(failure.status, status);
      assert.equal(failure.requestId, "download-request");
      assert.deepEqual(failure.details, error.details);
      assert.equal(failure.uncertain, false);
      return true;
    });
  }
});

test("忙时保留 Retry-After=2 且不自动重试", async () => {
  let calls = 0;
  await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => {
    calls++;
    return Response.json({ error: { code: "DOWNLOAD_BUSY", message: "busy" } },
      { status: 429, headers: { "Retry-After": "2" } });
  } }), (error) => error.code === "DOWNLOAD_BUSY" && error.retryAfter === 2);
  assert.equal(calls, 1);
});

test("代理 HTML 错误仍保留 HTTP 状态和 header request ID", async () => {
  await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => new Response("<html>bad gateway</html>",
    { status: 502, headers: { "X-Request-ID": "proxy-request" } }) }),
  (error) => error.status === 502 && error.code === "HTTP_502" && error.requestId === "proxy-request");
});

test("收到响应头后计时器和取消转发仍覆盖整个延迟 blob，完成后才清理", async () => {
  const time = clock(), caller = new AbortController(), held = heldBody();
  let transport;
  const result = fetchTaskAdapter(A, { ...time, signal: caller.signal, fetchImpl: async (_url, options) => {
    transport = options.signal; return held.response;
  } });
  await held.started.promise;
  assert.equal(time.pending.size, 1);
  assert.equal(transport.aborted, false);
  held.body.resolve(zip());
  await result;
  assert.equal(time.pending.size, 0);
  caller.abort();
  assert.equal(transport.aborted, false, "完成后已移除调用者 abort 监听");
});

test("请求头尚未返回时 timeout 可立即拒绝，传输不响应 abort 也不挂住 UI", async () => {
  const time = clock(), headers = deferred(), started = deferred();
  let transport;
  const result = fetchTaskAdapter(A, { ...time, fetchImpl: async (_url, options) => {
    transport = options.signal; started.resolve(); return headers.promise;
  } });
  await started.promise;
  time.fire();
  await assert.rejects(result, (error) => error.code === "DOWNLOAD_TIMEOUT");
  assert.equal(transport.aborted, true);
  assert.equal(time.pending.size, 0);
  headers.resolve(new Response(zip(), { headers: { "Content-Type": "application/zip" } }));
});

for (const mode of ["cancel", "timeout"]) {
  test(`延迟 blob 的 ${mode} 立即中止，旧 body 后来完成也不返回文件`, async () => {
    const time = clock(), caller = new AbortController(), held = heldBody();
    let transport;
    const result = fetchTaskAdapter(A, { ...time, signal: caller.signal, fetchImpl: async (_url, options) => {
      transport = options.signal; return held.response;
    } });
    await held.started.promise;
    if (mode === "cancel") caller.abort(); else time.fire();
    await assert.rejects(result, (error) => error.code === (mode === "cancel" ? "DOWNLOAD_CANCELLED" : "DOWNLOAD_TIMEOUT"));
    assert.equal(transport.aborted, true);
    assert.equal(time.pending.size, 0);
    held.body.resolve(zip());
  });
}

test("错误 JSON 响应体的读取同样受 timeout 约束", async () => {
  const time = clock(), started = deferred(), body = deferred();
  const result = fetchTaskAdapter(A, { ...time, fetchImpl: async () => ({ ok: false, status: 500,
    headers: new Headers(), json() { started.resolve(); return body.promise; } }) });
  await started.promise;
  time.fire();
  await assert.rejects(result, (error) => error.code === "DOWNLOAD_TIMEOUT");
  body.resolve({ error: { code: "INVALID_ARTIFACT" } });
});

test("已取消的信号不发送请求，网络中断或读取失败不重试", async () => {
  const caller = new AbortController(); caller.abort();
  let calls = 0;
  await assert.rejects(fetchTaskAdapter(A, { signal: caller.signal, fetchImpl: async () => { calls++; } }),
    (error) => error.code === "DOWNLOAD_CANCELLED");
  assert.equal(calls, 0);
  await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => { calls++; throw new TypeError("offline"); } }),
    (error) => error.code === "NETWORK_ERROR");
  assert.equal(calls, 1);
  await assert.rejects(fetchTaskAdapter(A, { fetchImpl: async () => ({ ok: true, status: 200,
    headers: new Headers({ "Content-Type": "application/zip" }), blob() { throw new TypeError("broken body"); } }) }),
    (error) => error.code === "NETWORK_ERROR");
});

test("只有选中的 COMPLETED 任务可下载，连续点击共用一次请求", async () => {
  const state = {}, body = deferred(); let calls = 0;
  const saved = [];
  const download = createTaskDownload({ state, fetchAdapter: () => { calls++; return body.promise; },
    save: (blob, filename) => saved.push({ blob, filename }) });
  download.select(A);
  for (const status of ["PENDING", "QUEUED", "RUNNING", "FAILED"]) await download.start(task(A, status));
  await download.start(task(B));
  assert.equal(calls, 0);
  const first = download.start(task()), second = download.start(task());
  assert.equal(first, second);
  assert.equal(calls, 1);
  body.resolve(zip());
  await first;
  assert.equal(saved.length, 1);
  assert.equal(saved[0].filename, adapterFilename(A));
  assert.equal(state.busy, false);
  assert.match(state.message, /交给浏览器/);
});

for (const outcome of ["success", "failure"]) {
  test(`切任务后的旧 ${outcome}/finally 不保存旧文件、不污染新下载`, async () => {
    const state = {}, old = deferred(), current = deferred(), saved = [];
    let oldSignal;
    const download = createTaskDownload({ state, fetchAdapter: (id, options) => {
      if (id === A) { oldSignal = options.signal; return old.promise; } return current.promise;
    }, save: (blob, filename) => saved.push(filename) });
    download.select(A);
    const oldRead = download.start(task(A));
    download.select(B);
    assert.equal(oldSignal.aborted, true);
    const newRead = download.start(task(B));
    if (outcome === "success") old.resolve(zip()); else old.reject(new ApiError("old error"));
    await oldRead;
    assert.equal(state.busy, true);
    assert.equal(state.error, null);
    assert.equal(state.message, "");
    assert.equal(saved.length, 0);
    current.resolve(zip());
    await newRead;
    assert.deepEqual(saved, [adapterFilename(B)]);
  });
}

test("取消可立即恢复按钮，旧请求完成不保存，再点击显式发起新请求", async () => {
  const state = {}, old = deferred(), saved = [];
  let calls = 0, signal;
  const download = createTaskDownload({ state, fetchAdapter: (_id, options) => {
    signal = options.signal; return ++calls === 1 ? old.promise : Promise.resolve(zip());
  }, save: (_blob, filename) => saved.push(filename) });
  download.select(A);
  const pending = download.start(task());
  download.cancel();
  assert.equal(signal.aborted, true);
  assert.equal(state.busy, false);
  assert.match(state.message, /已取消/);
  await download.start(task());
  old.resolve(zip()); await pending;
  assert.equal(calls, 2);
  assert.deepEqual(saved, [adapterFilename(A)]);
});

test("关闭详情/卸载清除错误和下载状态，晚到文件不能触发保存", async () => {
  for (const mode of ["close", "dispose"]) {
    const state = {}, pending = deferred(); let saved = 0;
    const download = createTaskDownload({ state, fetchAdapter: () => pending.promise, save: () => { saved++; } });
    download.select(A);
    const request = download.start(task());
    if (mode === "close") download.select(null); else download.dispose();
    pending.resolve(zip()); await request;
    assert.equal(saved, 0);
    assert.equal(state.busy, false);
    assert.equal(state.error, null);
    assert.equal(state.taskId, null);
  }
});

test("下载错误不调用保存且保留请求编号/Retry-After；保存异常明确反馈", async () => {
  const state = {}; let saveCalls = 0;
  const error = new ApiError("busy", { status: 429, code: "DOWNLOAD_BUSY", requestId: "busy-request" });
  error.retryAfter = 2;
  const download = createTaskDownload({ state, fetchAdapter: async () => { throw error; }, save: () => { saveCalls++; } });
  download.select(A);
  await download.start(task());
  assert.equal(state.error, error);
  assert.equal(state.error.retryAfter, 2);
  assert.equal(saveCalls, 0);
  assert.equal(state.busy, false);
  const brokenState = {};
  const broken = createTaskDownload({ state: brokenState, fetchAdapter: async () => zip(), save: () => { throw new Error("browser failure"); } });
  broken.select(A);
  assert.equal(await broken.start(task()), false);
  assert.equal(brokenState.error.code, "DOWNLOAD_SAVE_FAILED");
});
