<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { ApiError, baseUrl, request, saveFile } from "../api";
import {
  formatDate,
  loadTasks,
  supports,
  taskStates,
  workspace,
} from "../workspace";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";
import ErrorNotice from "./ErrorNotice.vue";
import LossChart from "./LossChart.vue";

const filter = ref("ALL");
const selected = ref(null);
const tab = ref("metrics");
const metrics = ref([]);
const logs = ref("");
const detailError = ref(null);
const metricsError = ref(null);
const logsError = ref(null);
const downloading = ref(false);
const downloadError = ref(null);
const polling = ref(true);
const detailLoading = ref(false);
const visibleTasks = computed(() =>
  (workspace.tasks?.items || []).filter(
    (task) => filter.value === "ALL" || task.status === filter.value,
  ),
);
const totalPages = computed(() =>
  Math.ceil((workspace.tasks?.total || 0) / 20),
);
let timer,
  alive = true,
  sequence = 0,
  detailController;
const stateOf = (status) =>
  taskStates[status] || { label: status || "未知", tone: "neutral" };

async function readDetail(id, isNew = false) {
  if (detailLoading.value && !isNew) return;
  detailController?.abort();
  detailController = new AbortController();
  const signal = detailController.signal;
  const current = ++sequence;
  detailLoading.value = true;
  if (isNew) {
    selected.value = { id };
    metrics.value = [];
    logs.value = "";
    detailError.value = null;
    metricsError.value = null;
    logsError.value = null;
    downloadError.value = null;
  }
  try {
    const data = await request(`/tasks/${encodeURIComponent(id)}`, { signal });
    if (current !== sequence || !alive) return;
    selected.value = data;
    detailError.value = null;
    const after = metrics.value.length
      ? Math.max(...metrics.value.map((point) => point.step))
      : -1;
    await Promise.allSettled([
      supports("/tasks/{task_id}/metrics")
        ? request(
            `/tasks/${encodeURIComponent(id)}/metrics${after >= 0 ? `?after_step=${after}` : ""}`,
            { signal },
          )
            .then((result) => {
              if (current !== sequence || !alive) return;
              const points = Array.isArray(result) ? result : result.items;
              if (!Array.isArray(points))
                throw new ApiError("指标响应格式待联调。");
              const merged = new Map(
                metrics.value.map((point) => [point.step, point]),
              );
              for (const point of points)
                if (Number.isFinite(point.step) && Number.isFinite(point.loss))
                  merged.set(point.step, point);
              metrics.value = [...merged.values()].toSorted(
                (a, b) => a.step - b.step,
              );
              metricsError.value = null;
            })
            .catch((error) => {
              if (current === sequence && alive) metricsError.value = error;
            })
        : Promise.resolve(),
      supports("/tasks/{task_id}/logs")
        ? request(`/tasks/${encodeURIComponent(id)}/logs?tail=100`, { signal })
            .then((result) => {
              if (current !== sequence || !alive) return;
              const text =
                typeof result === "string"
                  ? result
                  : Array.isArray(result.lines)
                    ? result.lines.join("\n")
                    : result.logs;
              if (typeof text !== "string")
                throw new ApiError("日志响应格式待联调。");
              logs.value = text;
              logsError.value = null;
            })
            .catch((error) => {
              if (current === sequence && alive) logsError.value = error;
            })
        : Promise.resolve(),
    ]);
  } catch (error) {
    if (current === sequence && alive) detailError.value = error;
  } finally {
    if (current === sequence && alive) detailLoading.value = false;
  }
}
async function tick() {
  if (!alive) return;
  if (polling.value && !document.hidden && supports("/tasks")) {
    await loadTasks();
    if (
      alive &&
      selected.value &&
      !["COMPLETED", "FAILED"].includes(selected.value.status)
    )
      await readDetail(selected.value.id);
  }
  if (alive) timer = setTimeout(tick, 2000);
}
async function download() {
  if (downloading.value || selected.value?.status !== "COMPLETED") return;
  downloading.value = true;
  downloadError.value = null;
  try {
    const blob = await request(
      `${baseUrl}/tasks/${encodeURIComponent(selected.value.id)}/adapter`,
      { raw: "blob", timeout: 60000 },
    );
    saveFile(blob, `adapter-${selected.value.id}.zip`);
  } catch (error) {
    downloadError.value = error;
  } finally {
    downloading.value = false;
  }
}
function closeDetail() {
  sequence++;
  detailController?.abort();
  selected.value = null;
  detailLoading.value = false;
}
onMounted(() => {
  timer = setTimeout(tick, 2000);
});
onBeforeUnmount(() => {
  alive = false;
  sequence++;
  clearTimeout(timer);
  detailController?.abort();
});
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">TRAINING MONITOR</div>
      <h1>训练任务</h1>
      <p>从排队到交付，追踪每一次训练的真实进展。</p>
    </div>
    <a class="button primary" href="#training"
      ><AppIcon name="plus" />新建微调</a
    >
  </div>
  <section class="panel">
    <div class="task-toolbar">
      <div class="segmented" aria-label="筛选当前页任务">
        <button
          v-for="[value, label] in [
            ['ALL', '全部'],
            ['RUNNING', '训练中'],
            ['QUEUED', '排队中'],
            ['COMPLETED', '已完成'],
            ['FAILED', '失败'],
          ]"
          :key="value"
          :class="{ active: filter === value }"
          :aria-pressed="filter === value"
          @click="filter = value"
        >
          {{ label }}
        </button>
      </div>
      <div class="toolbar-actions">
        <label class="checkbox-label"
          ><input v-model="polling" type="checkbox" />每 2 秒刷新</label
        ><button
          class="icon-button"
          aria-label="刷新任务"
          :disabled="!supports('/tasks') || workspace.taskLoading"
          @click="loadTasks()"
        >
          <AppIcon
            name="refresh"
            :class="{ spinning: workspace.taskLoading }"
            size="17"
          />
        </button>
      </div>
    </div>
    <ErrorNotice :error="workspace.taskError" />
    <div
      v-if="workspace.taskLoading && !workspace.tasks"
      class="loading-state"
      role="status"
    >
      <span class="loader" />正在读取任务…
    </div>
    <div v-else-if="visibleTasks.length" class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>训练步数</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in visibleTasks" :key="task.id">
            <td>
              <strong class="mono">{{ task.id.slice(0, 8) }}</strong
              ><small>{{ task.base_model?.split("/").at(-1) || "—" }}</small>
            </td>
            <td>
              <span class="badge" :class="stateOf(task.status).tone"
                ><i />{{ stateOf(task.status).label }}</span
              >
            </td>
            <td>
              {{ task.current_step ?? "—" }} / {{ task.total_steps || "—" }}
            </td>
            <td>{{ formatDate(task.created_at) }}</td>
            <td>
              <button class="text-button" @click="readDetail(task.id, true)">
                查看详情<AppIcon name="chevron" size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState
      v-else
      icon="activity"
      :title="
        workspace.tasks
          ? workspace.tasks.total
            ? '当前筛选下没有任务'
            : '你的第一场实验，从这里开始'
          : '等待训练服务就绪'
      "
      :description="
        workspace.tasks
          ? '创建训练任务后，即可查看排队状态、训练指标和模型产物。'
          : '你可以先在配置微调中准备参数，任务服务就绪后再提交训练。'
      "
      ><a class="button secondary" href="#training"
        >配置微调<AppIcon name="arrow" size="16" /></a
    ></EmptyState>
    <div v-if="workspace.tasks" class="pagination">
      <span
        >本页 {{ workspace.tasks.items.length }} 条 / 共
        {{ workspace.tasks.total }} 条 · 筛选当前页</span
      >
      <div>
        <button
          class="icon-button"
          aria-label="上一页任务"
          :disabled="workspace.taskPage <= 1 || workspace.taskLoading"
          @click="loadTasks(workspace.taskPage - 1)"
        >
          <AppIcon name="chevron" class="rotate" size="16" /></button
        ><span>{{ workspace.taskPage }} / {{ totalPages || 1 }}</span
        ><button
          class="icon-button"
          aria-label="下一页任务"
          :disabled="workspace.taskPage >= totalPages || workspace.taskLoading"
          @click="loadTasks(workspace.taskPage + 1)"
        >
          <AppIcon name="chevron" size="16" />
        </button>
      </div>
    </div>
    <div class="panel-footer">
      <span>单 GPU 串行执行 · 训练与推理互斥</span
      ><span>状态来源：后端业务记录</span>
    </div>
  </section>
  <section v-if="selected" class="panel task-detail">
    <div class="section-heading">
      <div>
        <h2>
          任务详情
          <span class="badge" :class="stateOf(selected.status).tone">{{
            stateOf(selected.status).label
          }}</span>
        </h2>
        <p class="mono subtle">{{ selected.id }}</p>
      </div>
      <button
        class="icon-button"
        aria-label="关闭任务详情"
        @click="closeDetail"
      >
        <AppIcon name="close" />
      </button>
    </div>
    <ErrorNotice :error="detailError" />
    <div v-if="selected.status" class="detail-stats">
      <div>
        <span>训练步数</span
        ><strong
          >{{ selected.current_step ?? "—" }}
          <small>/ {{ selected.total_steps || "—" }}</small></strong
        >
      </div>
      <div>
        <span>最新 Loss</span
        ><strong>{{
          metrics.length ? metrics.at(-1).loss.toFixed(4) : "—"
        }}</strong>
      </div>
      <div>
        <span>开始时间</span
        ><strong class="time-value">{{
          formatDate(selected.started_at)
        }}</strong>
      </div>
      <div>
        <span>结束时间</span
        ><strong class="time-value">{{
          formatDate(selected.finished_at)
        }}</strong>
      </div>
    </div>
    <p v-if="selected.error_message" class="notice error-notice" role="alert">
      {{ selected.error_message }}
    </p>
    <div class="tabs" role="tablist" aria-label="任务详情">
      <button
        v-for="[value, label] in [
          ['metrics', 'Loss 曲线'],
          ['logs', '运行日志'],
          ['config', '配置快照'],
        ]"
        :id="`tab-${value}`"
        :key="value"
        role="tab"
        :aria-selected="tab === value"
        :class="{ active: tab === value }"
        @click="tab = value"
      >
        {{ label }}
      </button>
    </div>
    <div role="tabpanel" :aria-labelledby="`tab-${tab}`">
      <template v-if="tab === 'metrics'"
        ><ErrorNotice :error="metricsError" /><LossChart :points="metrics" />
        <p v-if="!supports('/tasks/{task_id}/metrics')" class="field-help">
          指标接口尚未就绪。
        </p></template
      ><template v-else-if="tab === 'logs'"
        ><ErrorNotice :error="logsError" />
        <pre class="terminal">{{
          logs ||
          (supports("/tasks/{task_id}/logs")
            ? "等待服务端日志…"
            : "日志服务尚未就绪。")
        }}</pre>
        <p class="field-help">仅展示当前任务最近 100 行日志。</p></template
      >
      <pre v-else class="config-snapshot">{{
        JSON.stringify(
          selected.config || selected.training_config || {},
          null,
          2,
        )
      }}</pre>
    </div>
    <ErrorNotice :error="downloadError" />
    <div class="panel-footer">
      <span>{{
        selected.status === "COMPLETED"
          ? "训练已完成，可下载服务端校验通过的产物。"
          : "仅完成的任务可下载 Adapter。"
      }}</span
      ><button
        class="button secondary"
        :disabled="
          selected.status !== 'COMPLETED' ||
          !supports('/tasks/{task_id}/adapter') ||
          downloading
        "
        @click="download"
      >
        <AppIcon name="download" size="16" />{{
          downloading ? "准备下载…" : "下载 Adapter"
        }}
      </button>
    </div>
  </section>
  <div class="status-explainer">
    <span v-for="(state, key) in taskStates" :key="key"
      ><i :class="state.tone" />{{ state.label }} <small>{{ key }}</small></span
    >
  </div>
</template>
