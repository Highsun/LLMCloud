<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { formatDate, refreshWorkspace, workspace } from "./workspace";
import AppIcon from "./components/AppIcon.vue";
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
];
const current = ref("overview");
const sidebarOpen = ref(false);
const main = ref(null);
const page = computed(
  () => pages.find((item) => item.id === current.value) || pages[0],
);
function navigate(focus = true) {
  const hash = window.location.hash.slice(1);
  current.value = pages.some((item) => item.id === hash) ? hash : "overview";
  sidebarOpen.value = false;
  document.title = `${page.value.label} · LLMCloud`;
  if (focus)
    nextTick(() => {
      main.value?.focus({ preventScroll: true });
      window.scrollTo(0, 0);
    });
}
function hashChanged() {
  navigate();
}
onMounted(() => {
  navigate(false);
  window.addEventListener("hashchange", hashChanged);
  refreshWorkspace();
});
onBeforeUnmount(() => window.removeEventListener("hashchange", hashChanged));
</script>

<template>
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
        <div><strong>个人工作空间</strong><small>单用户 · 实验环境</small></div>
        <span class="workspace-tag">MVP</span>
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
        <div class="sidebar-footer">
          <span class="user-avatar">研</span>
          <div>
            <strong>研究工作空间</strong><small>云计算技术及应用</small>
          </div>
          <span class="version">v0.1</span>
        </div>
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
          ><span class="topbar-divider" /><span class="user-avatar small"
            >研</span
          >
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
        <KeepAlive :include="['DatasetPanel', 'TrainingPanel', 'InferencePanel']"
          ><component :is="page.component"
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
