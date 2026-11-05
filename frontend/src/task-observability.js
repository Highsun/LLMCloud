import { ApiError } from "./api.js";
import { isTaskId } from "./task-submission.js";

// M4 contract 1.0.0; checked against the generated x-limits in consumer tests.
export const OBSERVABILITY_LIMITS = Object.freeze({
  interval: 2000, pageSize: 200, pagesPerRound: 5, visibleRecords: 10000, logTail: 100,
});
const statuses = ["PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED"];
const terminal = (status) => status === "COMPLETED" || status === "FAILED";
const integer = (value) => Number.isSafeInteger(value) && value >= 0;
const nonnegative = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const invalid = () => new ApiError("观测响应与正式契约不一致，请重试或联系服务端。", { code: "INVALID_RESPONSE" });
const requireValue = (condition) => { if (!condition) throw invalid(); };
function fields(value, names) {
  requireValue(object(value) && Object.keys(value).length === names.length && names.every((key) => Object.hasOwn(value, key)));
}
function envelope(page, id) {
  requireValue(page.contract_version === "1.0.0" && isTaskId(page.task_id) && page.task_id === id &&
    statuses.includes(page.task_status) && ["ready", "not_created"].includes(page.source_state));
}

export function validateMetricsPage(page, id, query, previous = null) {
  fields(page, ["contract_version", "task_id", "task_status", "source_state", "source_id", "items", "next_cursor", "has_more", "tail_incomplete"]);
  envelope(page, id);
  requireValue(Array.isArray(page.items) && page.items.length <= query.limit &&
    integer(page.next_cursor) && typeof page.has_more === "boolean" && typeof page.tail_incomplete === "boolean");
  if (page.source_state === "not_created") {
    requireValue(query.cursor === 0 && !query.source_id && page.task_status !== "COMPLETED" &&
      page.source_id === null && !page.items.length && page.next_cursor === 0 && !page.has_more && !page.tail_incomplete);
    return page;
  }
  requireValue(typeof page.source_id === "string" && /^[a-f0-9]{64}$/.test(page.source_id) &&
    (!query.source_id || query.source_id === page.source_id));
  requireValue(!(page.task_status === "COMPLETED" && page.tail_incomplete));
  let last = previous;
  for (const point of page.items) {
    fields(point, ["contract_version", "kind", "step", "total_steps", "loss", "learning_rate", "epoch", "recorded_at", "offset"]);
    requireValue(point.contract_version === "1.0.0" && ["train", "eval"].includes(point.kind) &&
      integer(point.step) && point.step > 0 && integer(point.total_steps) && point.total_steps >= point.step &&
      nonnegative(point.loss) && nonnegative(point.learning_rate) && nonnegative(point.epoch) &&
      typeof point.recorded_at === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$/.test(point.recorded_at) &&
      Number.isFinite(Date.parse(point.recorded_at)) && integer(point.offset) && point.offset >= query.cursor);
    requireValue(!last || (point.offset > last.offset && point.total_steps === last.total_steps &&
      (point.step > last.step || (point.step === last.step && last.kind === "train" && point.kind === "eval"))));
    last = point;
  }
  if (page.items.length) {
    requireValue(page.items[0].offset === query.cursor && page.next_cursor > page.items.at(-1).offset);
  } else requireValue(page.next_cursor === query.cursor && !page.has_more);
  return page;
}

export function validateLogsPage(page, id, tail = OBSERVABILITY_LIMITS.logTail) {
  fields(page, ["contract_version", "task_id", "task_status", "source_state", "lines", "truncated", "tail_incomplete", "filtered_lines"]);
  envelope(page, id);
  requireValue(Array.isArray(page.lines) && page.lines.length <= tail &&
    page.lines.every((line) => typeof line === "string" && !/[\r\n\0]/.test(line) && line.isWellFormed() &&
      new TextEncoder().encode(line).length <= 65536) &&
    typeof page.truncated === "boolean" && typeof page.tail_incomplete === "boolean" &&
    integer(page.filtered_lines) && page.filtered_lines <= tail &&
    new TextEncoder().encode(JSON.stringify(page)).length <= 262144);
  if (page.source_state === "not_created") requireValue(page.task_status !== "COMPLETED" &&
    !page.lines.length && !page.truncated && !page.tail_incomplete && !page.filtered_lines);
  return page;
}

const metricsState = () => ({
  points: [], cursor: 0, sourceId: null, sourceState: null, lastRecord: null, latestTrain: null,
  hasMore: false, tailIncomplete: false, dropped: 0, resetNotice: false,
  error: null, loading: false, done: false,
});

