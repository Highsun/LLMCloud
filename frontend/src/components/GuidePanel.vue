<script setup>
import AppIcon from "./AppIcon.vue";
const guides = [
  [
    "01",
    "准备训练数据",
    "使用 UTF-8 JSONL，每行一个指令对象。instruction 与 output 为非空字符串，input 可省略。单文件不超过 50 MiB，单物理行不超过 1 MiB。",
    "datasets",
    "前往数据集",
  ],
  [
    "02",
    "配置训练参数",
    "初始模型为 Qwen2.5-0.5B-Instruct。建议从 Rank 8、Alpha 16、序列长度 512、batch size 1 开始；先用小数据验证训练与产物重载。",
    "training",
    "配置一次实验",
  ],
  [
    "03",
    "观察真实训练",
    "提交后由 GPU Worker 串行执行。任务可能正在派发、排队或加载模型；暂时没有 Loss 是正常情况。遇到失败请查看原因与任务日志。",
    "tasks",
    "查看训练任务",
  ],
  [
    "04",
    "验证与交付",
    "训练完成后下载 Adapter，在独立进程重载验证。使用固定测试问题，保持解码条件一致，记录基础模型与微调模型的实际回答。",
    "inference",
    "打开推理实验室",
  ],
];
</script>
<template>
  <div class="page-heading">
    <div>
      <div class="eyebrow">GETTING STARTED</div>
      <h1>使用指南</h1>
      <p>让每一次微调都可观察、可交付、可复现。</p>
    </div>
    <span class="badge green">单用户实验工作台</span>
  </div>
  <div class="guide-layout">
    <div class="stack">
      <article
        v-for="[number, title, text, href, action] in guides"
        :key="number"
        class="panel guide-card"
      >
        <span class="guide-number">{{ number }}</span>
        <div>
          <h2>{{ title }}</h2>
          <p>{{ text }}</p>
          <a class="text-button" :href="`#${href}`"
            >{{ action }}<AppIcon name="arrow" size="16"
          /></a>
        </div>
      </article>
    </div>
    <aside class="stack">
      <section class="panel">
        <h2>实验复现清单</h2>
        <ul class="check-list">
          <li
            v-for="item in [
              '模型 revision 与代码版本',
              '数据来源、划分与 SHA-256',
              '训练参数、随机种子与环境',
              '真实 Loss、耗时与显存峰值',
              'Adapter 与产物清单',
              '相同问题下的前后输出',
            ]"
            :key="item"
          >
            <AppIcon name="check" size="16" />{{ item }}
          </li>
        </ul>
      </section>
      <section class="panel faq-panel">
        <h2>常见问题</h2>
        <details open>
          <summary>为什么有些操作暂不可用？</summary>
          <p>
            页面依据当前服务公开的接口启用功能。服务尚未接入时，可先准备文件和配置，待服务就绪后点击右上角刷新。
          </p>
        </details>
        <details>
          <summary>上传中断后该怎么办？</summary>
          <p>
            先刷新数据集列表确认是否已保存，再决定是否重新上传。重复上传相同文件会创建新的数据集。
          </p>
        </details>
        <details>
          <summary>能同时训练和推理吗？</summary>
          <p>
            当前采用单 GPU
            互斥策略。训练期间推理可能返回资源忙，请等待任务结束后再试。
          </p>
        </details>
        <details>
          <summary>Loss 越低，模型一定越好吗？</summary>
          <p>
            训练 Loss
            只是一个指标。请结合独立测试问题检查实际表现，并记录无提升与退化案例。
          </p>
        </details>
      </section>
    </aside>
  </div>
</template>
