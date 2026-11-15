<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { advanceSessionGeneration, request, SESSION_ENDED_EVENT } from "./api";
import { formatDate, refreshWorkspace, switchWorkspaceAccount, workspace } from "./workspace";
import AppIcon from "./components/AppIcon.vue";
import AccountPanel from "./components/AccountPanel.vue";
import AuthPanel from "./components/AuthPanel.vue";
import ErrorNotice from "./components/ErrorNotice.vue";
import OverviewPanel from "./components/OverviewPanel.vue";
import DatasetPanel from "./components/DatasetPanel.vue";
import TrainingPanel from "./components/TrainingPanel.vue";
import TasksPanel from "./components/TasksPanel.vue";
import InferencePanel from "./components/InferencePanel.vue";
import GuidePanel from "./components/GuidePanel.vue";

const pages = [
  {
    id: "overview",
    label: "工作台总览",
    icon: "grid",
    component: OverviewPanel,
  },
  { id: "datasets", label: "数据集", icon: "data", component: DatasetPanel },
  {
    id: "training",
    label: "配置微调",
    icon: "sliders",
    component: TrainingPanel,
  },
  { id: "tasks", label: "训练任务", icon: "activity", component: TasksPanel },
  {
    id: "inference",
    label: "推理实验室",
    icon: "chat",
    component: InferencePanel,
  },
  { id: "guide", label: "使用指南", icon: "book", component: GuidePanel },
  { id: "account", label: "用户中心", component: AccountPanel },
];
const current = ref("overview");
const sidebarOpen = ref(false);
const main = ref(null);
const account = ref(null);
const checkingSession = ref(true);
const sessionError = ref(null);
const sessionMessage = ref("");
const signingOut = ref(false);
const signOutError = ref(null);
let intendedPage = "overview";
const avatar = computed(() => Array.from(account.value?.display_name || "用")[0]);
const page = computed(
  () => pages.find((item) => item.id === current.value) || pages[0],
);

function replaceRoute(target) {
  if (window.location.hash !== `#${target}`) window.history.replaceState(null, "", `#${target}`);
}

function navigate(focus = true) {
  const hash = window.location.hash.slice(1);
  const workspacePage = pages.some((item) => item.id === hash);
  if (!account.value) {
    if (workspacePage) intendedPage = hash;
    current.value = hash === "register" ? "register" : "login";
    replaceRoute(current.value);
    document.title = `${current.value === "register" ? "注册" : "登录"} · LLMCloud`;
    return;
  }
  current.value = workspacePage ? hash : "overview";
  replaceRoute(current.value);
  sidebarOpen.value = false;
  document.title = `${page.value.label} · LLMCloud`;
  if (focus)
    nextTick(() => {
      main.value?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    });
}
function hashChanged() {
  if (!checkingSession.value) navigate();
}

function openWorkspace(user, target) {
  if (!user?.id || !user.display_name) throw new Error("账号响应格式不正确，请重新登录。");
  advanceSessionGeneration();
  switchWorkspaceAccount(user.id);
  account.value = user;
  signOutError.value = null;
  sessionMessage.value = "";
  if (target) replaceRoute(target);
  navigate();
  intendedPage = "overview";
  refreshWorkspace();
}

async function restoreSession() {
  checkingSession.value = true;
  sessionError.value = null;
  try {
    openWorkspace(await request("/auth/me"));
  } catch (cause) {
    if (cause.code === "AUTH_REQUIRED") navigate(false);
    else sessionError.value = cause;
  } finally {
    checkingSession.value = false;
  }
}

function onAuthenticated(user, created) {
  openWorkspace(user, created ? "account" : intendedPage);
}

function clearSession(message, rememberPage = false) {
  intendedPage = rememberPage ? current.value : "overview";
  advanceSessionGeneration();
  switchWorkspaceAccount(null);
  account.value = null;
  sessionMessage.value = message;
  sidebarOpen.value = false;
  replaceRoute("login");
  navigate(false);
}

function onSessionEnded() {
  if (account.value) clearSession("会话已过期，请重新登录。", true);
}

async function logout() {
  if (signingOut.value) return;
  signingOut.value = true;
  signOutError.value = null;
  try {
    await request("/auth/logout", { method: "POST" });
    clearSession("");
  } catch (cause) {
    signOutError.value = cause;
  } finally {
    signingOut.value = false;
  }
}

onMounted(() => {
  window.addEventListener("hashchange", hashChanged);
  window.addEventListener(SESSION_ENDED_EVENT, onSessionEnded);
  restoreSession();
});
onBeforeUnmount(() => {
  window.removeEventListener("hashchange", hashChanged);
  window.removeEventListener(SESSION_ENDED_EVENT, onSessionEnded);
});
</script>

