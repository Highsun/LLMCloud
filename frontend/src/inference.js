import { ApiError, baseUrl, responseError, request } from "./api.js";
import { isTaskId } from "./task-submission.js";

export const INFERENCE_TIMEOUT_MS = 120000;
export const PROMPT_LIMIT = 8192;
export const unicodeLength = (text) => Array.from(text).length;
const invalid = (message) => new ApiError(message, { code: "INVALID_RESPONSE" });

export function inferenceInput(input) {
  const details = [];
  const check = (ok, field, message) => {
    if (!ok) details.push({ loc: ["body", field], message });
  };
  check(isTaskId(input.task_id), "task_id", "请选择已完成的训练任务。");
  check(typeof input.prompt === "string" && input.prompt.trim() &&
    unicodeLength(input.prompt) <= PROMPT_LIMIT, "prompt", "提示词须有内容，且不超过 8192 个 Unicode 字符。");
  check(Number.isInteger(input.max_new_tokens) && input.max_new_tokens >= 1 &&
    input.max_new_tokens <= 256, "max_new_tokens", "输出长度需为 1–256 的整数。");
  check(["adapter", "compare"].includes(input.mode), "mode", "请选择有效的生成模式。");
  const body = { task_id: input.task_id, prompt: input.prompt,
    max_new_tokens: input.max_new_tokens, mode: input.mode };
  check(new TextEncoder().encode(JSON.stringify(body)).length <= 65536,
    "prompt", "请求超过 64 KiB，请缩短提示词。");
  if (details.length) throw new ApiError("请检查推理设置。", { code: "VALIDATION_ERROR", details });
  return body;
}

export function inferenceResult(data, input) {
  const answer = (value) => value && typeof value.generated_text === "string" &&
    Number.isSafeInteger(value.generated_tokens) && value.generated_tokens >= 0 &&
    value.generated_tokens <= input.max_new_tokens;
  if (!data || typeof data.task_id !== "string" || data.task_id.toLowerCase() !== input.task_id.toLowerCase() ||
      data.mode !== input.mode || data.max_new_tokens !== input.max_new_tokens ||
      typeof data.base_model !== "string" || !data.base_model ||
      !/^[0-9a-f]{40}$/i.test(data.model_revision) ||
      !Number.isSafeInteger(data.input_tokens) || data.input_tokens < 1 || data.input_tokens > 2048 ||
      !answer(data.adapter) || (input.mode === "compare" ? !answer(data.base) : data.base !== null)) {
    throw invalid("推理响应与本次请求或契约不一致，未展示该结果。");
  }
  return { ...data, prompt: input.prompt };
}

const errorMessages = {
  GPU_BUSY: "GPU 当前忙碌，请等待训练或其他推理结束后手动重试。",
  ARTIFACT_NOT_READY: "训练尚未完成，请刷新列表并选择已完成任务。",
  TASK_NOT_FOUND: "训练任务不存在，请刷新任务列表后重新选择。",
  MODEL_NOT_CACHED: "该版本的模型缓存尚未就绪，请联系维护者准备缓存后重试。",
  INVALID_ARTIFACT: "训练产物缺失或校验失败，请保留请求编号并联系维护者检查。",
  INFERENCE_FAILED: "模型加载或生成失败，请保留请求编号并联系维护者检查。",
  INFERENCE_UNAVAILABLE: "推理服务暂不可用，输入已保留，请稍后手动重试。",
  DATABASE_UNAVAILABLE: "状态服务暂不可用，输入已保留，请稍后手动重试。",
  INFERENCE_TIMEOUT: "生成等待超时，输入已保留；GPU 可能仍在清理，请稍后手动重试。",
  REQUEST_TOO_LARGE: "请求过大，请缩短提示词后重试。",
};
export function inferenceError(error) {
  const cause = error instanceof ApiError ? error : new ApiError("无法连接推理服务，请检查网络后手动重试。");
  return new ApiError(errorMessages[cause.code] || cause.message, {
    ...cause, uncertain: false, taskId: "",
  });
}

