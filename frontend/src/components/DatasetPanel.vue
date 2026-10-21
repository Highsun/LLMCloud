<script setup>
import { computed, nextTick, onBeforeUnmount, onDeactivated, ref, watch } from "vue";
import { ApiError, request, saveFile, uploadDataset } from "../api";
import {
  formatBytes,
  formatDate,
  loadDatasets,
  refreshWorkspace,
  supports,
  workspace,
} from "../workspace";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";
import ErrorNotice from "./ErrorNotice.vue";

const file = ref(null);
const fileInput = ref(null);
const name = ref("");
const dragOver = ref(false);
const uploading = ref(false);
const progress = ref(null);
const error = ref(null);
const success = ref("");
const selected = ref(null);
const detailLoading = ref(false);
const detailError = ref(null);
const detailDialog = ref(null);
let previousFocus;
let controller;
let detailSequence = 0;
const canUpload = computed(() => supports("/datasets", "post"));

function selectFiles(files) {
  error.value = null;
  success.value = "";
  if (uploading.value || !files?.length) return;
  if (files.length !== 1) {
    file.value = null;
    error.value = new ApiError("每次请选择一个 JSONL 文件。");
    return;
  }
  const candidate = files[0];
  if (!/^.+\.jsonl$/i.test(candidate.name)) {
    file.value = null;
    error.value = new ApiError("请选择扩展名为 .jsonl 的文件。");
    return;
  }
  if (!candidate.size || candidate.size > 52428800) {
    file.value = null;
    error.value = new ApiError("文件不能为空，且大小不得超过 50 MiB。");
    return;
  }
  file.value = candidate;
}
function drop(event) {
  dragOver.value = false;
  selectFiles(event.dataTransfer.files);
}
function resetFile() {
  file.value = null;
  if (fileInput.value) fileInput.value.value = "";
}
function sample() {
  saveFile(
    '{"instruction":"什么是云计算？","input":"","output":"云计算通过网络按需提供计算、存储等资源。"}\n',
    "format-example.jsonl",
    "application/x-ndjson;charset=utf-8",
  );
}
async function upload() {
  if (!file.value || !canUpload.value || uploading.value) return;
  error.value = null;
  success.value = "";
  const rawName = name.value;
  if (
    rawName &&
    (/[\x00-\x1f\x7f]/.test(rawName) ||
      !rawName.trim() ||
      [...rawName.trim()].length > 255 ||
      new TextEncoder().encode(rawName.trim()).length > 1024)
  ) {
    error.value = new ApiError(
      "名称需为 1–255 个字符，不含控制字符，UTF-8 编码不得超过 1 KiB；也可完全留空使用文件名。",
    );
    return;
  }
  controller = new AbortController();
  uploading.value = true;
  progress.value = 0;
  try {
    const data = await uploadDataset(
      file.value,
      rawName,
      (value) => {
        progress.value = value;
      },
      controller.signal,
    );
    success.value = `「${data.name}」已上传并保存，共 ${data.row_count} 条记录。`;
    resetFile();
    name.value = "";
    await loadDatasets(1);
  } catch (cause) {
    error.value = cause;
  } finally {
    uploading.value = false;
    controller = null;
  }
}
async function showDetail(id) {
  previousFocus = document.activeElement;
  selected.value = { id };
  detailError.value = null;
  detailLoading.value = true;
  const sequence = ++detailSequence;
  try {
    const data = await request(`/datasets/${encodeURIComponent(id)}`);
    if (sequence === detailSequence) selected.value = data;
  } catch (cause) {
    if (sequence === detailSequence) detailError.value = cause;
  } finally {
    if (sequence === detailSequence) detailLoading.value = false;
  }
}
function closeDetail() {
  selected.value = null;
  detailSequence++;
  detailDialog.value?.close();
  previousFocus?.focus();
}
watch(
  () => Boolean(selected.value),
  async (open) => {
    if (open) {
      await nextTick();
      if (!detailDialog.value.open) detailDialog.value.showModal();
    }
  },
);
onBeforeUnmount(() => controller?.abort());
onDeactivated(closeDetail);
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">DATA MANAGEMENT</div>
      <h1>数据集</h1>
      <p>管理微调的起点，让每一次训练都有据可循。</p>
    </div>
    <button
      class="button secondary"
      :disabled="workspace.checking || workspace.datasetLoading"
      @click="refreshWorkspace"
    >
      <AppIcon
        name="refresh"
        :class="{ spinning: workspace.checking }"
      />刷新数据
    </button>
  </div>
  <div class="dataset-layout">
    <section class="panel upload-panel">
      <div class="section-heading">
        <h2><AppIcon name="upload" />上传数据集</h2>
        <span class="badge neutral">JSONL</span>
      </div>
      <p class="muted">上传 UTF-8 编码的指令数据，校验通过后即可用于训练。</p>
      <form @submit.prevent="upload">
        <input
          id="dataset-file"
          ref="fileInput"
          class="visually-hidden"
          type="file"
          accept=".jsonl"
          :disabled="uploading"
          @change="selectFiles($event.target.files)"
        />
        <label
          for="dataset-file"
          class="dropzone"
          :class="{ dragging: dragOver, 'has-file': file }"
          tabindex="0"
          @keydown.enter.prevent="fileInput.click()"
          @keydown.space.prevent="fileInput.click()"
          @dragover.prevent="dragOver = !uploading"
          @dragleave.prevent="dragOver = false"
          @drop.prevent="drop"
        >
          <span class="upload-symbol"
            ><AppIcon :name="file ? 'file' : 'upload'" size="28"
          /></span>
          <strong>{{ file ? file.name : "点击选择，或拖拽文件到这里" }}</strong>
          <span>{{
            file ? formatBytes(file.size) : "仅支持 .jsonl · 最大 50 MiB"
          }}</span>
          <span class="file-action"
            >{{ file ? "更换文件" : "选择文件" }}
            <AppIcon name="arrow" size="14"
          /></span>
        </label>
        <label class="field-label" for="dataset-name"
          >数据集名称 <span>可选</span></label
        >
        <input
          id="dataset-name"
          v-model="name"
          :disabled="uploading"
          placeholder="留空时使用原始文件名"
          autocomplete="off"
        />
        <div v-if="uploading" class="upload-progress" role="status">
          <div class="flex-between">
            <span>{{
              progress === 100 ? "传输完成，正在等待服务端校验…" : "文件传输中…"
            }}</span
            ><span>{{ progress === null ? "传输中" : `${progress}%` }}</span>
          </div>
          <progress
            :value="progress === null ? undefined : progress"
            max="100"
            aria-label="文件传输进度"
          /><button
            class="text-button"
            type="button"
            @click="controller?.abort()"
          >
            取消上传
          </button>
        </div>
        <ErrorNotice :error="error" />
        <div v-if="success" class="notice success-notice" role="status">
          <AppIcon name="check" /><span>{{ success }}</span>
        </div>
        <button
          class="button primary full-width"
          type="submit"
          :disabled="!file || uploading || !canUpload"
        >
          <AppIcon name="upload" />{{
            uploading ? "上传处理中…" : "上传并校验"
          }}
        </button>
        <p v-if="!canUpload" class="field-help">
          {{
            workspace.checking
              ? "正在检查上传服务…"
              : "上传服务尚未就绪。你可以先选择文件，服务接入后刷新即可上传。"
          }}
        </p>
        <p v-else class="field-help">
          服务端将完成格式校验；传输达到 100% 后仍需等待确认。
        </p>
      </form>
      <div class="format-guide">
        <div class="flex-between">
          <h3>数据格式</h3>
          <button class="text-button" @click="sample">
            <AppIcon name="download" size="14" />下载格式样例
          </button>
        </div>
        <pre>
{
  "instruction": "什么是云计算？",
  "input": "",
  "output": "通过网络按需提供计算资源。"
}</pre
        >
        <small
          >每行一个完整 JSON 对象。instruction、output 必填，input
          可省略。上方缩进仅为阅读展示。</small
        >
      </div>
    </section>
    <section class="panel dataset-library">
      <div class="section-heading">
        <h2>
          <AppIcon name="data" />我的数据集
          <span class="count">{{ workspace.datasets?.total ?? "—" }}</span>
        </h2>
        <span class="subtle">最新上传优先</span>
      </div>
      <ErrorNotice :error="workspace.datasetError" />
      <div v-if="workspace.datasetLoading" class="loading-state" role="status">
        <span class="loader" />正在读取数据集…
      </div>
      <template v-else-if="workspace.datasets?.items.length">
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>数据集名称</th>
                <th>记录 / 大小</th>
                <th>创建时间</th>
                <th><span class="visually-hidden">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in workspace.datasets.items" :key="item.id">
                <td>
                  <div class="table-name">
                    <span class="file-tile"
                      ><AppIcon name="file" size="19"
                    /></span>
                    <div>
                      <strong>{{ item.name }}</strong
                      ><small>Alpaca JSONL</small>
                    </div>
                  </div>
                </td>
                <td>
                  {{ item.row_count.toLocaleString() }} 条<small>{{
                    formatBytes(item.size_bytes)
                  }}</small>
                </td>
                <td>{{ formatDate(item.created_at) }}</td>
                <td>
                  <button class="text-button" @click="showDetail(item.id)">
                    详情<AppIcon name="chevron" size="14" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
      <EmptyState
        v-else
        :title="
          workspace.datasetError
            ? '数据暂时无法读取'
            : workspace.datasets
              ? '还没有数据集'
              : '等待连接数据服务'
        "
        :description="
          workspace.datasets
            ? '上传第一份指令数据，开始你的微调实验。'
            : '服务就绪后，已保存的数据集会显示在这里。'
        "
      />
      <div class="pagination">
        <span>{{
          workspace.datasets
            ? `共 ${workspace.datasets.total} 个数据集`
            : "数据由服务端保存"
        }}</span>
        <div>
          <label class="visually-hidden" for="page-size">每页数量</label
          ><select
            id="page-size"
            :value="workspace.pageSize"
            :disabled="!workspace.datasets || workspace.datasetLoading"
            @change="loadDatasets(1, Number($event.target.value))"
          >
            <option :value="20">20 条 / 页</option>
            <option :value="50">50 条 / 页</option>
            <option :value="100">100 条 / 页</option></select
          ><button
            class="icon-button"
            aria-label="上一页"
            :disabled="
              !workspace.datasets ||
              workspace.datasetPage <= 1 ||
              workspace.datasetLoading
            "
            @click="loadDatasets(workspace.datasetPage - 1)"
          >
            <AppIcon class="rotate" name="chevron" size="16" /></button
          ><span>{{
            workspace.datasets
              ? `${workspace.datasetPage} / ${workspace.datasets.total_pages || 1}`
              : "—"
          }}</span
          ><button
            class="icon-button"
            aria-label="下一页"
            :disabled="
              !workspace.datasets ||
              workspace.datasetPage >= workspace.datasets.total_pages ||
              workspace.datasetLoading
            "
            @click="loadDatasets(workspace.datasetPage + 1)"
          >
            <AppIcon name="chevron" size="16" />
          </button>
        </div>
      </div>
      <div class="library-note">
        <AppIcon name="info" size="16" />
        <p>
          上传后数据不可变。内容调整时请上传新版本，以保留每次实验的输入记录。
        </p>
      </div>
    </section>
  </div>
  <dialog
    ref="detailDialog"
    class="detail-dialog"
    aria-label="数据集详情"
    @cancel.prevent="closeDetail"
  >
    <template v-if="selected"
      ><div class="section-heading">
        <h2>数据集详情</h2>
        <button class="icon-button" aria-label="关闭详情" @click="closeDetail">
          <AppIcon name="close" />
        </button>
      </div>
      <div v-if="detailLoading" class="loading-state" role="status">
        正在读取详情…
      </div>
      <ErrorNotice :error="detailError" />
      <dl v-if="!detailLoading && !detailError" class="detail-list">
        <template
          v-for="[label, value] in [
            ['名称', selected.name],
            ['资源 ID', selected.id],
            ['原始文件名', selected.original_filename],
            ['格式', selected.format],
            ['记录数', selected.row_count],
            ['文件大小', formatBytes(selected.size_bytes)],
            ['创建时间', formatDate(selected.created_at)],
            ['SHA-256', selected.sha256],
          ]"
          :key="label"
          ><dt>{{ label }}</dt>
          <dd :class="{ mono: label === 'SHA-256' || label === '资源 ID' }">
            {{ value }}
          </dd></template
        >
      </dl>
      <button class="button primary full-width" @click="closeDetail">
        完成
      </button></template
    >
  </dialog>
</template>
