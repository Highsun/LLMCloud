import { reactive } from "vue";
import { ApiError, baseUrl, getHealth, request } from "./api";

export const workspace = reactive({
  health: null,
  healthError: null,
  checking: false,
  checkedAt: null,
  models: [],
  modelError: null,
  paths: null,
  discoveryError: null,
  datasets: null,
  datasetError: null,
  datasetLoading: false,
  datasetPage: 1,
  pageSize: 20,
  tasks: null,
  taskError: null,
  taskLoading: false,
  taskPage: 1,
  taskStatus: "ALL",
  taskPagination: null,
});

export function supports(path, method = "get") {
  const normalize = (value) => value.replace(/\{[^}]+\}/g, "{}");
  const target = normalize(
    `${new URL(baseUrl, window.location.origin).pathname}${path}`,
  );
  return Object.entries(workspace.paths || {}).some(
    ([key, value]) => normalize(key) === target && Boolean(value[method]),
  );
}

let datasetRequestSequence = 0;
let datasetController;

export async function loadDatasets(
  page = workspace.datasetPage,
  pageSize = workspace.pageSize,
) {
  const sequence = ++datasetRequestSequence;
  datasetController?.abort();
  const controller = new AbortController();
  datasetController = controller;
  workspace.datasetLoading = true;
  workspace.datasetError = null;
  try {
    const data = await request(`/datasets?page=${page}&page_size=${pageSize}`, {
      signal: controller.signal,
    });
    if (sequence !== datasetRequestSequence) return;
    if (
      !Array.isArray(data.items) ||
      !Number.isInteger(data.total) ||
      !Number.isInteger(data.total_pages)
    )
      throw new ApiError("数据集列表响应与约定不一致。", {
        code: "INVALID_RESPONSE",
      });
    workspace.datasets = data;
    workspace.datasetPage = data.page;
    workspace.pageSize = data.page_size;
  } catch (error) {
    if (sequence !== datasetRequestSequence) return;
    workspace.datasetError = error;
    workspace.datasets = null;
  } finally {
    if (sequence === datasetRequestSequence) {
      workspace.datasetLoading = false;
      datasetController = null;
    }
  }
}

let taskRequestSequence = 0;
let taskController;
export const TASK_PAGE_SIZE = 20;

export function cancelTaskRequest() {
  ++taskRequestSequence;
  taskController?.abort();
  taskController = null;
  workspace.taskLoading = false;
}

export function selectTaskStatus(status) {
  return loadTasks(1, status);
}

// A polling tick must never supersede an in-flight user selection or page change.
export function pollTasks() {
  if (workspace.taskLoading) return Promise.resolve();
  return loadTasks();
}

export async function loadTasks(
  page = workspace.taskPage,
  status = workspace.taskStatus,
) {
  if (
    !Number.isSafeInteger(page) ||
    page < 1 ||
    (status !== "ALL" && !Object.hasOwn(taskStates, status))
  ) {
    throw new RangeError("任务查询页码或状态无效。");
  }
  const changed =
    page !== workspace.taskPage || status !== workspace.taskStatus;
  if (status !== workspace.taskStatus) workspace.taskPagination = null;
  const sequence = ++taskRequestSequence;
  taskController?.abort();
  const controller = new AbortController();
  taskController = controller;
  // Store the user's intent immediately, so refresh/polling cannot restore an old query.
  workspace.taskPage = page;
  workspace.taskStatus = status;
  if (changed) workspace.tasks = null;
  workspace.taskLoading = true;
  workspace.taskError = null;
  try {
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(TASK_PAGE_SIZE),
    });
    if (status !== "ALL") query.set("status", status);
    const data = await request(`/tasks?${query}`, {
      signal: controller.signal,
    });
    if (sequence !== taskRequestSequence) return;
    if (
      !Array.isArray(data.items) ||
      !Number.isSafeInteger(data.total) ||
      data.total < 0 ||
      data.page !== page ||
      data.page_size !== TASK_PAGE_SIZE ||
      data.total_pages !== Math.ceil(data.total / TASK_PAGE_SIZE) ||
      data.items.length > Math.min(TASK_PAGE_SIZE, data.total) ||
      (page > data.total_pages && data.items.length !== 0)
    )
      throw new ApiError(
        "任务列表响应与分页契约不一致，请刷新或联系服务维护者。",
        { code: "INVALID_RESPONSE" },
      );
    workspace.tasks = data;
    workspace.taskPagination = {
      total: data.total,
      total_pages: data.total_pages,
    };
  } catch (error) {
    if (sequence !== taskRequestSequence) return;
    workspace.taskError = error;
    workspace.tasks = null;
  } finally {
    if (sequence === taskRequestSequence) {
      workspace.taskLoading = false;
      taskController = null;
    }
  }
}

export async function refreshWorkspace() {
  if (workspace.checking) return;
  workspace.checking = true;
  workspace.healthError = null;
  workspace.modelError = null;
  workspace.discoveryError = null;
  await Promise.allSettled([
    getHealth()
      .then((data) => {
        workspace.health = data;
      })
      .catch((error) => {
        workspace.health = null;
        workspace.healthError = error;
      }),
    request("/models")
      .then((data) => {
        if (!Array.isArray(data)) throw new ApiError("模型目录响应格式异常。");
        workspace.models = data;
      })
      .catch((error) => {
        workspace.models = [];
        workspace.modelError = error;
      }),
    request(
      import.meta.env?.VITE_OPENAPI_URL ||
        new URL("/openapi.json", new URL(baseUrl, window.location.origin)).href,
      { raw: true },
    )
      .then((data) => {
        if (!data.paths || typeof data.paths !== "object")
          throw new ApiError("无法读取接口目录。");
        workspace.paths = data.paths;
      })
      .catch((error) => {
        workspace.paths = null;
        workspace.discoveryError = error;
      }),
  ]);
  await Promise.allSettled([
    supports("/datasets")
      ? loadDatasets(1)
      : Promise.resolve().then(() => {
          workspace.datasets = null;
          workspace.datasetError = null;
        }),
    supports("/tasks")
      ? loadTasks()
      : Promise.resolve().then(() => {
          cancelTaskRequest();
          workspace.tasks = null;
          workspace.taskPagination = null;
          workspace.taskError = null;
        }),
  ]);
  workspace.checkedAt = new Date();
  workspace.checking = false;
}

export const taskStates = {
  PENDING: { label: "待派发", tone: "neutral" },
  QUEUED: { label: "排队中", tone: "amber" },
  RUNNING: { label: "训练中", tone: "blue" },
  COMPLETED: { label: "已完成", tone: "green" },
  FAILED: { label: "失败", tone: "red" },
};
export function formatDate(value) {
  if (!value || Number.isNaN(new Date(value).getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}
export function formatBytes(value) {
  if (!Number.isFinite(value)) return "—";
  if (value < 1024) return `${value} B`;
  return `${(value / (value < 1048576 ? 1024 : 1048576)).toFixed(1)} ${value < 1048576 ? "KiB" : "MiB"}`;
}
