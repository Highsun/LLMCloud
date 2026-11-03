import { ApiError } from "./api.js";
import { isTaskId } from "./task-submission.js";

export function validateTaskDetail(data, id) {
  if (!data || data.id !== id || !isTaskId(data.id) ||
      !["PENDING", "QUEUED", "RUNNING", "COMPLETED", "FAILED"].includes(data.status) ||
      !data.config || typeof data.config !== "object" || Array.isArray(data.config) ||
      !Number.isSafeInteger(data.current_step) || data.current_step < 0 ||
      !(data.total_steps === null || (Number.isSafeInteger(data.total_steps) && data.total_steps > 0)) ||
      !(data.progress === null || (Number.isFinite(data.progress) && data.progress >= 0 && data.progress <= 1))) {
    throw new ApiError("任务详情响应与 TaskDetail 契约不一致。", { code: "INVALID_RESPONSE" });
  }
  return data;
}

export function progressLabel(task) {
  if (task.progress === null || task.progress === undefined) return "进度待确认";
  const percent = `${Math.round(task.progress * 100)}%`;
  return task.status === "RUNNING" && task.progress === 1 ? `${percent} · 等待产物校验与状态提交` : percent;
}