<template>
  <main v-if="checkingSession || sessionError" class="account-entry">
    <section class="panel account-card">
      <h1>LLMCloud</h1>
      <p v-if="checkingSession" role="status">正在验证会话…</p>
      <template v-else>
        <ErrorNotice :error="sessionError" />
        <button type="button" class="button primary" @click="restoreSession">重新连接</button>
      </template>
    </section>
  </main>
  <AuthPanel v-else-if="!account" :mode="current" :message="sessionMessage" @authenticated="onAuthenticated" />
  <template v-else>
    <a class="skip-link" href="#workspace-main" @click.prevent="main?.focus()"
    >跳转到主要内容</a
  >
  <div class="app-shell">
    <div
      v-if="sidebarOpen"
      class="sidebar-backdrop"
      @click="sidebarOpen = false"
    />
    <aside
      id="main-navigation"
      class="sidebar"
      :class="{ 'is-open': sidebarOpen }"
    >
      <a class="brand" href="#overview" aria-label="LLMCloud 首页"
        ><span class="brand-symbol"><AppIcon name="cloud" size="25" /></span
        ><span>LLMCloud<small>模型微调工作台</small></span></a
      >
      <div class="workspace-switch">
        <span class="workspace-avatar">L</span>
        <div><strong>个人工作空间</strong><small>模型微调</small></div>
      </div>
      <div class="nav-label">工作空间</div>
      <nav aria-label="主导航">
        <a
          v-for="item in pages.slice(0, 5)"
          :key="item.id"
          :href="`#${item.id}`"
          :class="{ active: current === item.id }"
          :aria-current="current === item.id ? 'page' : undefined"
          ><AppIcon :name="item.icon" size="19" /><span>{{ item.label }}</span
          ><span
            v-if="item.id === 'tasks' && workspace.tasks?.total"
            class="nav-count"
            >{{ workspace.tasks.total }}</span
          ></a
        >
      </nav>
      <div class="nav-label resource-nav-label">支持与资源</div>
      <nav aria-label="资源导航">
        <a
          href="#guide"
          :class="{ active: current === 'guide' }"
          :aria-current="current === 'guide' ? 'page' : undefined"
          ><AppIcon name="book" size="19" />使用指南</a
        ><a
          href="https://github.com/Highsun/LLMCloud"
          target="_blank"
          rel="noopener noreferrer"
          ><AppIcon name="external" size="19" />项目仓库<AppIcon
            class="nav-external"
            name="external"
            size="12"
        /></a>
      </nav>
      <div class="sidebar-bottom">
        <div class="environment-card">
          <div>
            <span
              class="status-dot"
              :class="workspace.health ? 'green' : 'muted-dot'"
            /><strong>{{
              workspace.health
                ? "API 已连接"
                : workspace.checking
                  ? "正在连接服务"
                  : "API 未连接"
            }}</strong>
          </div>
          <p>Qwen2.5 · LoRA<br />单 GPU 串行训练</p>
          <span>本地开发环境</span>
        </div>
        <a href="#account" class="sidebar-footer account-navigation"
          :aria-current="current === 'account' ? 'page' : undefined">
          <span class="user-avatar" aria-hidden="true">{{ avatar }}</span>
          <div><strong>{{ account.display_name }}</strong><small>用户中心</small></div>
        </a>
      </div>
    </aside>
    <div class="workspace-body">
      <header class="topbar">
        <div class="breadcrumbs">
          <button
            class="icon-button mobile-menu"
            aria-label="切换导航菜单"
            aria-controls="main-navigation"
            :aria-expanded="sidebarOpen"
            @click="sidebarOpen = !sidebarOpen"
          >
            <AppIcon name="menu" /></button
          ><span class="breadcrumb-home">工作空间</span
          ><AppIcon name="chevron" size="13" /><strong>{{ page.label }}</strong>
        </div>
        <div class="topbar-actions">
          <span class="environment-badge"
            ><span
              class="status-dot"
              :class="workspace.health ? 'green' : 'muted-dot'"
            />{{
              workspace.health
                ? "API 在线"
                : workspace.checking
                  ? "连接中"
                  : "本地工作台"
            }}</span
          ><button
            class="icon-button"
            :disabled="workspace.checking"
            aria-label="刷新服务状态"
            title="刷新服务状态"
            @click="refreshWorkspace"
          >
            <AppIcon
              name="refresh"
              size="17"
              :class="{ spinning: workspace.checking }"
            /></button
          ><span class="topbar-divider" /><a href="#account" class="user-avatar small"
            aria-label="用户中心" :aria-current="current === 'account' ? 'page' : undefined">{{ avatar }}</a>
        </div>
      </header>
      <main id="workspace-main" ref="main" tabindex="-1" class="main-content">
        <div
          v-if="!workspace.health && !workspace.checking && workspace.checkedAt"
          class="connection-banner"
          role="status"
        >
          <AppIcon name="info" size="17" /><span
            >后端尚未连接，仍可浏览工作台、准备数据和配置参数。</span
          ><button class="text-button" @click="refreshWorkspace">
            重新连接<AppIcon name="arrow" size="14" />
          </button>
        </div>
        <div
          v-if="workspace.health && workspace.discoveryError && !workspace.checking"
          class="connection-banner"
          role="status"
        >
          <AppIcon name="info" size="17" />
          <span>服务能力检查未完成，上传与提交暂不可用。</span>
          <button class="text-button" @click="refreshWorkspace">刷新重试</button>
        </div>
        <AccountPanel v-if="page.id === 'account'" :account="account" :signing-out="signingOut"
          :sign-out-error="signOutError" @updated="account = $event" @logout="logout" />
        <KeepAlive :include="['DatasetPanel', 'TrainingPanel', 'InferencePanel']"
          ><component v-if="page.id !== 'account'" :is="page.component"
        /></KeepAlive>
        <footer class="page-footer">
          <span
            >LLMCloud
            <span class="footer-dot">·</span> 让模型微调成为一项云服务</span
          ><span>{{
            workspace.checkedAt
              ? `上次服务检查 ${formatDate(workspace.checkedAt)}`
              : "Vue3 · FastAPI · LoRA"
          }}</span>
        </footer>
      </main>
    </div>
  </div>
  </template>
</template>
