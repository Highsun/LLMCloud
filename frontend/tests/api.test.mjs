import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { ApiError, getHealth, request, uploadDataset } from "../src/api.js";
import { defaultConfig, validateConfig } from "../src/training-config.js";

const originalFetch = globalThis.fetch;
const originalXHR = globalThis.XMLHttpRequest;
afterEach(() => {
  globalThis.fetch = originalFetch;
  globalThis.XMLHttpRequest = originalXHR;
});

test("健康检查只接受真实的存活响应", async () => {
  globalThis.fetch = async () =>
    Response.json({ status: "ok", service: "llmcloud", version: "0.1.0" });
  assert.equal((await getHealth()).service, "llmcloud");
  globalThis.fetch = async () =>
    Response.json({ status: "error", service: "llmcloud" });
  await assert.rejects(getHealth, (error) => error.code === "INVALID_RESPONSE");
});

test("结构化错误保留行号、字段与请求编号", async () => {
  const detail = {
    loc: ["body", "file", "output"],
    code: "missing",
    message: "缺少 output",
    line: 2,
    column: null,
  };
  globalThis.fetch = async () =>
    Response.json(
      {
        error: {
          code: "INVALID_DATASET",
          message: "数据错误",
          details: [detail],
          request_id: "request-test",
          details_truncated: true,
        },
      },
      { status: 422 },
    );
  await assert.rejects(request("/datasets"), (error) => {
    assert.equal(error.status, 422);
    assert.equal(error.code, "INVALID_DATASET");
    assert.equal(error.details[0].line, 2);
    assert.equal(error.requestId, "request-test");
    assert.equal(error.truncated, true);
    return true;
  });
});

test("兼容旧路由错误和代理 HTML 错误", async () => {
  globalThis.fetch = async () =>
    Response.json({ detail: "Not Found" }, { status: 404 });
  await assert.rejects(
    request("/datasets"),
    (error) => error.status === 404 && error.code === "HTTP_404",
  );
  globalThis.fetch = async () =>
    new Response("<html>Bad gateway</html>", {
      status: 502,
      headers: { "X-Request-ID": "proxy-request" },
    });
  await assert.rejects(
    request("/datasets"),
    (error) => error.requestId === "proxy-request" && error.status === 502,
  );
});

test("断网后的 POST 不重试，并提示保存结果不确定", async () => {
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    throw new TypeError("connection lost");
  };
  await assert.rejects(
    request("/tasks", { method: "POST", body: { dataset_id: "test" } }),
    (error) => error.uncertain === true,
  );
  assert.equal(count, 1);
});

test("超时请求被中断", async () => {
  globalThis.fetch = (_url, options) =>
    new Promise((_resolve, reject) =>
      options.signal.addEventListener("abort", () =>
        reject(new DOMException("Aborted", "AbortError")),
      ),
    );
  await assert.rejects(
    request("/health", { timeout: 10 }),
    (error) => error instanceof ApiError && error.code === "NETWORK_ERROR",
  );
});

test("取消请求不自动重试", async () => {
  globalThis.fetch = (_url, options) =>
    new Promise((_resolve, reject) => {
      if (options.signal.aborted)
        reject(new DOMException("Aborted", "AbortError"));
      else
        options.signal.addEventListener("abort", () =>
          reject(new DOMException("Aborted", "AbortError")),
        );
    });
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    request("/health", { signal: controller.signal }),
    ApiError,
  );
});

function fakeUpload({
  status = 201,
  data = { id: "dataset-test" },
  event = "load",
} = {}) {
  const calls = [];
  globalThis.XMLHttpRequest = class {
    upload = {};
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    getResponseHeader() {
      return "upload-request";
    }
    send(body) {
      calls.push({ method: this.method, url: this.url, body });
      this.status = status;
      this.responseText = JSON.stringify(data);
      queueMicrotask(() => {
        this.upload.onprogress({
          lengthComputable: true,
          loaded: 50,
          total: 100,
        });
        this[`on${event}`]();
      });
    }
    abort() {
      this.onabort();
    }
  };
  return calls;
}

test("上传仅发送 file 与可选 name，进度来自实际传输事件", async () => {
  const calls = fakeUpload();
  const progress = [];
  await uploadDataset(
    new File(["{}\n"], "data.jsonl"),
    "  云计算样例  ",
    (value) => progress.push(value),
  );
  assert.deepEqual([...calls[0].body.keys()], ["file", "name"]);
  assert.equal(calls[0].body.get("name"), "云计算样例");
  assert.equal(calls[0].url, "/api/v1/datasets");
  assert.deepEqual(progress, [50]);
});

test("空名称省略 name part，避免将空字符串提交给服务端", async () => {
  const calls = fakeUpload();
  await uploadDataset(new File(["{}"], "data.jsonl"), "", () => {});
  assert.deepEqual([...calls[0].body.keys()], ["file"]);
});

test("上传中断和异常成功响应都不冒充保存成功", async () => {
  const calls = fakeUpload({ event: "error" });
  await assert.rejects(
    uploadDataset(new File(["{}"], "data.jsonl"), "", () => {}),
    (error) => error.uncertain,
  );
  assert.equal(calls.length, 1);
  fakeUpload({ data: { success: true } });
  await assert.rejects(
    uploadDataset(new File(["{}"], "data.jsonl"), "", () => {}),
    (error) => error.code === "INVALID_RESPONSE" && error.uncertain,
  );
});

test("推荐训练参数通过契约边界校验", () =>
  assert.deepEqual(validateConfig(defaultConfig), []));

test("参数校验覆盖整数、开区间、非有限值和空目标模块", () => {
  for (const values of [
    { lora_r: 1.5 },
    { lora_r: 65 },
    { lora_dropout: 1 },
    { learning_rate: 0 },
    { learning_rate: NaN },
    { seed: -1 },
    { max_seq_length: 63 },
    { target_modules: [] },
  ]) {
    assert.ok(
      validateConfig({ ...defaultConfig, ...values }).length > 0,
      JSON.stringify(values),
    );
  }
  assert.deepEqual(
    validateConfig({
      ...defaultConfig,
      lora_dropout: 0.9999999,
      learning_rate: 1e-20,
    }),
    [],
  );
});
