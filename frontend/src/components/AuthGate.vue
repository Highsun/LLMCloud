<script setup>
import { onBeforeUnmount, onMounted, ref } from "vue";
import App from "../App.vue";
import { baseUrl } from "../api";

const checking = ref(true), enabled = ref(false), user = ref(null);
const mode = ref("login"), username = ref(""), password = ref("");
const showPassword = ref(false);
const pending = ref(false), error = ref("");
async function authRequest(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(`${baseUrl}/auth/${path}`, {
      credentials: "include", signal: controller.signal,
      ...options,
    });
    const data = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const cause = new Error(data?.error?.message || "账户操作失败，请重试。");
      cause.status = response.status; throw cause;
    }
    return data;
  } finally { clearTimeout(timer); }
}
async function check() {
  checking.value = true; error.value = "";
  try {
    const config = await authRequest("config");
    enabled.value = config.enabled === true;
    if (enabled.value) {
      try {
        user.value = await authRequest("me");
        try {
          if (sessionStorage.getItem("llmcloud:account-id") !== user.value.id) {
            rememberAccount(user.value.id); window.location.reload(); return;
          }
        } catch { /* Account data is still isolated by the API. */ }
      }
      catch (cause) {
        user.value = null;
        if (cause.status !== 401) error.value = "账户服务暂时不可用，请稍后重新检查连接。";
      }
    }
  } catch (cause) {
    if (cause.status === 404) { enabled.value = false; return; }
    // A missing account endpoint is compatible with the historical demo API.
    // Only an explicit enabled=true response activates authentication here;
    // resource endpoints remain authoritative about access.
    error.value = "无法检查账户服务，请确认后端已启动后重试。";
    enabled.value = true;
  } finally { checking.value = false; }
}
function rememberAccount(id) {
  try { sessionStorage.setItem("llmcloud:account-id", id); } catch { /* Session remains server-owned. */ }
}
function notifyAccountChange() {
  try { localStorage.setItem("llmcloud:account-change", `${Date.now()}:${Math.random()}`); } catch { /* Optional cross-tab notification. */ }
}
function changedInAnotherTab(event) {
  if (event.key === "llmcloud:account-change") window.location.reload();
}
async function submit() {
  if (pending.value) return;
  pending.value = true; error.value = "";
  try {
    const body = JSON.stringify({ username: username.value, password: password.value });
    if (mode.value === "register") await authRequest("register", { method: "POST", headers: { "Content-Type": "application/json" }, body });
    const account = await authRequest("login", { method: "POST", headers: { "Content-Type": "application/json" }, body });
    password.value = ""; rememberAccount(account.id); notifyAccountChange();
    window.location.reload();
  } catch (cause) { error.value = cause.message || "连接失败，请重试。"; }
  finally { pending.value = false; }
}
async function logout() {
  if (pending.value) return;
  pending.value = true; error.value = "";
  try {
    await authRequest("logout", { method: "POST" });
    rememberAccount(""); notifyAccountChange(); window.location.reload();
  } catch (cause) { error.value = cause.message || "退出失败，请重试。"; }
  finally { pending.value = false; }
}
function expired() { user.value = null; password.value = ""; error.value = "会话已过期，请重新登录。"; }
onMounted(() => { check(); window.addEventListener("llmcloud:auth-required", expired); window.addEventListener("storage", changedInAnotherTab); });
onBeforeUnmount(() => { window.removeEventListener("llmcloud:auth-required", expired); window.removeEventListener("storage", changedInAnotherTab); });
</script>

<template>
  <main v-if="checking" class="auth-screen" aria-busy="true"><p>正在检查账户服务…</p></main>
  <main v-else-if="enabled && !user" class="auth-screen">
    <form class="auth-card" @submit.prevent="submit">
      <span class="auth-brand">LLMCloud</span>
      <h1>{{ mode === 'login' ? '登录工作空间' : '创建账户' }}</h1>
      <p>管理自己的数据集、训练任务和模型产物。</p>
      <label>用户名<input v-model="username" name="username" autocomplete="username" required minlength="3" maxlength="32" pattern="[a-zA-Z0-9_\-]+" :disabled="pending" /></label>
      <small>3–32 位英文字母、数字、下划线或连字符，不区分大小写。</small>
      <label>密码<input v-model="password" :type="showPassword ? 'text' : 'password'" name="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" required minlength="12" maxlength="128" :disabled="pending" /></label>
      <div class="password-options">
        <small>12–128 个字符。请使用独立密码。</small>
        <button type="button" class="text-button" @click="showPassword = !showPassword">{{ showPassword ? '隐藏密码' : '显示密码' }}</button>
      </div>
      <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
      <button class="primary-button" :disabled="pending">{{ pending ? '正在处理…' : mode === 'login' ? '登录' : '注册并登录' }}</button>
      <button type="button" class="text-button" :disabled="pending" @click="mode = mode === 'login' ? 'register' : 'login'; error = ''">{{ mode === 'login' ? '没有账户？注册' : '已有账户？登录' }}</button>
      <button type="button" class="text-button" :disabled="pending" @click="check">重新检查连接</button>
    </form>
  </main>
  <template v-else>
    <div v-if="enabled && user" class="auth-account"><span>{{ user.username }}</span><button class="text-button" :disabled="pending" @click="logout">退出登录</button><span v-if="error" role="alert">{{ error }}</span></div>
    <App :key="user?.id || 'demo'" :account="user" @account-updated="user = $event" />
  </template>
</template>

<style scoped>
.password-options{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.auth-screen{min-height:100vh;display:grid;place-items:center;padding:24px;background:#f3f5fa}.auth-card{width:min(100%,420px);display:grid;gap:14px;background:white;padding:32px;border:1px solid #e1e6ef;border-radius:18px;box-shadow:0 12px 40px #1c326410}.auth-brand{font-size:20px;font-weight:750;color:#3663d8}.auth-card h1{font-size:26px;margin:4px 0}.auth-card p{color:#586478;margin:0;line-height:1.6}.auth-card label{display:grid;gap:7px;font-weight:600}.auth-card input{width:100%;min-width:0;padding:12px;border:1px solid #c6cfde;border-radius:8px;font:inherit}.auth-card small{color:#637087;line-height:1.5}.auth-card .auth-error{color:#b42318}.auth-account{position:fixed;z-index:40;bottom:14px;right:20px;background:white;border:1px solid #dbe2ef;border-radius:10px;padding:6px 12px;display:flex;align-items:center;gap:12px;box-shadow:0 4px 18px #1c326414;max-width:calc(100vw - 24px);flex-wrap:wrap}.auth-account span{overflow-wrap:anywhere}@media(max-width:500px){.auth-card{padding:22px}.auth-account{right:12px;bottom:8px}}
</style>
