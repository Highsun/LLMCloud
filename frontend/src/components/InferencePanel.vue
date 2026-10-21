<script setup>
import { computed, onBeforeUnmount, ref } from "vue";
import { ApiError, request } from "../api";
import { supports, workspace } from "../workspace";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";
import ErrorNotice from "./ErrorNotice.vue";

const taskId = ref("");
const prompt = ref("");
const maxTokens = ref(128);
const baseline = ref("");
const result = ref(null);
const running = ref(false);
const error = ref(null);
const completed = computed(() =>
  (workspace.tasks?.items || []).filter((task) => task.status === "COMPLETED"),
);
const canGenerate = computed(
  () =>
    supports("/inference", "post") &&
    Boolean(taskId.value) &&
    Boolean(prompt.value.trim()),
);
const questions = [
  "用简洁的语言解释什么是云计算。",
  "异步任务队列如何处理模型训练请求？",
  "LoRA 微调与全量微调有什么区别？",
];
let controller;
async function generate() {
  if (!canGenerate.value || running.value) return;
  if (
    !Number.isInteger(maxTokens.value) ||
    maxTokens.value < 1 ||
    maxTokens.value > 512
  ) {
    error.value = new ApiError("输出长度需为 1–512 的整数。");
    return;
  }
  running.value = true;
  error.value = null;
  result.value = null;
  controller = new AbortController();
  const input = {
    task_id: taskId.value,
    prompt: prompt.value,
    max_new_tokens: maxTokens.value,
  };
  try {
    const data = await request("/inference", {
      method: "POST",
      body: input,
      timeout: 120000,
      signal: controller.signal,
    });
    const text = data.generated_text ?? data.text ?? data.output;
    if (typeof text !== "string")
      throw new ApiError("推理响应格式待联调，尚未读取到文本结果。");
    result.value = { text, prompt: input.prompt, taskId: input.task_id };
  } catch (cause) {
    error.value =
      cause.status === 409
        ? new ApiError("GPU 当前忙碌，请等待训练或其他推理任务结束后重试。", {
            status: 409,
            code: cause.code,
            requestId: cause.requestId,
          })
        : cause;
  } finally {
    running.value = false;
    controller = null;
  }
}
onBeforeUnmount(() => controller?.abort());
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">MODEL PLAYGROUND</div>
      <h1>推理实验室</h1>
      <p>用同一道问题，观察模型在微调之后的变化。</p>
    </div>
    <span class="badge neutral"
      ><AppIcon name="chip" size="14" />共享 GPU · 串行推理</span
    >
  </div>
  <p class="field-help inference-help">
    Adapter
    选项取自训练任务当前页中的已完成任务；可在训练任务页翻页，再返回选择。
  </p>
  <div class="inference-layout">
    <section class="panel">
      <div class="section-heading">
        <h2><AppIcon name="sliders" />推理设置</h2>
      </div>
      <form @submit.prevent="generate">
        <label class="field-label" for="inference-task">选择 Adapter</label
        ><select
          id="inference-task"
          v-model="taskId"
          :disabled="running || !completed.length"
        >
          <option value="">
            {{
              completed.length ? "选择已完成的训练任务" : "暂无已完成的训练任务"
            }}
          </option>
          <option v-for="task in completed" :key="task.id" :value="task.id">
            {{ task.id.slice(0, 8) }} · Qwen2.5-0.5B
          </option>
        </select>
        <p class="field-help">仅使用已完成任务的 Adapter。</p>
        <label class="field-label" for="max-tokens">最大输出长度</label>
        <div class="input-unit">
          <input
            id="max-tokens"
            v-model.number="maxTokens"
            type="number"
            min="1"
            max="512"
            step="1"
            required
            :disabled="running"
          /><span>tokens</span>
        </div>
        <label class="field-label" for="prompt">测试提示词</label
        ><textarea
          id="prompt"
          v-model="prompt"
          rows="7"
          maxlength="8000"
          placeholder="输入你想测试的问题…"
          required
          :disabled="running"
        />
        <div class="field-help flex-between">
          <span>尽量保持前后测试条件一致</span
          ><span>{{ prompt.length }} / 8000</span>
        </div>
        <ErrorNotice :error="error" /><button
          class="button primary full-width"
          type="submit"
          :disabled="!canGenerate || running"
        >
          <AppIcon :name="running ? 'clock' : 'chat'" />{{
            running ? "正在生成回答…" : "生成回答"
          }}</button
        ><button
          v-if="running"
          type="button"
          class="text-button"
          @click="controller?.abort()"
        >
          停止等待
        </button>
        <p v-if="!supports('/inference', 'post')" class="field-help">
          推理服务尚未就绪，可以先准备测试问题。
        </p>
      </form>
      <div class="prompt-suggestions">
        <h3>试试这些问题</h3>
        <button
          v-for="question in questions"
          :key="question"
          :disabled="running"
          @click="prompt = question"
        >
          {{ question }}<AppIcon name="arrow" size="14" />
        </button>
      </div>
    </section>
    <div class="stack">
      <section class="panel response-panel">
        <div class="section-heading">
          <h2><span class="status-dot green" />微调模型回答</h2>
          <span class="badge green">LoRA Adapter</span>
        </div>
        <div v-if="running" class="loading-state" role="status">
          <span class="loader" />等待模型生成，可能需要一些时间…
        </div>
        <template v-else-if="result"
          ><div class="result-context">
            <span class="mono">任务 {{ result.taskId }}</span>
            <p>{{ result.prompt }}</p>
          </div>
          <div class="model-output">{{ result.text }}</div></template
        ><EmptyState
          v-else
          icon="chat"
          title="让训练成果开口说话"
          description="选择一个已完成的 Adapter，输入问题并生成回答。"
        />
      </section>
      <section class="panel baseline-panel">
        <div class="section-heading">
          <h2><AppIcon name="layers" />基础模型对照</h2>
          <span class="badge neutral">手动记录</span>
        </div>
        <p class="muted">
          将独立测试得到的基础模型回答粘贴在这里，保留无提升或退化的情况。
        </p>
        <label class="visually-hidden" for="baseline">基础模型回答记录</label
        ><textarea
          id="baseline"
          v-model="baseline"
          rows="5"
          placeholder="粘贴同一提示词、相同解码设置下的基础模型回答…"
        /><small class="field-help"
          >仅在当前页面暂存；这里不会自动调用基础模型。</small
        >
      </section>
    </div>
  </div>
</template>
