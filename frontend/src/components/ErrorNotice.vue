<script setup>
import AppIcon from "./AppIcon.vue";
defineProps({ error: Object });
</script>
<template>
  <div v-if="error" class="notice error-notice" role="alert">
    <AppIcon name="info" />
    <div>
      <strong>{{ error.message }}</strong>
      <ul v-if="error.details?.length">
        <li v-for="(detail, index) in error.details" :key="index">
          {{
            detail.line
              ? `第 ${detail.line} 行${detail.column ? `，第 ${detail.column} 列` : ""} · `
              : ""
          }}{{ detail.loc?.slice(1).join(" / ") }}：{{ detail.message }}
        </li>
      </ul>
      <small v-if="error.truncated">更多错误已省略，请修正后重试。</small>
      <small v-if="error.requestId" class="mono"
        >请求编号：{{ error.requestId }}</small
      >
      <small v-if="error.uncertain"
        >保存结果尚不确定。请先刷新列表核对，避免直接重复提交。</small
      >
    </div>
  </div>
</template>
