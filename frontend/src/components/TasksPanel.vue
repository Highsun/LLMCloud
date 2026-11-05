<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { request } from "../api";
import {
  formatDate,
  cancelTaskRequest,
  loadTasks,
  pollTasks,
  selectTaskStatus,
  submissionState,
  supports,
  taskStates,
  workspace,
} from "../workspace";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";
import ErrorNotice from "./ErrorNotice.vue";
import LossChart from "./LossChart.vue";
import TaskLogs from "./TaskLogs.vue";
import { createTaskPolling } from "../task-polling";
import { progressLabel, validateTaskDetail } from "../task-detail";
import { createTaskObservability } from "../task-observability";
import { createTaskDownload } from "../task-download";

const filter = computed(() => workspace.taskStatus);
const selected = ref(null);
const tab = ref("config");
const observations = reactive({});
const observer = createTaskObservability({ state: observations, request, supports });
const metrics = computed(() => observations.metrics.points);
const detailError = ref(null);
const downloadState = reactive({});
const downloader = createTaskDownload({ state: downloadState });
const downloading = computed(() => downloadState.busy);
const downloadError = computed(() => downloadState.error);
const polling = ref(true);
const detailLoading = ref(false);
const visibleTasks = computed(() => workspace.tasks?.items || []);
const totalPages = computed(() => workspace.taskPagination?.total_pages ?? 0);
let alive = true,
  sequence = 0,
  detailController;
const stateOf = (status) =>
  taskStates[status] || { label: status || "未知", tone: "neutral" };

