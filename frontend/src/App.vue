<script setup>
import { onMounted, ref } from 'vue'
import { getHealth } from './api'

const status = ref('正在连接')
const connected = ref(false)
const checking = ref(false)
const detail = ref('检查 API 服务状态')

async function checkHealth() {
  checking.value = true
  status.value = '正在连接'
  connected.value = false
  try {
    const result = await getHealth()
    connected.value = true
    status.value = 'API 已连接'
    detail.value = `${result.service} · v${result.version}`
  } catch {
    status.value = 'API 未连接'
    detail.value = '请先启动后端服务，再重试连接。'
  } finally {
    checking.value = false
  }
}
onMounted(checkHealth)

const steps = [
  ['01', '上传数据集', '校验 JSONL 指令数据，建立训练数据资产。'],
  ['02', '配置微调', '选择基础模型，设置 LoRA 与训练参数。'],
  ['03', '异步训练', 'GPU Worker 执行任务，记录进度和 Loss。'],
  ['04', '验证与交付', '下载 Adapter，比较微调前后的模型表现。'],
]
</script>

<template>
  <div class="shell">
    <header>
      <a class="brand" href="/" aria-label="LLMCloud 首页"><span class="brand-icon">L</span>LLMCloud</a>
      <span class="course">云计算技术及应用 · 课程项目</span>
    </header>
    <main>
      <div class="eyebrow">PARAMETER-EFFICIENT FINE-TUNING</div>
      <section class="hero">
        <div>
          <h1>让模型微调，<br /><span>成为一项云服务。</span></h1>
          <p>从数据到模型，把参数高效微调流程连接起来。<br />异步任务调度、GPU 计算与训练过程观测，汇聚于同一工作台。</p>
          <span class="stage">项目初始化 · M0</span>
        </div>
        <aside class="status-card">
          <div class="card-label">服务连接</div>
          <div class="connection" role="status" aria-live="polite"><i :class="{ online: connected }"></i>{{ status }}</div>
          <p>{{ detail }}</p>
          <button :disabled="checking" @click="checkHealth">{{ checking ? '连接中…' : '重新检查连接 ↗' }}</button>
          <small>检查范围：API 进程。GPU 与队列尚未检测。</small>
        </aside>
      </section>
      <section class="workflow" aria-label="计划中的微调流程">
        <article v-for="[number, title, description] in steps" :key="number">
          <span class="step">{{ number }}</span>
          <h2>{{ title }}</h2>
          <p>{{ description }}</p>
          <span class="planned">待开发</span>
        </article>
      </section>
      <section class="foundation">
        <div><span class="card-label">初始模型</span><h2>Qwen2.5-0.5B-Instruct</h2></div>
        <p>以小模型跑通服务闭环，再扩展模型规模。<br />当前已建立项目骨架，训练任务功能将在后续阶段实现。</p>
      </section>
    </main>
    <footer><span>LLMCloud / 2026</span><span>FastAPI · Celery · Vue3 · LoRA</span></footer>
  </div>
</template>
