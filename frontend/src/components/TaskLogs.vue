<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import ErrorNotice from "./ErrorNotice.vue";
const props = defineProps({ page: Object, error: Object, loading: Boolean, taskStatus: String });
const terminal = ref(null);
const following = ref(true);
const ended = computed(() => ["COMPLETED", "FAILED"].includes(props.taskStatus));
const emptyText = computed(() => {
  if (props.error) return "日志读取失败，请重试。";
  if (props.loading) return "正在读取任务日志…";
  if (props.page?.source_state === "ready") return "日志文件已创建，暂无可展示的完整记录。";
  return ended.value ? "任务已结束，未产生可展示的日志。" : "尚未产生日志。";
});
function onScroll() {
  const box = terminal.value;
  following.value = box.scrollHeight - box.scrollTop - box.clientHeight < 16;
}
function toBottom() {
  if (terminal.value) terminal.value.scrollTop = terminal.value.scrollHeight;
  following.value = true;
}
onMounted(toBottom);
watch(() => props.page, async () => {
  const follow = following.value;
  const top = terminal.value?.scrollTop ?? 0;
  await nextTick();
  if (follow) toBottom();
  else if (terminal.value) terminal.value.scrollTop = top;
});
</script>
<template>
  <div class="task-logs">
    <ErrorNotice :error="error" />
    <p v-if="loading" class="field-help" role="status">正在刷新日志尾部…</p>
    <p v-if="page?.truncated" class="notice" role="status">更早的日志已省略，当前显示有限尾部。</p>
    <p v-if="page?.tail_incomplete" class="notice" role="status">日志尾部有未完成行，尚未作为完整记录显示。</p>
    <p v-if="page?.filtered_lines" class="notice" role="status">本次有 {{ page.filtered_lines }} 条源记录被过滤或调整。</p>
    <button v-if="!following" class="text-button" @click="toBottom">回到底部</button>
    <pre ref="terminal" class="terminal" tabindex="0" aria-label="当前任务日志尾部" @scroll="onScroll">{{ page?.lines.length ? page.lines.join('\n') : emptyText }}</pre>
    <p class="field-help">仅显示当前任务最近 100 条记录中的可展示内容，刷新时更新此尾部。</p>
  </div>
</template>
<style scoped>
.task-logs .notice { display: block; overflow-wrap: anywhere; }
.task-logs .terminal { overflow-anchor: none; }
</style>
