<script setup>
import { computed, onActivated, onBeforeUnmount, onDeactivated, reactive, ref, watch } from "vue";
import { supports, formatDate } from "../workspace";
import { createInference, createInferenceTasks, unicodeLength } from "../inference";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";
import ErrorNotice from "./ErrorNotice.vue";

const taskId = ref("");
const prompt = ref("");
const maxTokens = ref(128);
const mode = ref("compare");
const active = ref(false);
const state = reactive({});
const tasks = reactive({});
const inference = createInference({ state });
const taskList = createInferenceTasks({ state: tasks, onMissing(items) {
  if (taskId.value && !items.some((task) => task.id === taskId.value)) taskId.value = "";
} });
const available = computed(() => supports("/inference", "post"));
const taskAvailable = computed(() => supports("/tasks"));
const canGenerate = computed(() => available.value && taskAvailable.value && !tasks.busy &&
  tasks.items.some((task) => task.id === taskId.value) && Boolean(prompt.value.trim()));
const answers = [
  { key: "adapter", title: "微调模型回答", badge: "LoRA Adapter" },
  { key: "base", title: "基础模型对照", badge: "基础模型" },
];
const questions = [
  "用简洁的语言解释什么是云计算。",
  "异步任务队列如何处理模型训练请求？",
  "LoRA 微调与全量微调有什么区别？",
];
watch([taskId, mode], () => inference.cancel(state.busy
  ? "已停止原请求的等待；GPU 可能仍在清理，请稍后再生成。" : ""), { flush: "sync" });
