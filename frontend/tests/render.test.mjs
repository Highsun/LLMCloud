import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer } from "vite";
import { h } from "vue";
import { renderToString } from "@vue/server-renderer";

let server, workspace, supports, refreshWorkspace;
const originalWindow = globalThis.window;
before(async () => {
  globalThis.window = { location: { origin: "http://localhost" } };
  server = await createServer({
    server: { middlewareMode: true, hmr: false, watch: null },
    appType: "custom",
  });
  ({ workspace, supports, refreshWorkspace } = await server.ssrLoadModule("/src/workspace.js"));
});
after(async () => {
  await server?.close();
  globalThis.window = originalWindow;
});

async function render(name, props) {
  const { default: component } = await server.ssrLoadModule(
    `/src/components/${name}.vue`,
  );
  return renderToString(h(component, props));
}

test("六个页面在没有后端数据时均可渲染", async () => {
  for (const [name, heading] of [
    ["OverviewPanel", "工作台总览"],
    ["DatasetPanel", "数据集"],
    ["TrainingPanel", "配置微调"],
    ["TasksPanel", "训练任务"],
    ["InferencePanel", "推理实验室"],
    ["GuidePanel", "使用指南"],
  ]) {
    const html = await render(name);
    assert.ok(html.includes(heading), name);
    assert.ok(
      !html.includes("03a853e2-1bf1-45da-92fb-5a1548499fc4"),
      "不将契约样例当作真实记录",
    );
  }
});

test("接口能力检测不依赖 OpenAPI 路径参数的变量名称", () => {
  workspace.paths = { "/api/v1/tasks/{id}/metrics": { get: {} } };
  assert.equal(supports("/tasks/{task_id}/metrics"), true);
  assert.equal(supports("/tasks/{task_id}/metrics", "post"), false);
  assert.equal(supports("/datasets"), false);
});

test("数据列表保留服务端排序并对名称做 HTML 转义", async () => {
  workspace.datasets = {
    items: [
      {
        id: "first",
        name: "<script>alert(1)</script>",
        row_count: 3,
        size_bytes: 625,
        created_at: "2026-10-19T08:00:00Z",
      },
      {
        id: "second",
        name: "第二份数据",
        row_count: 1,
        size_bytes: 88,
        created_at: "2026-10-18T08:00:00Z",
      },
    ],
    total: 2,
    page: 1,
    page_size: 20,
    total_pages: 1,
  };
  const html = await render("DatasetPanel");
  assert.ok(html.includes("&lt;script&gt;alert(1)&lt;/script&gt;"));
  assert.ok(!html.includes("<script>alert"));
  assert.ok(html.indexOf("&lt;script&gt;") < html.indexOf("第二份数据"));
  workspace.datasets = null;
});

test("Loss 图只使用有限的真实指标，空数据不画虚构曲线", async () => {
  const empty = await render("LossChart", { points: [] });
  assert.ok(empty.includes("等待第一条训练指标"));
  assert.ok(!empty.includes("<polyline"));
  const real = await render("LossChart", {
    points: [
      { step: 3, loss: 0.8 },
      { step: 1, loss: 1.4 },
      { step: 4, loss: null },
    ],
  });
  assert.ok(real.includes("共 2 个真实数据点"));
  assert.ok(real.includes("0.8000"));
  assert.ok(!real.includes("NaN"));
});

test("错误提示输出字段位置和请求编号，安全转义消息", async () => {
  const html = await render("ErrorNotice", {
    error: {
      message: "<b>错误</b>",
      requestId: "req-123",
      details: [
        {
          line: 2,
          column: 8,
          loc: ["body", "file", "output"],
          message: "缺少字段",
        },
      ],
    },
  });
  assert.ok(html.includes("&lt;b&gt;错误&lt;/b&gt;"));
  assert.ok(html.includes("第 2 行，第 8 列"));
  assert.ok(html.includes("req-123"));
});

test("现有 M0 接口可连接，但不会错误启用尚未实现的数据上传", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(url);
    if (url.endsWith('/health')) return Response.json({ status: 'ok', service: 'LLMCloud', version: '0.1.0' });
    if (url.endsWith('/models')) return Response.json([{ id: 'Qwen/Qwen2.5-0.5B-Instruct', name: 'Qwen2.5' }]);
    if (url.endsWith('/openapi.json')) return Response.json({ paths: { '/api/v1/health': { get: {} }, '/api/v1/models': { get: {} } } });
    throw new Error(`不应请求未实现的接口：${url}`);
  };
  try {
    await refreshWorkspace();
    assert.equal(workspace.health.service, 'LLMCloud');
    assert.equal(workspace.models.length, 1);
    assert.equal(supports('/datasets', 'post'), false);
    assert.equal(workspace.datasets, null);
    assert.equal(calls.length, 3);
    assert.ok((await render('DatasetPanel')).includes('上传服务尚未就绪'));
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("工作台外壳包含可访问导航与移动端菜单入口", async () => {
  const { default: App } = await server.ssrLoadModule('/src/App.vue');
  const html = await renderToString(h(App));
  assert.ok(html.includes('跳转到主要内容'));
  assert.ok(html.includes('切换导航菜单'));
  assert.ok(html.includes('aria-current="page"'));
  assert.ok(html.includes('工作台总览'));
});
