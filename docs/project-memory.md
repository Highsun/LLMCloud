# 项目状态与协作记忆

梳理日期：2026-10-22。这是成员及 AI 助手的当前状态摘要；详细契约以 datasets.md 和 Pydantic Schema 为准，历史过程见工作日志。开始任务时仍须核对最新 Git、日志和实际代码。

## 项目目标与边界

LLMCloud 将 Qwen2.5-0.5B-Instruct 的 LoRA 微调封装成异步云服务。交付链路：上传数据 → 配置微调 → Celery 排队 → 单 GPU 真实训练 → Loss/日志 → Adapter 下载 → 测试推理。团队两人、每人每周 6–8 小时、八周完成，先实现单用户与单 GPU 闭环。

开发环境为 WSL2 Ubuntu、Python 3.12/uv、Node/Vue3/Vite；RTX 5070 12GB 用于本地训练验证。API 使用 FastAPI，SQLite 管元数据、本地文件管数据和产物，Redis/Celery 执行异步任务。当前不引入更大模型、量化、Kubernetes、多 GPU 或新的存储服务。

## 已确认的实现

| 范围 | 当前事实 |
| --- | --- |
| M0 | 工程、uv、健康检查、模型白名单、Redis/Celery ping、GPU 环境验证已完成 |
| M1-01/02/03 | 严格 JSONL 扫描、不可变数据集存储、迁移/审计、上传/分页/详情 API、统一错误与 request_id 已完成 |
| 成员 B 前端 | `5665ef2` 交付 Vue 工作台、数据集页面及后续阶段界面；`5114741` 合并 M1-03；`65fb120` 补交文档与日志 |
| M1-04 接续 | 在成员 B 页面基础上修复列表刷新竞态与窄屏溢出，22 项前端、8 项真实浏览器、61 项后端及生产构建通过；见 [接续日志](worklogs/2026-10-22-m1-04-integration.md) |
| M2–M5 | 真实预训练模型微调、业务调度、训练观测/下载和推理尚未实现；页面存在不代表服务已具备这些能力 |

`trainer.train`、`worker.train` 仍是明确报错的占位。极小随机模型的 GPU/LoRA 检查是环境证据，不能算 Qwen2.5 预训练模型真实微调完成。

## 必须延续的接口与实现决定

- 数据集 API 固定 `/api/v1/datasets`；上传只接收 file 和可选 name，成功 201，列表分页直接返回 DatasetPage，详情只读元数据。
- 文件上限 50 MiB、单物理行上限 1 MiB、multipart 总体上限 50 MiB + 64 KiB。UTF-8 JSONL，instruction/output 必填，input 可省略。上传与 Trainer 共用扫描器，前端不另写内容解析器。
- 原始字节、大小、行数和 SHA-256 由服务端产生；存储键为 `datasets/{UUID}/train.jsonl`，文件名不能决定路径；上传后不可变。
- 错误保留真实 HTTP 状态，用稳定 code 判断条件；request_id 由服务端生成。浏览器网络失败或取消后，上传可能已保存，不自动重传。
- 上传成功重新读取第一页；并发查询仅允许最新请求更新数据、错误与加载状态。
- 新库启动建表，旧库显式 `--check`/`--apply` 迁移，不删库。OpenAPI 从真实应用生成，不能恢复成手工维护的另一套设计稿。
- API 不加载 GPU 模型或直接训练；Trainer 不依赖 HTTP/Celery/SQL。后续单 Worker 串行执行，训练与推理互斥。

## 协作与下一步

成员 A 主负责后端/存储/调度，成员 B 当前主负责 frontend，后续承担训练。保留成员 B 的组件、样式和页面结构；必要修复以最小变更配合回归验证，并在新日志说明原因。不要覆写历史交付记录。

每次任务及提交前 fetch、检查工作区、阅读新增工作日志与相关代码；提交仅包含本次任务文件。测试使用独立临时库，不能把自动化上传留在实际业务数据中。

M1 结束前仍须完成 M1-05 全量联调/故障验收与轻量 CI、M1-06 数据来源、划分与固定测试问题。之后进入 M2：先以独立 Trainer 训练 0.5B 模型，保存并在独立进程重载 Adapter，再在 M3 接入 Celery。

入口：[项目规划](project-plan.md)、[数据集契约](api/datasets.md)、[成员 B 日志](worklogs/2026-10-21-m1-04-frontend.md)、[日志索引](worklogs/README.md)。
