<script setup>
import { computed } from "vue";
import { formatDate, supports, taskStates, workspace } from "../workspace";
import AppIcon from "./AppIcon.vue";
import EmptyState from "./EmptyState.vue";

const recent = computed(() => workspace.tasks?.items.slice(0, 4) || []);
const steps = [
  {
    n: "01",
    icon: "data",
    title: "准备指令数据",
    desc: "上传 JSONL，管理训练输入。",
    href: "datasets",
    action: "管理数据",
  },
  {
    n: "02",
    icon: "sliders",
    title: "配置 LoRA 微调",
    desc: "选择数据集与训练超参数。",
    href: "training",
    action: "配置微调",
  },
  {
    n: "03",
    icon: "activity",
    title: "观察训练过程",
    desc: "查看真实 Loss、日志与状态。",
    href: "tasks",
    action: "查看任务",
  },
  {
    n: "04",
    icon: "chat",
    title: "验证模型表现",
    desc: "下载 Adapter，测试领域问答。",
    href: "inference",
    action: "测试推理",
  },
];
</script>

<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">YOUR FINETUNING WORKSPACE</div>
      <h1>工作台总览</h1>
      <p>从数据到模型，每一步都在这里。</p>
    </div>
    <a class="button primary" href="#training"
      ><AppIcon name="plus" size="18" />新建微调</a
    >
  </div>
  <section class="welcome-banner">
    <div class="welcome-copy">
      <span class="banner-kicker"
        ><span class="status-dot" />PARAMETER-EFFICIENT FINE-TUNING</span
      >
      <h2>小参数，<span>开启模型的新可能。</span></h2>
      <p>
        以 Qwen2.5 为起点，将你的领域知识融入模型。<br />数据、训练与验证，在一个工作台里有序连接。
      </p>
      <a class="button light" href="#datasets"
        >从上传数据开始<AppIcon name="arrow" size="17" /></a
      ><a class="banner-link" href="#guide"
        >查看使用指南<AppIcon name="external" size="14"
      /></a>
    </div>
    <div class="model-visual" aria-hidden="true">
      <div class="orbit orbit-one" />
      <div class="orbit orbit-two" />
      <div class="orbit orbit-three" />
      <div class="visual-cube">
        <AppIcon name="layers" size="64" /><span>LoRA</span>
      </div>
      <span class="orbit-label label-one">ADAPTER</span
      ><span class="orbit-label label-two">QWEN 2.5</span
      ><span class="orbit-node node-one" /><span
        class="orbit-node node-two"
      /><span class="orbit-node node-three" />
    </div>
  </section>
  <section class="stat-grid" aria-label="工作区概况">
    <article class="stat-card">
      <div>
        <span>数据集</span
        ><span class="stat-icon teal"><AppIcon name="data" /></span>
      </div>
      <strong>{{ workspace.datasets?.total ?? "—" }}<small>个</small></strong>
      <p>
        {{ workspace.datasets ? "已校验并保存的训练数据" : "等待数据服务连接" }}
      </p>
    </article>
    <article class="stat-card">
      <div>
        <span>训练任务</span
        ><span class="stat-icon blue"><AppIcon name="activity" /></span>
      </div>
      <strong>{{ workspace.tasks?.total ?? "—" }}<small>项</small></strong>
      <p>{{ workspace.tasks ? "来自实际任务记录" : "等待任务服务连接" }}</p>
    </article>
    <article class="stat-card">
      <div>
        <span>基础模型</span
        ><span class="stat-icon purple"><AppIcon name="layers" /></span>
      </div>
      <strong>{{ workspace.models.length || "—" }}<small>个</small></strong>
      <p>
        {{
          workspace.models.length ? "Qwen2.5-0.5B-Instruct" : "等待模型目录连接"
        }}
      </p>
    </article>
    <article class="stat-card">
      <div>
        <span>训练资源</span
        ><span class="stat-icon amber"><AppIcon name="chip" /></span>
      </div>
      <strong class="resource-value">单 GPU<small>串行</small></strong>
      <p>资源策略 · 实际 GPU 状态待检测</p>
    </article>
  </section>
  <div class="section-heading workflow-heading">
    <h2>开启一次微调实验</h2>
    <span class="subtle">四个步骤，连接完整流程</span>
  </div>
  <section class="workflow-grid">
    <a
      v-for="step in steps"
      :key="step.n"
      :href="`#${step.href}`"
      class="workflow-card"
      ><div>
        <span class="workflow-icon"
          ><AppIcon :name="step.icon" size="23" /></span
        ><span class="workflow-number">{{ step.n }}</span>
      </div>
      <h3>{{ step.title }}</h3>
      <p>{{ step.desc }}</p>
      <span class="workflow-action"
        >{{ step.action }}<AppIcon name="arrow" size="15" /></span
    ></a>
  </section>
  <div class="overview-lower">
    <section class="panel">
      <div class="section-heading">
        <h2>近期任务</h2>
        <a class="text-button" href="#tasks"
          >全部任务<AppIcon name="arrow" size="15"
        /></a>
      </div>
      <div v-if="recent.length" class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>任务</th>
              <th>状态</th>
              <th>创建时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in recent" :key="task.id">
              <td>
                <a class="mono" href="#tasks">{{ task.id.slice(0, 8) }}</a
                ><small>Qwen2.5-0.5B</small>
              </td>
              <td>
                <span
                  class="badge"
                  :class="taskStates[task.status]?.tone || 'neutral'"
                  >{{ taskStates[task.status]?.label || task.status }}</span
                >
              </td>
              <td>{{ formatDate(task.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState
        v-else
        icon="activity"
        :title="workspace.tasks ? '还没有训练任务' : '准备好你的第一场实验'"
        description="先上传指令数据，再配置你的第一次 LoRA 微调。"
        ><a class="text-button" href="#training"
          >前往配置<AppIcon name="arrow" size="15" /></a
      ></EmptyState>
    </section>
    <section class="panel service-panel">
      <div class="section-heading">
        <h2>服务状态</h2>
        <span class="badge neutral">实时检查</span>
      </div>
      <div
        v-for="[label, online, description] in [
          [
            'API 服务',
            Boolean(workspace.health),
            workspace.health
              ? `v${workspace.health.version} · 进程存活`
              : '等待后端连接',
          ],
          ['数据集接口', supports('/datasets'), '上传 / 列表 / 详情'],
          ['任务调度接口', supports('/tasks'), '任务记录与队列入口'],
          ['推理接口', supports('/inference', 'post'), 'Adapter 文本生成'],
        ]"
        :key="label"
        class="service-row"
      >
        <span class="status-dot" :class="online ? 'green' : 'muted-dot'" />
        <div>
          <strong>{{ label }}</strong
          ><small>{{ description }}</small>
        </div>
        <span class="service-label" :class="{ available: online }">{{
          online ? "已连接" : "待就绪"
        }}</span>
      </div>
      <div class="library-note">
        <AppIcon name="info" size="15" />
        <p>API 健康检查仅说明进程存活，GPU 与队列的实际状态仍需单独验证。</p>
      </div>
    </section>
  </div>
</template>
