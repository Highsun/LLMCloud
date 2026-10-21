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

export async function loadDatasets(
  page = workspace.datasetPage,
  pageSize = workspace.pageSize,
) {
  if (workspace.datasetLoading) return;
  workspace.datasetLoading = true;
  workspace.datasetError = null;
  try {
    const data = await request(`/datasets?page=${page}&page_size=${pageSize}`);
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
    workspace.datasetError = error;
    workspace.datasets = null;
  } finally {
    workspace.datasetLoading = false;
  }
}

export async function loadTasks(page = workspace.taskPage) {
  if (workspace.taskLoading) return;
  workspace.taskLoading = true;
  workspace.taskError = null;
  try {
    const data = await request(`/tasks?page=${page}&page_size=20`);
    if (!Array.isArray(data.items) || !Number.isInteger(data.total))
      throw new ApiError(
        "任务列表接口待联调：预期返回分页对象与 items、total 字段。",
        { code: "INVALID_RESPONSE" },
      );
    workspace.tasks = data;
    workspace.taskPage = page;
  } catch (error) {
    workspace.taskError = error;
    workspace.tasks = null;
  } finally {
    workspace.taskLoading = false;
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
      ? loadTasks(1)
      : Promise.resolve().then(() => {
          workspace.tasks = null;
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
