export const baseUrl = (
  import.meta.env?.VITE_API_BASE_URL || "/api/v1"
).replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message,
    {
      status = 0,
      code = "NETWORK_ERROR",
      details = [],
      requestId = "",
      truncated = false,
      uncertain = false,
    } = {},
  ) {
    super(message);
    Object.assign(this, {
      status,
      code,
      details,
      requestId,
      truncated,
      uncertain,
    });
  }
}

function responseError(status, data, requestId, mutation = false) {
  const error = data?.error;
  return new ApiError(
    error?.message ||
      (status === 404
        ? "接口尚未就绪，或资源不存在。"
        : status === 409
          ? "资源当前不可用，请稍后重试。"
          : `服务请求失败（HTTP ${status}），请稍后重试。`),
    {
      status,
      code: error?.code || `HTTP_${status}`,
      details: Array.isArray(error?.details) ? error.details : [],
      requestId: error?.request_id || requestId || "",
      truncated: error?.details_truncated === true,
      uncertain: mutation && status >= 500,
    },
  );
}

export async function request(
  path,
  { method = "GET", body, timeout = 10000, signal, raw = false } = {},
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  try {
    const response = await fetch(raw ? path : `${baseUrl}${path}`, {
      method,
      signal: controller.signal,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (raw === "blob" && response.ok) return response.blob();
    const data = await response.json().catch(() => null);
    if (!response.ok)
      throw responseError(
        response.status,
        data,
        response.headers.get("X-Request-ID"),
        method !== "GET",
      );
    if (data === null)
      throw new ApiError("接口没有返回有效的 JSON 数据。", {
        code: "INVALID_RESPONSE",
        uncertain: method !== "GET",
      });
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      controller.signal.aborted
        ? "请求已取消或超时，请检查服务连接。"
        : "无法连接服务，请检查网络及后端是否启动。",
      { uncertain: method !== "GET" },
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export async function getHealth() {
  const data = await request("/health", { timeout: 5000 });
  if (data.status !== "ok" || typeof data.service !== "string")
    throw new ApiError("健康检查响应格式异常。", { code: "INVALID_RESPONSE" });
  return data;
}

export function uploadDataset(file, name, onProgress, signal) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const form = new FormData();
    form.append("file", file);
    if (name.trim()) form.append("name", name.trim());
    xhr.open("POST", `${baseUrl}/datasets`);
    xhr.timeout = 120000;
    xhr.upload.onprogress = (event) =>
      onProgress(
        event.lengthComputable
          ? Math.round((event.loaded / event.total) * 100)
          : null,
      );
    const abort = () => xhr.abort();
    const cleanup = () => signal?.removeEventListener("abort", abort);
    xhr.onload = () => {
      cleanup();
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = null;
      }
      if (xhr.status === 201 && data?.id) resolve(data);
      else if (xhr.status >= 200 && xhr.status < 300)
        reject(
          new ApiError("上传响应与契约不一致，请先刷新列表确认保存结果。", {
            code: "INVALID_RESPONSE",
            uncertain: true,
          }),
        );
      else
        reject(
          responseError(
            xhr.status,
            data,
            xhr.getResponseHeader("X-Request-ID"),
            true,
          ),
        );
    };
    const interrupted = (message) => {
      cleanup();
      reject(new ApiError(message, { uncertain: true }));
    };
    xhr.onerror = () =>
      interrupted(
        "上传连接中断。请先刷新数据集列表，确认是否已保存，再决定是否重传。",
      );
    xhr.ontimeout = () =>
      interrupted("上传请求超时。请先刷新列表确认保存结果，避免重复上传。");
    xhr.onabort = () =>
      interrupted("上传已取消；服务端可能已收到文件，请刷新列表确认结果。");
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) {
      interrupted("上传已取消。");
      return;
    }
    xhr.send(form);
  });
}

export function saveFile(content, filename, type = "application/json") {
  const url = URL.createObjectURL(
    content instanceof Blob ? content : new Blob([content], { type }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