export function createTaskObservability({ state, request, supports }) {
  let generation = 0, controller = null, running = null, active = true;
  const can = (kind) => supports(`/tasks/{task_id}/${kind}`);
  const initialize = (id = null, status = null) => Object.assign(state, {
    taskId: id, taskStatus: status, metrics: metricsState(),
    logs: { page: null, error: null, loading: false, done: false },
  });
  initialize();

  function pause() {
    active = false;
    generation++;
    controller?.abort();
    controller = null;
    running = null;
    state.metrics.loading = state.logs.loading = false;
  }
  function select(id, status = null) {
    if (id !== null && !isTaskId(id)) throw invalid();
    const wasActive = active;
    pause();
    initialize(id, status);
    active = wasActive;
  }
  function setStatus(status) {
    if (!statuses.includes(status)) throw invalid();
    if (status !== state.taskStatus) {
      state.metrics.done = state.logs.done = false;
      state.taskStatus = status;
    }
  }
  function needsRefresh() {
    return Boolean(state.taskId && statuses.includes(state.taskStatus) &&
      ((can("metrics") && !state.metrics.done) || (can("logs") && !state.logs.done)));
  }

  async function readMetrics(current, id, signal) {
    const fresh = () => current === generation && id === state.taskId && can("metrics");
    if (!fresh() || state.metrics.done) return;
    const metrics = state.metrics;
    metrics.loading = true;
    let reset = false;
    try {
      for (let count = 0; count < OBSERVABILITY_LIMITS.pagesPerRound && fresh(); count++) {
        const query = { cursor: metrics.cursor, limit: OBSERVABILITY_LIMITS.pageSize };
        if (metrics.sourceId) query.source_id = metrics.sourceId;
        let page;
        try {
          page = await request(`/tasks/${encodeURIComponent(id)}/metrics?${new URLSearchParams(query)}`, { signal });
          if (!fresh()) return;
          validateMetricsPage(page, id, query, metrics.lastRecord);
        } catch (error) {
          if (!fresh()) return;
          if (error.status === 409 && error.code === "METRICS_CURSOR_INVALID" && !reset) {
            Object.assign(metrics, metricsState(), { loading: true, resetNotice: true });
            reset = true;
            continue;
          }
          throw error;
        }
        const points = new Map(metrics.points.map((point) => [`${metrics.sourceId}:${point.offset}`, point]));
        for (const point of page.items) points.set(`${page.source_id}:${point.offset}`, point);
        const all = [...points.values()];
        const removed = Math.max(0, all.length - OBSERVABILITY_LIMITS.visibleRecords);
        metrics.points = all.slice(removed);
        metrics.dropped += removed;
        metrics.latestTrain = page.items.findLast((point) => point.kind === "train") ?? metrics.latestTrain;
        metrics.lastRecord = page.items.at(-1) ?? metrics.lastRecord;
        metrics.sourceState = page.source_state;
        metrics.sourceId = page.source_id;
        metrics.cursor = page.next_cursor;
        metrics.hasMore = page.has_more;
        metrics.tailIncomplete = page.tail_incomplete;
        metrics.error = null;
        // An observation snapshot never changes the authoritative TaskDetail status.
        metrics.done = terminal(state.taskStatus) && page.task_status === state.taskStatus && !page.has_more;
        if (!page.has_more) break;
      }
    } catch (error) {
      if (fresh()) metrics.error = error;
    } finally {
      if (fresh()) metrics.loading = false;
    }
  }

  async function readLogs(current, id, signal) {
    const fresh = () => current === generation && id === state.taskId && can("logs");
    if (!fresh() || state.logs.done) return;
    const logs = state.logs;
    logs.loading = true;
    try {
      const page = await request(`/tasks/${encodeURIComponent(id)}/logs?tail=${OBSERVABILITY_LIMITS.logTail}`, { signal });
      if (!fresh()) return;
      validateLogsPage(page, id);
      logs.page = page;
      logs.error = null;
      // On the last round, fetch a final log snapshot after draining metrics.
      logs.done = terminal(state.taskStatus) && page.task_status === state.taskStatus &&
        (!can("metrics") || state.metrics.done);
    } catch (error) {
      if (fresh()) logs.error = error;
    } finally {
      if (fresh()) logs.loading = false;
    }
  }

  function refresh({ force = false } = {}) {
    if ((!active && !force) || !state.taskId || !statuses.includes(state.taskStatus)) return Promise.resolve();
    if (running) return running;
    if (force) state.metrics.done = state.logs.done = false;
    if (!needsRefresh()) return Promise.resolve();
    const current = generation, id = state.taskId;
    controller = new AbortController();
    const signal = controller.signal;
    const promise = (async () => {
      await readMetrics(current, id, signal);
      if (current === generation) await readLogs(current, id, signal);
    })().finally(() => {
      if (current === generation) { running = null; controller = null; }
    });
    running = promise;
    return promise;
  }
  return { select, setStatus, refresh, needsRefresh, pause, resume() { active = true; }, dispose: pause };
}
