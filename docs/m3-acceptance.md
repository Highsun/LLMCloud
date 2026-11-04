# M3-07 真实服务验收与两人交接

更新：2026-11-04。当前在实施真实 GPU/Redis/SQL/生产浏览器自动验收，结果以独立运行 report.json 和 [A 工作日志](worklogs/2026-11-04-m3-07-a.md) 为准。队友的人工/异步证据复核另行记录，不以受控测试事件代替真实训练。

## A 的执行入口

在 WSL/Linux 仓库根目录，确认同一 GPU 没有其他手工训练/重载，服务端使用共用的 LOG_DIR/worker.lock：

```bash
uv sync --locked --extra training
uv run --locked --extra training python scripts/check_m3_acceptance.py --gpu
```

需 redis-server、Node/npm、frontend/node_modules 和可运行的 Playwright Chromium。初次模型准备沿用 [固定缓存说明](model-cache.md)，本入口只核验既有离线缓存，不自动下载模型。--gpu 是实际训练开关；未指定时拒绝运行。--run-dir 可选，必须是尚不存在的新目录。默认在忽略的 DATA_DIR/acceptance/m3-07/{UUID} 保留所有证据，失败也保留，不能覆盖旧运行。

主入口 scripts/check_m3_acceptance.py 启动私有 Redis Unix socket（含独立结果 DB）、隔离 SQLite/数据/输出、实际 FastAPI、Vite 和原生产 Worker。训练复用原 Trainer/固定 0.5B revision，API 的内部步数上限按场景切换，公开请求仍只含 dataset_id/config。LOG_DIR 沿用当前主机配置，以与其他实际 Worker 竞争同一物理 GPU 的锁；任务日志 UUID 独立。原业务 DB/队列不参与。

scripts/check_m3_browser.mjs 使用实际页面上传数据、配置并连续提交两任务，核对实际状态和桌面/390px 布局，保存截图/trace；没有 route 拦截、Publisher 替身或 /__test__ 控制。现有 npm run test:e2e 继续承担 M1/M3-05 的受控回归，不能替代本入口。

scripts/m3_acceptance_worker.py 仅供受控故障：在指定任务的真实 SQL before_commit/after_commit 或成功清单发布边界注入异常。生产 worker/tasks、启动钩子和 HTTP 应用不增加故障开关/控制路由。此类结果必须写明注入方式，不称为自然故障或真实 OOM。

## 自动验收范围

| 场景 | 必须记录的实际证据 |
| --- | --- |
| 浏览器上传/两任务成功 | 实际 HTTP/Redis/Worker/Qwen LoRA，独立任务/产物；UTC 训练区间不重叠，实际轮询至多一项 RUNNING，真实 GPU 峰值/指标/审计清单 |
| 请求/消息去重 | 原键 200、受控重复消息 skipped；任务时间/状态不变，不再次训练 |
| 完成回复丢失 | 真实 after_commit 注入后 SQL 仍 COMPLETED，产物有效，不被 fail 覆盖 |
| 有效产物与 SQL 回滚 | 真实 before_commit 注入后保留 RUNNING/有效清单；停 API/Worker，check/apply/check 恢复 COMPLETED |
| 保存失败 | 实际 LoRA 后注入清单发布异常，FAILED/ARTIFACT_WRITE_FAILED，有诊断/部分产物而无有效成功清单 |
| GPU 中断和排队遗留 | 实际优化器更新后仅杀本入口的 Worker；保留真实进度/文件，停机对账得 WORKER_INTERRUPTED 和 TASK_ABANDONED |
| 旧队列残留 | 对账后重启实际 Worker，终态消息 skipped，不重训 |
| 非法数据/缺缓存 | 仅篡改隔离数据文件以触发真实哈希校验；独立空缓存触发 MODEL_NOT_CACHED；产品不自动下载 |
| 生产页面失败/恢复 | 原页面查询真实 FAILED/恢复 COMPLETED，错误码/步数/进度正确，M4/M5 操作仍禁用 |

输入是显式工程格式草稿，证明服务链路，不是已人工审核的正式语料或效果提升实验；冻结评测题不参与训练/调参。COMPLETED 指训练保存与产物审计，不承诺每项任务已经生成或质量提升。

## 队友现在需要做什么

1. 同步 A 推送的最新 main，阅读本文件、当次 A 工作日志及生产 Worker/前端约定；保留自己的未提交改动并正常 merge，不覆盖 A 的脚本/后端。
2. 复核实际运行 report.json 的任务 ID、配置、UTC 起止时间、真实成功/失败和恢复结果；核对截图/trace 是生产服务，而不是 frontend/testing/serve_task_api.py。原数据/权重/DB/原始日志不提交 Git。
3. 在约定时段配合实际页面操作：上传、配置、连续两任务、原任务查询、刷新/筛选/分页、完成和失败详情；桌面及窄屏都检查。若 B 无法直连 A 的 WSL 服务，先异步复核 A 生成的证据，再约定同机/可访问环境的人工操作，不要求 B 在本机重跑 GPU。
4. 发现页面问题后，先反馈实际 task_id、request_id、操作步骤和预期/实际；只改 frontend，新增独立测试及 YYYY-MM-DD-m3-07-b.md 日志，附检查结果和未验收项。涉及共享 HTTP/Worker 语义先与 A 核对，不复制 SQL/Trainer 或扩大 M4/M5 范围。
5. 在独立日志中写明已复核哪些真实证据、人工操作是否完成、剩余问题；共同核对后才将 M3 全阶段完成项收口。GPU/共用服务测试安排一次中途同步，阻塞约 30 分钟时反馈具体问题。

当前不能将“入口已实现”当作上表全部通过，最终状态随真实运行结果更新。