// Separate transport preserves the existing training/dataset request behavior.
// The deadline and cancellation cover both headers and JSON consumption.
export async function fetchInference(input, {
  signal, timeout = INFERENCE_TIMEOUT_MS, fetchImpl = globalThis.fetch,
  setTimer = setTimeout, clearTimer = clearTimeout,
} = {}) {
  const body = inferenceInput(input);
  const controller = new AbortController();
  let timedOut = false;
  const interrupted = () => new ApiError(timedOut
    ? "等待超过 120 秒，GPU 可能仍在清理，请稍后手动重试。" : "已停止等待，GPU 可能仍在清理。", {
    code: timedOut ? "CLIENT_INFERENCE_TIMEOUT" : "INFERENCE_CANCELLED",
  });
  const abort = () => controller.abort();
  const timer = setTimer(() => { timedOut = true; abort(); }, timeout);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  async function consume(operation) {
    if (controller.signal.aborted) throw interrupted();
    let rejectAbort;
    const cancelled = new Promise((_, reject) => { rejectAbort = reject; });
    const onAbort = () => rejectAbort(interrupted());
    controller.signal.addEventListener("abort", onAbort, { once: true });
    try {
      return await Promise.race([Promise.resolve().then(() => {
        if (controller.signal.aborted) throw interrupted();
        return operation();
      }), cancelled]);
    } finally { controller.signal.removeEventListener("abort", onAbort); }
  }
  try {
    const response = await consume(() => fetchImpl(`${baseUrl}/inference`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: controller.signal, cache: "no-store",
    }));
    let data;
    try { data = await consume(() => response.json()); }
    catch (error) {
      if (controller.signal.aborted) throw error;
      if (response.ok) throw invalid("推理接口未返回有效 JSON。");
    }
    if (controller.signal.aborted) throw interrupted();
    if (!response.ok) throw responseError(response.status, data, response.headers.get("X-Request-ID"));
    if (response.status !== 200) throw invalid("推理接口返回了非预期的成功状态。");
    return inferenceResult(data, body);
  } catch (error) {
    throw inferenceError(controller.signal.aborted ? interrupted() : error);
  } finally {
    clearTimer(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function createInference({ state, generate = fetchInference }) {
  let sequence = 0, controller = null;
  Object.assign(state, { busy: false, result: null, error: null, message: "" });
  function cancel(message = "") {
    sequence++;
    controller?.abort();
    controller = null;
    Object.assign(state, { busy: false, result: null, error: null, message });
  }
  async function start(input) {
    if (state.busy) return;
    let body;
    try { body = inferenceInput(input); }
    catch (error) { state.error = error; return; }
    const current = ++sequence;
    const fresh = () => current === sequence;
    controller = new AbortController();
    const signal = controller.signal;
    Object.assign(state, { busy: true, error: null, result: null, message: "" });
    try {
      const data = await generate(body, { signal });
      if (fresh()) state.result = inferenceResult(data, body);
    } catch (error) {
      if (fresh()) state.error = inferenceError(error);
    } finally {
      if (fresh()) { state.busy = false; controller = null; }
    }
  }
  return { start, cancel };
}

// Independent pagination must not change the training task page's filter or selection.
export function createInferenceTasks({ state, query = request, onMissing = () => {} }) {
  let sequence = 0, controller = null;
  Object.assign(state, { items: [], page: 1, totalPages: 0, total: 0, busy: false, error: null });
  function cancel() { sequence++; controller?.abort(); controller = null; state.busy = false; }
  async function load(page = state.page) {
    if (!Number.isSafeInteger(page) || page < 1) return;
    cancel();
    const current = sequence;
    controller = new AbortController();
    Object.assign(state, { busy: true, error: null, items: [], page, totalPages: 0 });
    try {
      const data = await query(`/tasks?page=${page}&page_size=20&status=COMPLETED`, { signal: controller.signal });
      if (current !== sequence) return;
      if (!Array.isArray(data?.items) || !Number.isSafeInteger(data.total) || data.total < 0 ||
          data.page !== page || data.page_size !== 20 || data.total_pages !== Math.ceil(data.total / 20) ||
          data.items.length !== Math.max(0, Math.min(20, data.total - (page - 1) * 20)) ||
          data.items.some((task) => !isTaskId(task.id) || task.status !== "COMPLETED") ||
          new Set(data.items.map((task) => task.id)).size !== data.items.length) {
        throw invalid("已完成任务列表与契约不一致，请刷新重试。");
      }
      Object.assign(state, { items: data.items, total: data.total, totalPages: data.total_pages });
      onMissing(data.items);
    } catch (error) {
      if (current === sequence) { state.error = error; onMissing([]); }
    } finally {
      if (current === sequence) { state.busy = false; controller = null; }
    }
  }
  return { load, cancel };
}
