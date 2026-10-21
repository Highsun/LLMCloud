# LLMCloud 协作约束

本文件是项目成员及其 AI 助手进入仓库后的阅读入口，适用于整个仓库。当前用户的明确任务优先；以下规则用于维持接口一致与开发范围，不新增额外审批流程。

## 先理解项目

LLMCloud 是《云计算技术及应用》课程项目：将 Qwen2.5-0.5B-Instruct 的 LoRA 微调封装为异步云服务。目标流程是数据上传、配置训练、任务排队、真实训练、Loss/日志观测、Adapter 下载与测试推理。

团队 2 人，每人每周 6–8 小时，按八周规划推进。先交付单用户、单 GPU 的完整闭环。

阅读顺序：

1. [README.md](README.md)：启动入口与已实现范围。
2. [docs/project-plan.md](docs/project-plan.md)：M0–M5、任务编号和分工。
3. [docs/requirements.md](docs/requirements.md)、[docs/architecture.md](docs/architecture.md)：全局需求与模块边界。
4. [docs/api/datasets.md](docs/api/datasets.md)：M1 数据集接口和文件契约。
5. [docs/environment.md](docs/environment.md)：本机环境；其中绝对路径与代理地址不能作为跨机器固定配置。

## 当前事实与任务边界

- M0 环境和骨架已完成。健康检查、模型目录与 Celery ping 已实现。
- M1-01 交付接口约定、Pydantic Schema、离线 OpenAPI 设计稿和样例。
- M1-02 已完成共享 JSONL 扫描器、数据集创建/查询服务、失败清理/只读审计、新字段及 SQLite 显式迁移；详见 [工作日志](docs/worklogs/2026-10-21-m1-02.md)。
- M1-03 已完成数据集上传/列表/详情 HTTP 路由、multipart/请求体限制、request_id、统一错误与运行时 OpenAPI；详见 [工作日志](docs/worklogs/2026-10-21-m1-03.md)。M1-04 页面、M1-05 浏览器联调和 M1-06 数据准备仍需验收，M1 完成后再进入 M2。
- `trainer.dataset.iter_records` 与上传服务共用 DatasetScanner/InstructionRecord，不能另写一套宽松的文件校验。
- 新库启动直接创建新表，旧库先运行 `scripts/migrate_datasets.py --check`，确认报告后显式 `--apply`；禁止用 create_all 或删库替代迁移。
- `trainer.train` 和 `worker.train` 仍是占位。极小随机模型验证成功，不代表预训练模型微调功能完成。
- 每次开始任务及提交/推送前检查实际代码、Git 状态与 [工作日志目录](docs/worklogs/README.md)，读取组员新增日志及相关改动；有远端更新先核对再同步，不能用覆盖文件或强推消除差异。阶段状态变化时同步更新此处与规划，不把约定或 mock 写成已实现能力。

## 技术与资源边界

- Python 3.12、uv、FastAPI、SQLAlchemy/SQLite、Redis/Celery、Vue3/Vite、PyTorch/Hugging Face/PEFT/TRL。
- 依赖声明只维护 `pyproject.toml`，版本锁定在 `uv.lock`。服务运行用 `uv run --locked`；训练机器同步用 `uv sync --locked --extra training`。
- requirements 文件由 `bash scripts/export_requirements.sh` 导出，不能单独手改。
- API 不加载 GPU 模型，不在 HTTP 请求中直接训练；GPU 计算由单 Worker 执行，训练与推理互斥。
- 先使用 0.5B 模型、本地文件和单机 SQLite。未经本次任务要求，不引入更大模型、Kubernetes、多 GPU、量化或新的基础设施。
- 不为了前端展示伪造任务状态、进度、Loss 或训练产物。mock 必须标为 mock，并与真实 API 调用区分。

## 接口与数据边界

- 对外字段使用 snake_case，资源 ID 是服务端生成的 UUID，时间输出为 UTC/RFC 3339。
- 成功响应直接返回资源或分页对象，错误返回统一 ErrorResponse，保持真实 HTTP 状态码。
- 业务条件看稳定错误 code，message 用于展示，前端不能解析中文文案判断错误类型。
- 客户端不能提交服务器路径、用户归属、统计值或数据集哈希；不能把本机绝对路径写入响应。
- 数据集上传后不可变。文件存于 DATA_DIR/datasets/{dataset_id}/train.jsonl，数据库保存相对 DATA_DIR 的键；文件名不决定存储路径。
- 元数据入库与文件操作由 services 负责；api 负责 HTTP/序列化，models 负责类型；Trainer 不依赖 FastAPI/Celery/数据库。
- 不把数据、模型权重、数据库、日志、.env 或凭据提交到 Git。

## 合作与契约修改

- 成员 A 主负责后端/存储/调度，成员 B 当前主负责 frontend，之后负责训练；可按实际任务调整，不代表文件访问限制。交付任务时新增工作日志，写清接口影响、验证和待交接项。
- 修改共享字段、默认值、上限或错误语义时，在同一变更中更新 Schema、接口文档、OpenAPI 和样例，说明兼容性影响；常规实现不必反复请求确认。
- 标准查阅以本次用户要求为先；M1 字段与行为以 datasets.md 为准，类型约束以对应 Pydantic Schema 为准。两者冲突应在实现前修正，不能静默选择一份忽略另一份。
- 数据集 OpenAPI 由 `uv run --locked python scripts/export_dataset_contract.py` 从真实应用 `.openapi()` 导出，不手改生成文件；`--check` 检查漂移。导出文件使用 `/api/v1` server 与相对 paths，运行时 `/openapi.json` 使用完整 paths，操作与 Schema 必须一致。
- 新增不兼容字段/行为先更新契约版本并写明迁移方式；在已有已发布客户端依赖时，不兼容改动另开 API 主版本。
- 进入实施阶段以 OpenAPI 与真实后端响应一致作为验收条件，不能长期维护两套不同契约。
- 每个任务交付包含改动、验证、未完成项。验证聚焦行为、失败处理和接口一致性；文档或契约任务不要求执行完整 GPU 训练。
- 默认保留他人的未提交改动，不擅自覆盖；提交仅包含当前任务相关文件。分支/PR 按团队实际工作方式使用，Git 同步沿用用户授权范围。
