import { ApiError } from "./api.js";
import { validateConfig } from "./training-config.js";

export const isTaskId = (value) =>
  typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

// Only IDs and configuration are retained, never dataset contents. Reloading does no POST.
export function createTaskSubmission({ state, request, storage, storageKey, createKey = () => crypto.randomUUID() }) {
  Object.assign(state, { intent: null, busy: false, error: null, storageWarning: false });
  try {
    const saved = JSON.parse(storage?.getItem(storageKey) || "null");
    if (saved && isTaskId(saved.key) && isTaskId(saved.payload?.dataset_id) &&
        saved.payload?.config && validateConfig(saved.payload.config).length === 0 &&
        ["uncertain", "accepted", "recorded"].includes(saved.status) &&
        (!saved.taskId || isTaskId(saved.taskId))) state.intent = saved;
  } catch { state.storageWarning = true; }

  function persist() {
    try {
      if (!storage) throw new Error("Storage unavailable");
      if (state.intent) storage.setItem(storageKey, JSON.stringify(state.intent));
      else storage.removeItem(storageKey);
    } catch { state.storageWarning = true; }
  }

  async function send() {
    if (state.busy || !state.intent || state.intent.taskId) return;
    state.busy = true;
    state.error = null;
    // Persist before sending: an interrupted navigation remains an unresolved intent.
    state.intent.status = "uncertain";
    persist();
    try {
      const data = await request("/tasks", {
        method: "POST", body: state.intent.payload, timeout: 15000,
        headers: { "Idempotency-Key": state.intent.key },
      });
      if (!isTaskId(data?.id)) throw new ApiError("提交响应缺少有效的 TaskDetail.id，请核对原提交。", {
        code: "INVALID_RESPONSE", uncertain: true,
      });
      state.intent.taskId = data.id;
      state.intent.status = "accepted";
    } catch (error) {
      state.error = error;
      if (isTaskId(error.taskId)) {
        state.intent.taskId = error.taskId;
        state.intent.status = "recorded";
      } else if (!error.uncertain && error.status >= 400 && error.status < 500 && error.code !== "IDEMPOTENCY_CONFLICT") {
        state.intent = null;
      }
    } finally {
      persist();
      state.busy = false;
    }
  }

  return {
    async submit(payload) {
      if (state.busy || state.intent) return;
      state.intent = { key: createKey(), payload: JSON.parse(JSON.stringify(payload)), taskId: "", status: "uncertain" };
      await send();
    },
    // User-triggered lookup by replaying the exact frozen request/key. The API never republishes it.
    confirm: send,
    newTask() {
      if (state.busy) return;
      state.intent = null;
      state.error = null;
      persist();
    },
  };
}
