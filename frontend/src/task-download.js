import { ApiError, baseUrl, responseError, saveFile } from "./api.js";
import { isTaskId } from "./task-submission.js";

export const DOWNLOAD_TIMEOUT_MS = 60000;
export function adapterFilename(id) {
  if (!isTaskId(id)) throw new ApiError("任务编号无效，无法下载。", { code: "INVALID_RESPONSE" });
  return `llmcloud-adapter-${id.toLowerCase()}.zip`;
}

// A separate transport keeps the M1/M3 JSON request contract unchanged.
export async function fetchTaskAdapter(id, {
  signal, timeout = DOWNLOAD_TIMEOUT_MS, fetchImpl = globalThis.fetch,
  setTimer = setTimeout, clearTimer = clearTimeout,
} = {}) {
  adapterFilename(id);
  if (!Number.isFinite(timeout) || timeout <= 0) throw new TypeError("Invalid download timeout");
  const controller = new AbortController();
  let timedOut = false;
  const abortError = () => new ApiError(timedOut
    ? "下载超时，文件尚未保存，请稍后重试。" : "下载已取消。", {
    code: timedOut ? "DOWNLOAD_TIMEOUT" : "DOWNLOAD_CANCELLED",
  });
  const abort = () => controller.abort();
  const timer = setTimer(() => { timedOut = true; controller.abort(); }, timeout);
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();

  async function consume(operation) {
    if (controller.signal.aborted) throw abortError();
    let rejectAbort;
    const cancelled = new Promise((_, reject) => { rejectAbort = reject; });
    const onAbort = () => rejectAbort(abortError());
    controller.signal.addEventListener("abort", onAbort, { once: true });
    try {
      return await Promise.race([
        Promise.resolve().then(() => {
          if (controller.signal.aborted) throw abortError();
          return operation();
        }), cancelled,
      ]);
    } finally { controller.signal.removeEventListener("abort", onAbort); }
  }

  try {
    const response = await consume(() => fetchImpl(`${baseUrl}/tasks/${encodeURIComponent(id)}/adapter`, {
      method: "GET", signal: controller.signal,
    }));
    if (!response.ok) {
      let data = null;
      try { data = await consume(() => response.json()); }
      catch { if (controller.signal.aborted) throw abortError(); }
      const error = responseError(response.status, data, response.headers.get("X-Request-ID"));
      const retry = response.headers.get("Retry-After");
      error.retryAfter = retry !== null && /^\d+$/.test(retry) && Number.isSafeInteger(Number(retry))
        ? Number(retry) : null;
      throw error;
    }
    const type = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase();
    const invalid = () => new ApiError("下载响应不是完整的 ZIP 文件，未保存该响应，请重试。", {
      code: "INVALID_RESPONSE", status: response.status, requestId: response.headers.get("X-Request-ID") || "",
    });
    if (response.status !== 200 || type !== "application/zip") {
      try { await consume(() => response.body?.cancel()); }
      catch { if (controller.signal.aborted) throw abortError(); }
      throw invalid();
    }
    const blob = await consume(() => response.blob());
    // This small signature check rejects HTML/JSON disguised as a ZIP; full audit stays on the server.
    const bytes = new Uint8Array(await consume(() => blob.slice(0, 4).arrayBuffer()));
    if (bytes.length !== 4 || bytes[0] !== 0x50 || bytes[1] !== 0x4b ||
      !((bytes[2] === 3 && bytes[3] === 4) || (bytes[2] === 5 && bytes[3] === 6))) throw invalid();
    if (controller.signal.aborted) throw abortError();
    return blob;
  } catch (error) {
    if (controller.signal.aborted) throw abortError();
    if (error instanceof ApiError) throw error;
    throw new ApiError("下载连接中断，文件尚未保存，请检查网络后手动重试。", { code: "NETWORK_ERROR" });
  } finally {
    clearTimer(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export function createTaskDownload({ state, fetchAdapter = fetchTaskAdapter, save = saveFile }) {
  let selectedId = null, generation = 0, controller = null, running = null, disposed = false;
  Object.assign(state, { taskId: null, busy: false, error: null, message: "" });
  function invalidate(message = "") {
    generation++;
    controller?.abort();
    controller = null;
    running = null;
    Object.assign(state, { busy: false, error: null, message });
  }
  function select(id) {
    if (id !== null) adapterFilename(id);
    if (id === selectedId) return;
    invalidate();
    selectedId = state.taskId = id;
  }
  function start(task) {
    if (disposed || !task || task.id !== selectedId || task.status !== "COMPLETED") return Promise.resolve(false);
    if (state.busy) return running;
    const id = selectedId, filename = adapterFilename(id), current = ++generation;
    const fresh = () => !disposed && current === generation && selectedId === id;
    controller = new AbortController();
    const signal = controller.signal;
    Object.assign(state, { busy: true, error: null, message: "" });
    const promise = (async () => {
      try {
        const blob = await fetchAdapter(id, { signal });
        if (!fresh()) return false;
        await save(blob, filename, "application/zip");
        if (fresh()) state.message = "下载已交给浏览器保存。";
        return true;
      } catch (error) {
        if (fresh()) state.error = error instanceof ApiError ? error :
          new ApiError("无法将文件交给浏览器保存，请重试。", { code: "DOWNLOAD_SAVE_FAILED" });
        return false;
      } finally {
        if (fresh()) { state.busy = false; controller = null; running = null; }
      }
    })();
    running = promise;
    return promise;
  }
  return { select, start, cancel() { if (state.busy) invalidate("下载已取消。"); },
    dispose() { invalidate(); selectedId = state.taskId = null; disposed = true; } };
}
