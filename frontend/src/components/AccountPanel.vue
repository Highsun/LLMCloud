<script setup>
import { ref } from "vue";
import { request } from "../api";
import AppIcon from "./AppIcon.vue";
import ErrorNotice from "./ErrorNotice.vue";

const props = defineProps({ account: { type: Object, required: true } });
const emit = defineEmits(["updated"]);
const currentName = () => props.account.display_name || props.account.username;
const displayName = ref(currentName());
const saving = ref(false);
const saved = ref(false);
const error = ref(null);

async function save() {
  const name = displayName.value.trim();
  if (!name || name === currentName() || saving.value) return;
  error.value = null;
  saved.value = false;
  saving.value = true;
  try {
    const account = await request("/auth/me", { method: "PATCH", body: { display_name: name } });
    displayName.value = account.display_name;
    emit("updated", account);
    saved.value = true;
  } catch (cause) {
    error.value = cause;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="page-heading">
    <div><h1>用户中心</h1><p>管理账号资料与个人实验。</p></div>
  </div>
  <div class="account-grid">
    <section class="panel account-panel">
      <div class="section-heading"><h2>账号资料</h2></div>
      <form class="account-form" @submit.prevent="save">
        <ErrorNotice :error="error" />
        <label class="account-field">登录用户名<input :value="account.username" readonly /></label>
        <label class="account-field">
          显示名称
          <input v-model="displayName" required maxlength="80" :disabled="saving" @input="saved = false" />
          <small>最多 40 个字符。</small>
        </label>
        <div class="account-actions">
          <button type="submit" class="button primary" :disabled="saving || !displayName.trim() || displayName.trim() === currentName()">
            {{ saving ? "正在保存…" : "保存资料" }}
          </button>
          <span v-if="saved" class="account-saved" role="status">资料已保存</span>
        </div>
      </form>
    </section>
    <section class="panel account-panel">
      <div class="section-heading"><h2>我的实验</h2></div>
      <div class="account-links">
        <a href="#datasets"><AppIcon name="data" /><span>我的数据集</span><AppIcon name="arrow" size="16" /></a>
        <a href="#tasks"><AppIcon name="activity" /><span>我的训练任务与 Adapter</span><AppIcon name="arrow" size="16" /></a>
      </div>
    </section>
  </div>
</template>

<style scoped>
.account-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 16px;
}
.account-panel {
  padding: 20px;
}
.account-form,
.account-field,
.account-links {
  display: grid;
  gap: 12px;
}
.account-field {
  gap: 7px;
}
.account-field input {
  width: 100%;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  font: inherit;
}
.account-field input[readonly] {
  background: #f4f7f6;
}
.account-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.account-saved {
  color: var(--accent-dark);
}
.account-links a {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--ink);
  min-height: 44px;
}
.account-links a span {
  flex: 1;
}
@media (max-width: 880px) {
  .account-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
