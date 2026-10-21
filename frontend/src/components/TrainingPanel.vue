<script setup>
import { computed, reactive, ref } from "vue";
import { ApiError, request, saveFile } from "../api";
import {
  configFields,
  defaultConfig,
  validateConfig,
} from "../training-config";
import { loadDatasets, loadTasks, supports, workspace } from "../workspace";
import AppIcon from "./AppIcon.vue";
import ErrorNotice from "./ErrorNotice.vue";

const config = reactive(structuredClone(defaultConfig));
const datasetId = ref("");
const modulesText = ref("q_proj, v_proj");
const submitting = ref(false);
const error = ref(null);
const feedback = ref("");
const modules = computed(() => [
  ...new Set(modulesText.value.split(/[,，\s]+/).filter(Boolean)),
]);
const payload = computed(() => ({
  dataset_id: datasetId.value,
  base_model: "Qwen/Qwen2.5-0.5B-Instruct",
  config: { ...config, target_modules: modules.value },
}));
const effectiveBatch = computed(
  () =>
    Number(config.per_device_train_batch_size) *
      Number(config.gradient_accumulation_steps) || "—",
);
const modelAllowed = computed(() =>
  workspace.models.some((model) => model.id === payload.value.base_model),
);
const canSubmit = computed(
  () =>
    supports("/tasks", "post") &&
    Boolean(datasetId.value) &&
    modelAllowed.value,
);
function reset() {
  Object.assign(config, structuredClone(defaultConfig));
  modulesText.value = "q_proj, v_proj";
  error.value = null;
  feedback.value = "已恢复推荐参数。";
}
function validate() {
  const errors = validateConfig(payload.value.config);
  if (errors.length) {
    error.value = new ApiError(errors.join(" "));
    return false;
  }
  return true;
}
function exportConfig() {
  error.value = null;
  if (!validate()) return;
  saveFile(
    JSON.stringify(payload.value, null, 2),
    "llmcloud-training-draft.json",
  );
  feedback.value = "配置草稿已导出；尚未提交训练任务。";
}
async function submit() {
  error.value = null;
  feedback.value = "";
  if (!canSubmit.value || submitting.value || !validate()) return;
  submitting.value = true;
  try {
    const data = await request("/tasks", {
      method: "POST",
      body: payload.value,
      timeout: 15000,
    });
    if (!data.id && !data.task_id)
      throw new ApiError("任务提交响应缺少任务编号，请先检查任务列表。", {
        uncertain: true,
      });
    feedback.value = `任务已提交：${data.id || data.task_id}。可到训练任务查看实际状态。`;
    await loadTasks();
  } catch (cause) {
    error.value = cause;
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">NEW EXPERIMENT</div>
      <h1>配置微调</h1>
      <p>从一组可靠的参数开始，训练属于你的领域模型。</p>
    </div>
    <span class="badge blue"
      ><AppIcon name="layers" size="14" />LoRA · 参数高效微调</span
    >
  </div>
  <form class="training-layout" @submit.prevent="submit">
    <div class="stack">
      <section class="panel">
        <div class="section-heading">
          <h2><span class="step-number">01</span>模型与数据</h2>
          <span class="subtle">训练输入</span>
        </div>
        <label class="field-label" for="base-model">基础模型</label
        ><select id="base-model" disabled>
          <option>Qwen2.5-0.5B-Instruct</option>
        </select>
        <p class="field-help">
          第一版使用 0.5B 指令模型。模型目录不代表权重已缓存。
        </p>
        <ErrorNotice :error="workspace.modelError" /><label
          class="field-label"
          for="training-dataset"
          >训练数据集</label
        ><select
          id="training-dataset"
          v-model="datasetId"
          :disabled="!workspace.datasets || submitting"
        >
          <option value="">
            {{
              workspace.datasets?.items.length
                ? "请选择数据集"
                : "暂无可用数据集，请先上传"
            }}
          </option>
          <option
            v-for="dataset in workspace.datasets?.items || []"
            :key="dataset.id"
            :value="dataset.id"
          >
            {{ dataset.name }} · {{ dataset.row_count }} 条
          </option>
        </select>
        <div class="field-help flex-between">
          <span>仅使用后端已保存的数据。</span
          ><a href="#datasets">管理数据集 ↗</a>
        </div>
        <div
          v-if="workspace.datasets && workspace.datasets.total_pages > 1"
          class="pagination"
        >
          <span
            >第 {{ workspace.datasetPage }} /
            {{ workspace.datasets.total_pages }} 页</span
          >
          <div>
            <button
              class="text-button"
              type="button"
              :disabled="workspace.datasetPage <= 1 || workspace.datasetLoading"
              @click="loadDatasets(workspace.datasetPage - 1)"
            >
              上一页</button
            ><button
              class="text-button"
              type="button"
              :disabled="
                workspace.datasetPage >= workspace.datasets.total_pages ||
                workspace.datasetLoading
              "
              @click="loadDatasets(workspace.datasetPage + 1)"
            >
              下一页
            </button>
          </div>
        </div>
      </section>
      <section class="panel">
        <div class="section-heading">
          <h2><span class="step-number">02</span>LoRA 配置</h2>
          <button class="text-button" type="button" @click="reset">
            恢复推荐参数
          </button>
        </div>
        <div class="form-grid three">
          <div
            v-for="field in configFields.filter(
              (item) => item.group === 'lora',
            )"
            :key="field.key"
          >
            <label class="field-label" :for="field.key">{{ field.label }}</label
            ><input
              :id="field.key"
              v-model.number="config[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              required
              :disabled="submitting"
            /><small class="field-help">{{ field.hint }}</small>
          </div>
        </div>
        <label class="field-label" for="target-modules">目标模块</label
        ><input
          id="target-modules"
          v-model="modulesText"
          placeholder="q_proj, v_proj"
          :disabled="submitting"
          required
        />
        <p class="field-help">
          用逗号分隔；默认训练注意力层 q_proj 与 v_proj。
        </p>
      </section>
      <section class="panel">
        <div class="section-heading">
          <h2><span class="step-number">03</span>训练超参数</h2>
          <span class="subtle">单 GPU 运行</span>
        </div>
        <div class="form-grid three">
          <div
            v-for="field in configFields.filter(
              (item) => item.group === 'train',
            )"
            :key="field.key"
          >
            <label class="field-label" :for="field.key">{{ field.label }}</label
            ><input
              :id="field.key"
              v-model.number="config[field.key]"
              type="number"
              :min="field.min"
              :max="field.max"
              :step="field.step"
              required
              :disabled="submitting"
            /><small class="field-help">{{ field.hint }}</small>
          </div>
        </div>
      </section>
    </div>
    <aside class="stack">
      <section class="panel summary-panel">
        <span class="eyebrow">EXPERIMENT SUMMARY</span>
        <h2>实验摘要</h2>
        <div class="model-mark">Q<span>0.5B</span></div>
        <h3>Qwen2.5 Instruct</h3>
        <p class="muted">普通 LoRA · 单 GPU</p>
        <dl class="summary-list">
          <div>
            <dt>LoRA Rank / Alpha</dt>
            <dd>{{ config.lora_r }} / {{ config.lora_alpha }}</dd>
          </div>
          <div>
            <dt>有效批次大小</dt>
            <dd>{{ effectiveBatch }}</dd>
          </div>
          <div>
            <dt>序列长度</dt>
            <dd>{{ config.max_seq_length }}</dd>
          </div>
          <div>
            <dt>训练轮数</dt>
            <dd>{{ config.num_train_epochs }}</dd>
          </div>
          <div>
            <dt>目标模块</dt>
            <dd>{{ modules.join(", ") || "未选择" }}</dd>
          </div>
        </dl>
        <ErrorNotice :error="error" />
        <p v-if="feedback" class="notice success-notice" role="status">
          {{ feedback }}
        </p>
        <button
          class="button primary full-width"
          type="submit"
          :disabled="!canSubmit || submitting"
        >
          <AppIcon name="plus" />{{
            submitting ? "正在提交…" : "提交训练任务"
          }}</button
        ><button
          class="button secondary full-width"
          type="button"
          @click="exportConfig"
        >
          <AppIcon name="download" />导出配置草稿
        </button>
        <p class="field-help">
          {{
            !supports("/tasks", "post")
              ? "任务服务尚未就绪，可先编辑并导出参数。"
              : !datasetId
                ? "选择数据集后即可提交。"
                : !modelAllowed
                  ? "等待模型目录确认可用模型。"
                  : "提交后由 GPU Worker 排队执行。"
          }}
        </p>
      </section>
      <div class="quiet-note">
        <AppIcon name="info" />
        <div>
          <strong>以小规模实验验证流程</strong>
          <p>
            推荐参数是实验起点，显存占用与训练效果需要实测。训练和推理共用单
            GPU，串行执行。
          </p>
        </div>
      </div>
      <details class="panel code-details">
        <summary>查看请求配置</summary>
        <pre>{{ JSON.stringify(payload, null, 2) }}</pre>
      </details>
    </aside>
  </form>
</template>