async function readDetail(id, isNew = false, manual = false) {
  if (!supports('/tasks/{task_id}')) return;
  if (detailLoading.value && !isNew) return;
  detailController?.abort();
  detailController = new AbortController();
  const signal = detailController.signal;
  const current = ++sequence;
  detailLoading.value = true;
  if (isNew) {
    selected.value = { id };
    observer.select(id);
    downloader.select(id);
    detailError.value = null;
  }
  try {
    const data = await request(`/tasks/${encodeURIComponent(id)}`, { signal });
    if (current !== sequence || !alive) return;
    selected.value = validateTaskDetail(data, id);
    detailError.value = null;
    observer.setStatus(selected.value.status);
    observer.refresh({ force: manual || !polling.value });
  } catch (error) {
    if (current === sequence && alive) detailError.value = error;
  } finally {
    if (current === sequence && alive) detailLoading.value = false;
  }
}
const taskPolling = createTaskPolling({
  shouldPoll: () =>
    alive && polling.value && !document.hidden && supports("/tasks"),
  async refresh() {
    await Promise.allSettled([
      pollTasks(),
      selected.value && !["COMPLETED", "FAILED"].includes(selected.value.status)
        ? readDetail(selected.value.id) : Promise.resolve(),
    ]);
  },
});
const observationPolling = createTaskPolling({
  shouldPoll: () => alive && polling.value && !document.hidden && observer.needsRefresh(),
  refresh: () => observer.refresh(),
});
function updatePolling() {
  if (polling.value && !document.hidden) {
    taskPolling.start();
    observationPolling.start();
    observer.resume();
    observer.refresh();
  } else {
    taskPolling.stop();
    observationPolling.stop();
    observer.pause();
  }
  if (document.hidden) {
    cancelTaskRequest();
    ++sequence;
    detailController?.abort();
    detailLoading.value = false;
  }
}
function closeDetail() {
  sequence++;
  detailController?.abort();
  observer.select(null);
  downloader.select(null);
  selected.value = null;
  detailLoading.value = false;
}
onMounted(() => {
  if (!document.hidden && supports("/tasks") && !workspace.taskLoading)
    loadTasks();
  document.addEventListener("visibilitychange", updatePolling);
  updatePolling();
});
watch(polling, updatePolling);
watch(() => supports('/tasks/{task_id}'), (available) => {
  if (available && submissionState.intent?.taskId && !selected.value && typeof document !== 'undefined' && !document.hidden)
    readDetail(submissionState.intent.taskId, true);
}, { immediate: true });
watch(() => [supports('/tasks/{task_id}/metrics'), supports('/tasks/{task_id}/logs')], () => {
  observer.pause();
  updatePolling();
});
watch(() => supports('/tasks/{task_id}/adapter'), (available) => {
  if (!available) downloader.cancel();
});
watch(() => selected.value?.status, (status) => {
  if (status !== 'COMPLETED') downloader.cancel();
});
onBeforeUnmount(() => {
  alive = false;
  sequence++;
  taskPolling.stop();
  observationPolling.stop();
  observer.dispose();
  downloader.dispose();
  document.removeEventListener("visibilitychange", updatePolling);
  cancelTaskRequest();
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
    <p v-if="submissionState.intent?.taskId" class="field-help">
      最近提交：<span class="mono">{{ submissionState.intent.taskId }}</span>
      <button class="text-button" :disabled="!supports('/tasks/{task_id}')" @click="readDetail(submissionState.intent.taskId, true)">查询原任务</button>
    </p>
    <div class="task-toolbar">
      <div class="segmented" aria-label="按状态筛选任务">
        <button
          v-for="[value, label] in [
            ['ALL', '全部'],
            ['PENDING', '待派发'],
            ['RUNNING', '训练中'],
            ['QUEUED', '排队中'],
            ['COMPLETED', '已完成'],
            ['FAILED', '失败'],
          ]"
          :key="value"
          :class="{ active: filter === value }"
          :aria-pressed="filter === value"
          :disabled="!supports('/tasks')"
          @click="selectTaskStatus(value)"
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
          :disabled="!supports('/tasks')"
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
    <p
      v-if="workspace.taskLoading && workspace.tasks"
      class="field-help"
      role="status"
    >
      正在刷新任务…
    </p>
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
              {{ task.current_step ?? "—" }} / {{ task.total_steps ?? "—" }}
              <small>{{ progressLabel(task) }}</small>
            </td>
            <td>{{ formatDate(task.created_at) }}</td>
            <td>
              <button class="text-button" :disabled="!supports('/tasks/{task_id}')" @click="readDetail(task.id, true)">
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
        workspace.taskError
          ? '任务列表读取失败'
          : workspace.tasks
            ? workspace.tasks.total > 0
              ? '当前页没有任务'
              : filter === 'ALL'
                ? '还没有训练任务'
                : '当前状态下没有任务'
            : '等待训练服务就绪'
      "
      :description="
        workspace.taskError
          ? '请重试刷新，也可以切换状态重新查询。'
          : workspace.tasks
            ? workspace.tasks.total > 0
              ? '任务数量可能已变化，请返回上一页或重新选择状态。'
              : '创建训练任务后，即可查看排队状态、训练指标和模型产物。'
            : '你可以先在配置微调中准备参数，任务服务就绪后再提交训练。'
      "
      ><a class="button secondary" href="#training"
        >配置微调<AppIcon name="arrow" size="16" /></a
    ></EmptyState>
    <div v-if="workspace.taskPagination" class="pagination">
      <span
        >本页 {{ workspace.tasks?.items.length ?? "—" }} 条 / 共
        {{ workspace.taskPagination.total }} 条 ·
        {{ filter === "ALL" ? "全部状态" : taskStates[filter].label }}</span
      >
      <div>
        <button
          class="icon-button"
          aria-label="上一页任务"
          :disabled="
            !supports('/tasks') || workspace.taskPage <= 1 || totalPages === 0
          "
          @click="loadTasks(workspace.taskPage - 1)"
        >
          <AppIcon name="chevron" class="rotate" size="16" /></button
        ><span
          >{{ totalPages ? workspace.taskPage : 0 }} / {{ totalPages }}</span
        ><button
          class="icon-button"
          aria-label="下一页任务"
          :disabled="!supports('/tasks') || workspace.taskPage >= totalPages"
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
    <p v-if="detailLoading" class="field-help" role="status">正在读取任务详情…</p>
    <div class="detail-actions">
      <button class="text-button" :disabled="detailLoading || !supports('/tasks/{task_id}')" @click="readDetail(selected.id, false, true)">刷新任务详情</button>
      <button class="text-button" :disabled="!selected.status || observations.metrics.loading || observations.logs.loading || (!supports('/tasks/{task_id}/metrics') && !supports('/tasks/{task_id}/logs'))" @click="observer.refresh({ force: true })">刷新指标与日志</button>
    </div>
    <div v-if="selected.status" class="detail-stats">
      <div>
        <span>训练步数</span
        ><strong
          >{{ selected.current_step ?? "—" }}
          <small>/ {{ selected.total_steps ?? "—" }}</small></strong
        >
        <small class="task-progress-label">{{ progressLabel(selected) }}</small>
      </div>
      <div>
        <span>最新训练 Loss</span
        ><strong>{{
          observations.metrics.latestTrain?.loss.toFixed(4) ?? "—"
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
    <p v-if="selected.error_code || selected.error_message" class="notice error-notice task-failure-notice" role="alert">
      <strong>{{ selected.error_code }}</strong> {{ selected.error_message }}
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
        :disabled="value !== 'config' && !supports(`/tasks/{task_id}/${value}`)"
        @click="tab = value"
      >
        {{ label }}
      </button>
    </div>
    <div role="tabpanel" :aria-labelledby="`tab-${tab}`">
      <template v-if="tab === 'metrics'"
        ><ErrorNotice :error="observations.metrics.error" />
        <p v-if="observations.metrics.loading" class="field-help" role="status">正在读取真实指标…</p>
        <p v-if="observations.metrics.hasMore" class="notice" role="status">仍有历史指标待补拉。{{ polling ? '正在分批读取。' : '请手动刷新或开启自动刷新。' }}</p>
        <p v-if="observations.metrics.dropped" class="notice" role="status">仅展示最近 10,000 条指标记录。任务成功完成后，可从产物包获取完整指标。</p>
        <p v-if="observations.metrics.resetNotice" class="field-help" role="status">指标来源或游标已变化，已清除旧记录并从头重新读取。</p>
        <p v-if="observations.metrics.tailIncomplete" class="notice" role="status">指标尾部存在未完成行，仅展示前面完整的记录。</p>
        <p v-if="observations.metrics.done && !metrics.length" class="field-help">任务已结束，没有可展示的指标记录。</p>
        <LossChart :points="metrics" />
        <p v-if="!supports('/tasks/{task_id}/metrics')" class="field-help">
          指标接口尚未就绪。
        </p></template
      ><template v-else-if="tab === 'logs'"
        ><TaskLogs v-if="supports('/tasks/{task_id}/logs')" :key="selected.id"
          :page="observations.logs.page" :error="observations.logs.error"
          :loading="observations.logs.loading" :task-status="selected.status" />
        <p v-else class="field-help">日志服务尚未就绪。</p></template>
      <pre v-else class="config-snapshot">{{
        JSON.stringify(
          selected.config || {},
          null,
          2,
        )
      }}</pre>
    </div>
    <ErrorNotice :error="downloadError" />
    <p v-if="downloadError?.code === 'DOWNLOAD_BUSY' && downloadError.retryAfter != null" class="field-help" role="status">下载服务正忙，请在 {{ downloadError.retryAfter }} 秒后手动重试。</p>
    <p v-if="downloadState.message" class="field-help" role="status">{{ downloadState.message }}</p>
    <div class="panel-footer">
      <span>{{
        !supports('/tasks/{task_id}/adapter')
          ? "Adapter 下载将在产物接口就绪后开放。"
          : selected.status === "COMPLETED"
          ? "训练已完成，可下载服务端校验通过的产物。"
          : "仅完成的任务可下载 Adapter。"
      }}</span
      ><div class="download-actions"><button v-if="downloading" class="button secondary" @click="downloader.cancel()">取消下载</button><button
        class="button secondary"
        :disabled="
          selected.status !== 'COMPLETED' ||
          !supports('/tasks/{task_id}/adapter') ||
          downloading
        "
        @click="downloader.start(selected)"
      >
        <AppIcon name="download" size="16" />{{
          downloading ? "正在下载…" : "下载 Adapter"
        }}
      </button></div>
    </div>
  </section>
  <div class="status-explainer">
    <span v-for="(state, key) in taskStates" :key="key"
      ><i :class="state.tone" />{{ state.label }} <small>{{ key }}</small></span
    >
  </div>
</template>

<style scoped>
.detail-actions { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-bottom: 12px; }
.download-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.task-detail .panel-footer { flex-wrap: wrap; gap: 12px; }
</style>
