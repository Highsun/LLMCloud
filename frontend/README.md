# LLMCloud 前端工作台

本目录使用现有 Vue3/Vite 技术栈，不引入 UI 库、路由库或图表依赖。界面覆盖工作台总览、数据集、微调配置、任务观测、推理和使用指南，支持桌面与移动端布局。Hash 导航支持直接访问与浏览器前进/后退。

## 启动与检查

要求 Node.js 22.18+ 的 22.x 或 24.12+。

```bash
cd frontend
npm ci
npm run dev
```

本地入口：http://127.0.0.1:5173/ 。生产构建：`npm run build`；自动检查：`npm test`。

`.env.example` 中 `VITE_API_BASE_URL` 配置业务 API 前缀，`VITE_BACKEND_URL` 配置开发代理目标。开发代理同时转发 `/api` 和 `/openapi.json`。生产反向代理需要提供这两条路径，Vite 开发代理不包含在 dist 中。跨域 API 需由后端正确配置 CORS；如果 OpenAPI 地址不同，可设置 `VITE_OPENAPI_URL`。

## 当前交付与接口边界

- 所有页面可以在后端离线时浏览，不填充虚构数据、任务状态或训练指标。
- 数据集实现 multipart 上传、真实传输进度、取消等待、错误明细、请求编号、分页、只读详情。上传只发送 file 和可选 name，不在浏览器中另写 JSONL 扫描器，内容以共享服务端校验为准。
- 上传成功需要收到 201 和资源 ID。成功后重新读取第一页；网络中断、超时、取消或异常响应不自动重传，提示先核对列表。传输 100% 不表示校验或入库完成。
- LoRA 表单遵循现有 TrainingConfig 范围和默认值，可独立导出配置草稿。没有选择实际数据集时，草稿的 dataset_id 为空，不能直接当作有效任务请求。页面切换保留待上传文件、配置和推理输入，刷新页面会清空；不持久化训练正文或生成记录。
- 工作台读取运行时 `/openapi.json` 判断接口是否存在，再启用相应操作。健康检查只表示 API 进程存活，模型目录只表示允许的模型，不展示推测的 GPU/Redis 状态。
- 任务页面具有分页、当前页状态筛选、每 2 秒轮询、详情、真实 Loss SVG 曲线、日志尾部和 Adapter 下载入口。切出任务页即停止轮询，浏览器页面隐藏时暂停请求；不支持取消训练、重试训练或恢复训练。
- 推理页面仅选择任务列表当前页中 COMPLETED 的任务，提交 task_id、prompt、max_new_tokens；409 显示 GPU 忙。前端提示词限制 8000 字符、输出限制 1–512 tokens 是当前界面限制，须在 M5 对照正式接口确认。基础模型对照为明确标识的手动记录，不伪造第二次模型调用。

当前仓库后端仅实现 health/models。M1-03 接入前，数据集上传入口不可提交；M3–M5 接入前，任务与推理入口不可提交。接口公开并不证明真实训练或 GPU 能力已通过验收，本次仅交付前端。

## M3–M5 联调约定

数据集严格按 `../docs/api/datasets.md` 实现。任务/指标/日志/推理目前只有规划，以下是隔离在前端适配层中的暂定读取方式，需等后端正式 Schema 完成后再联调，不构成新增共享契约：

| 接口                   | 当前前端读取                                                                                                         |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| GET tasks              | 分页对象 items、total；发送 page、page_size=20                                                                       |
| POST tasks             | dataset_id、base_model、config；读取 id 或 task_id                                                                   |
| GET tasks/{id}         | id、status、current_step、total_steps、created_at、started_at、finished_at、error_message、config 或 training_config |
| GET tasks/{id}/metrics | 数组或 items 数组；每项 step、loss，增量查询 after_step                                                              |
| GET tasks/{id}/logs    | lines 字符串数组、logs 字符串或 JSON 字符串，查询 tail=100                                                           |
| GET tasks/{id}/adapter | 成功时读取 Blob 并保存 ZIP，错误仍解析统一 ErrorResponse                                                             |
| POST inference         | 读取 generated_text、text 或 output 字符串                                                                           |

若实际响应不同，修改 `src/api.js`、`src/workspace.js` 及对应页面的读取函数；本次未修改后端、Worker、Trainer、共享 Schema 或 docs 契约。

## 验证范围

`npm test` 检查错误语义、断网/超时与不重复 POST、FormData 字段、上传结果不确定性、参数边界、各页面无后端时的服务端渲染、HTML 转义、能力发现与真实 Loss 绘制。测试中的网络和数据为隔离替身，不出现在产品界面。

这些检查不替代真实浏览器视觉验收、真实 HTTP 联调或 GPU 训练。数据集真实上传需等待 M1-03，任务与推理需等待对应后端阶段。

2026-10-21：18 项自动检查与生产构建通过，受保护的后端/调度/训练/共享文档无修改。浏览器工具的访问策略阻止本地页面读取，因此本轮未完成浏览器视觉验收与真实服务联调。