function generate() {
  if (!canGenerate.value) return;
  return inference.start({ task_id: taskId.value, prompt: prompt.value,
    max_new_tokens: maxTokens.value, mode: mode.value });
}
function loadPage(page = tasks.page) {
  if (!taskAvailable.value || !active.value) return;
  if (page !== tasks.page) taskId.value = "";
  return taskList.load(page);
}
watch(taskAvailable, (value) => { if (value && active.value) loadPage(1); });
onActivated(() => { active.value = true; loadPage(); });
function leave() {
  active.value = false;
  taskList.cancel();
  if (state.busy) inference.cancel("已停止等待；返回页面后可手动重试，GPU 可能仍在清理。");
}
onDeactivated(leave);
onBeforeUnmount(leave);
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">MODEL PLAYGROUND</div>
      <h1>推理实验室</h1>
      <p>用同一道问题，观察模型在微调之后的变化。</p>
    </div>
    <span class="badge neutral"><AppIcon name="chip" size="14" />共享 GPU · 串行推理</span>
  </div>
  <p class="field-help inference-help">选择已完成的训练任务；对照模式将使用同一问题和生成参数，顺序生成两份回答。</p>
  <div class="inference-layout">
    <section class="panel">
      <div class="section-heading"><h2><AppIcon name="sliders" />推理设置</h2></div>
      <form @submit.prevent="generate">
        <label class="field-label" for="inference-task">选择 Adapter</label>
        <select id="inference-task" v-model="taskId" :disabled="tasks.busy || !tasks.items.length">
          <option value="">{{ tasks.busy ? "正在读取已完成任务…" : tasks.items.length ? "选择已完成的训练任务" : "暂无已完成的训练任务" }}</option>
          <option v-for="task in tasks.items" :key="task.id" :value="task.id">
            {{ task.id.slice(0, 8) }} · {{ formatDate(task.created_at) }}
          </option>
        </select>
        <p v-if="taskId" class="field-help mono inference-id">任务 {{ taskId }}</p>
        <div class="inference-pagination">
          <button type="button" class="text-button" :disabled="tasks.busy || !taskAvailable" @click="loadPage()">刷新任务</button>
          <button type="button" class="text-button" :disabled="tasks.busy || tasks.page <= 1" @click="loadPage(tasks.page - 1)">上一页</button>
          <span>{{ tasks.page }} / {{ tasks.totalPages || 1 }}</span>
          <button type="button" class="text-button" :disabled="tasks.busy || tasks.page >= tasks.totalPages" @click="loadPage(tasks.page + 1)">下一页</button>
        </div>
        <ErrorNotice :error="tasks.error" />
        <p v-if="!taskAvailable" class="field-help">任务查询服务尚未就绪，请刷新服务状态。</p>
        <label class="field-label" for="inference-mode">生成模式</label>
        <select id="inference-mode" v-model="mode">
          <option value="compare">基础模型与 Adapter 对照</option>
          <option value="adapter">仅 Adapter 回答</option>
        </select>
        <label class="field-label" for="max-tokens">每份回答的最大输出长度</label>
        <div class="input-unit">
          <input id="max-tokens" v-model.number="maxTokens" type="number" min="1" max="256" step="1" required :disabled="state.busy" />
          <span>tokens</span>
        </div>
        <label class="field-label" for="prompt">测试提示词</label>
        <textarea id="prompt" v-model="prompt" rows="7" placeholder="输入你想测试的问题…" required :disabled="state.busy" />
        <div class="field-help flex-between inference-prompt-count"><span>尽量保持前后测试条件一致</span><span>{{ unicodeLength(prompt) }} / 8192 字符</span></div>
        <ErrorNotice :error="state.error" />
        <p v-if="state.message" class="field-help" role="status">{{ state.message }}</p>
        <button class="button primary full-width" type="submit" :disabled="!canGenerate || state.busy">
          <AppIcon :name="state.busy ? 'clock' : 'chat'" />{{ state.busy ? "正在生成回答…" : state.error ? "重新生成" : "生成回答" }}
        </button>
        <button v-if="state.busy" type="button" class="text-button" @click="inference.cancel('已停止等待；GPU 可能仍在清理，请稍后手动重试。')">停止等待</button>
        <p v-if="state.busy" class="field-help">等待最多 120 秒。切换任务或模式会停止本次等待；停止等待后 GPU 可能仍在清理。</p>
        <p v-if="!available" class="field-help">推理服务尚未就绪，可以先准备测试问题。</p>
      </form>
      <div class="prompt-suggestions">
        <h3>试试这些问题</h3>
        <button v-for="question in questions" :key="question" :disabled="state.busy" @click="prompt = question">
          {{ question }}<AppIcon name="arrow" size="14" />
        </button>
      </div>
    </section>
    <div class="stack inference-answers" aria-live="polite" :aria-busy="state.busy">
      <div v-if="state.result" class="panel result-context">
        <span class="mono inference-id">任务 {{ state.result.task_id }}</span>
        <p>{{ state.result.prompt }}</p>
        <small>{{ state.result.base_model }} · 输入 {{ state.result.input_tokens }} tokens · 每份最多 {{ state.result.max_new_tokens }} tokens</small>
        <small class="mono inference-id">revision {{ state.result.model_revision }}</small>
      </div>
      <section v-for="answer in answers" :key="answer.key" class="panel response-panel" :data-answer="answer.key">
        <div class="section-heading">
          <h2><AppIcon :name="answer.key === 'base' ? 'layers' : 'chat'" />{{ answer.title }}</h2>
          <span class="badge" :class="answer.key === 'base' ? 'neutral' : 'green'">{{ answer.badge }}</span>
        </div>
        <div v-if="state.busy && (answer.key === 'adapter' || mode === 'compare')" class="loading-state" role="status">
          <span class="loader" />等待模型生成，完成后展示本次{{ mode === 'compare' ? '两份' : '' }}回答…
        </div>
        <template v-else-if="state.result?.[answer.key]">
          <div class="model-output">{{ state.result[answer.key].generated_text || '本次未生成文本。' }}</div>
          <p class="field-help">实际生成 {{ state.result[answer.key].generated_tokens }} tokens</p>
        </template>
        <EmptyState v-else icon="chat" :title="answer.key === 'base' ? '基础模型对照' : '让训练成果开口说话'"
          :description="answer.key === 'base' ? mode === 'adapter' ? '仅 Adapter 模式不生成基础模型回答。' : '选择对照模式后，两份回答将使用同一问题与生成参数。' : '选择一个已完成的 Adapter，输入问题并生成回答。'" />
      </section>
    </div>
  </div>
</template>
