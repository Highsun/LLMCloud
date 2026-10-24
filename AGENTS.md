# LLMCloud 协作约束

本文件是项目成员及其 AI 助手进入仓库后的阅读入口，适用于整个仓库。当前用户的明确任务优先；以下规则用于维持接口一致与开发范围，不新增额外审批流程。

## 先理解项目

LLMCloud 是《云计算技术及应用》课程项目：将 Qwen2.5-0.5B-Instruct 的 LoRA 微调封装为异步云服务。目标流程是数据上传、配置训练、任务排队、真实训练、Loss/日志观测、Adapter 下载与测试推理。

团队 2 人，每人每周 6–8 小时，按八周规划推进。先交付单用户、单 GPU 的完整闭环。

阅读顺序：

1. [README.md](README.md)：启动入口与已实现范围。
2. [docs/project-memory.md](docs/project-memory.md)：当前实现、前端交付和必须延续的决定；[docs/project-plan.md](docs/project-plan.md)：M0–M5、任务编号和分工。
3. [docs/requirements.md](docs/requirements.md)、[docs/architecture.md](docs/architecture.md)：全局需求与模块边界。
4. [docs/api/datasets.md](docs/api/datasets.md)：M1 数据集接口和文件契约。
5. [docs/environment.md](docs/environment.md)：本机环境；其中绝对路径与代理地址不能作为跨机器固定配置。

执行 M2 前继续读 [docs/m2-development-plan.md](docs/m2-development-plan.md)：六项任务、依赖、主改文件与验收；再读 [内部训练契约 1.0.0](docs/contracts/training.md)、[模型缓存](docs/model-cache.md) 和 [训练数据](docs/training-data.md)。类型/缓存/数据处理及 M2-04 真实 LoRA 已交付；继续读 [训练入口](docs/training.md)。M2-05 [独立产物审计与故障验收](docs/training-artifacts.md) 已完成，M2-06 新进程重载工程验收已完成，不能把训练保存成功当作完整 M2 验收。

执行 M3 前继续读 [M3 开发计划](docs/m3-development-plan.md)、[任务 API 设计草案](docs/api/tasks.md) 和 [两人交接](docs/m3-handoff.md)。当前只完成规划，M3-01～07 未实现。先共同交付 CPU 类型/Protocol，再 A 实现 SQL/迁移/API/派发/离线对账，B 实现 Worker/单实例保护及现有前端接通；具体文件归属以该计划为准，不延用“A 独自做全部 Worker”的旧排期。01 接口核对、真实仓储装配和最终 Redis/GPU/浏览器联调需要合作，不能以 mock 验收代替。

## 当前事实与任务边界

- M0 环境和骨架已完成。健康检查、模型目录与 Celery ping 已实现。
- M1-01 交付接口约定、Pydantic Schema、离线 OpenAPI 设计稿和样例。
- M1-02 已完成共享 JSONL 扫描器、数据集创建/查询服务、失败清理/只读审计、新字段及 SQLite 显式迁移；详见 [工作日志](docs/worklogs/2026-10-21-m1-02.md)。
- M1-03 已完成数据集上传/列表/详情 HTTP 路由、multipart/请求体限制、request_id、统一错误与运行时 OpenAPI；详见 [工作日志](docs/worklogs/2026-10-21-m1-03.md)。M1-04 已在成员 B 页面基础上完成数据集浏览器功能验收及局部修复，见 [接续日志](docs/worklogs/2026-10-22-m1-04-integration.md)。M1-05 故障验收/CPU CI 已完成且 GitHub 首次运行成功，见 [日志](docs/worklogs/2026-10-22-m1-05.md)。M1-06 来源说明、可复现划分工具和 12 道冻结题已交付，见 [数据说明](docs/data/README.md)。M1 计划范围已验收，可进入 M2；正式语料仍需人工编写/审核。
- `trainer.dataset.iter_records` 与上传服务共用 DatasetScanner/InstructionRecord，不能另写一套宽松的文件校验。
- 新库启动直接创建新表，旧库先运行 `scripts/migrate_datasets.py --check`，确认报告后显式 `--apply`；禁止用 create_all 或删库替代迁移。
- `trainer.train` 已实现单 GPU 真实 LoRA 与 CLI，`worker.train` 仍是占位，业务调度属于 M3。真实训练证据见 [M2-04 日志](docs/worklogs/2026-10-23-m2-04.md)，格式草稿不代表效果提升。
- M2-01 契约、M2-02 模型准备、M2-03 数据转换/监督标签/截断/清单核对已完成，见 [数据处理](docs/training-data.md) 和 [M2-03 日志](docs/worklogs/2026-10-22-m2-03.md)。M2-04 训练/指标/回调及基础保存已完成；M2-05 共享产物校验器/独立 CPU 命令与保存故障验收已完成，见 [日志](docs/worklogs/2026-10-23-m2-05.md)；M2-06 新进程重载工程验收已完成。任务 HTTP/Celery 业务调度属 M3，在线推理属 M5。
- 每次开始任务及提交/推送前检查实际代码、Git 状态与 [工作日志目录](docs/worklogs/README.md)，读取组员新增日志及相关改动；有远端更新先核对再同步，不能用覆盖文件或强推消除差异。阶段状态变化时同步更新此处与规划，不把约定或 mock 写成已实现能力。

## 技术与资源边界

- Python 3.12、uv、FastAPI、SQLAlchemy/SQLite、Redis/Celery、Vue3/Vite、PyTorch/Hugging Face/PEFT/TRL。
- 基础 safetensors 用于 CPU 产物审计，不加载 torch/numpy/HF；训练库仍只在执行时导入。依赖声明只维护 `pyproject.toml`，版本锁定在 `uv.lock`。服务运行用 `uv run --locked`；训练机器同步用 `uv sync --locked --extra training`。
- requirements 文件由 `bash scripts/export_requirements.sh` 导出，不能单独手改。
- API 不加载 GPU 模型，不在 HTTP 请求中直接训练；GPU 计算由单 Worker 执行，训练与推理互斥。
- 先使用 0.5B 模型、本地文件和单机 SQLite。未经本次任务要求，不引入更大模型、Kubernetes、多 GPU、量化或新的基础设施。
- 不为了前端展示伪造任务状态、进度、Loss 或训练产物。mock 必须标为 mock，并与真实 API 调用区分。

## M2 实施约束

- 沿用 `TrainRequest → train(request, on_progress) → TrainResult`；Schema 保持 CPU 可导入，Trainer 不依赖后端 Settings、HTTP、Celery 或 SQL。训练库在执行入口加载，不因实现 Trainer 破坏 CPU API。
- 模型和 tokenizer 固定相同可追溯 revision，使用模型 chat template；数据转换检查助手回答监督、padding 与截断后的有效目标。上传格式校验继续复用现有扫描器。
- M2-01 已定稿进度事件与指标格式，代码为 trainer/contracts.py，旧 trainer.train 导入位置保留；Pydantic 使用关键字构造，新增必填字段按契约迁移。公开 TrainingConfig 未改，max_steps/precision/local_files_only 属于内部 RuntimeOptions。
- step 表示优化器更新步数，kind 区分 train/eval，时间归一 UTC。Trainer 通过 MetricWriter 唯一写入并 flush metrics.jsonl，再回调同源事件；M3 Worker 消费事件并更新数据库，不能重复写指标。加载阶段不伪造 Loss。
- 内部路径类型只验证布局，不验证文件、符号链接或授权；后续执行层负责真实路径、受控根目录与哈希校验。模型/tokenizer 固定同一 40 位 revision，缓存目录是实际 Hub 缓存目录。
- M2-02 缓存入口为 scripts/prepare_model.py；prepare 显式联网，check 必须使用完整 revision 且不在线回退。trainer.model_cache.resolve_model_paths 按 CLI/环境/.env/默认解析根目录；TrainRequest.cache_dir 是 HF_HUB_CACHE（默认 HF_HOME/hub），不能直接传 HF_HOME。后续从 verify_model_cache 返回的已校验 snapshot_dir 加载，保持 local_files_only=true，不仅凭快照目录存在判断完整。
- M2-03 入口为 trainer.preprocessing 与 scripts/check_training_data.py。真实 Qwen 模板没有 generation 标记，使用完整序列字符偏移确定回答标签，不修改模板、不盲用 assistant_only_loss。只监督有效回答内容和模板 EOS；右截断后无回答内容即失败，不允许仅 EOS 充数。padding 填 -100 且保留原标签，M2-04 不手动 shift labels、不用默认 LM collator 覆盖标签。
- 数据准备复用 DatasetScanner；可选清单由 trainer.dataset_manifest 核对实际 train/validation 与 provenance/问答族/审核状态，不读取 test 正文。无清单为 unknown，草稿保留 draft_unreviewed；一致性检查不能替代人工审核或语义防泄漏。诊断默认不输出正文，--show-sample 必须显式指定。
- 训练 Schema/样例从类型经 scripts/export_training_contract.py 生成，--check 检查漂移；docs/examples/training 中数值均为格式占位，不是训练证据。结构合法的 manifest 也不能代替真实产物和 GPU 验证。
- 每次运行独立目录，保存 Adapter、tokenizer、参数和版本化清单，校验成功后才返回结果；失败保留诊断、不留下有效成功标记。训练后必须结束进程，再在新进程重载验收。
- M2 工程闭环允许使用显式标记的格式草稿；正式效果实验必须使用人工审核数据，冻结题不参与调参。不要求输出必须改变或效果必须提升，不把阶段计划写成实际结果。
- 默认 B 主改 trainer/train.py、数据转换和重载入口，A 主改内部契约、缓存工具和产物校验辅助模块；共享配置/类型先核对再修改，避免同时编辑同一入口。M2 不安排前端业务改动，用户调整分工时以本次要求为准。

## M3 规划与协作边界

- 本阶段规划不是已实现 API。M3-01 先交付共享 Schema/样例、task_protocols 和迁移清单；M3-03 注册路由后再从真实 app.openapi() 导出，不能把设计草案写成运行时能力。
- A 主改 SQL 仓储/状态/迁移/任务 HTTP/Publisher/离线对账；B 主改 Worker 执行/进程实例锁和 frontend。B 按 TaskRepository Protocol 用替身独立检查，不写 SQL、不复制 Trainer；A 不为了联调改 B 页面。共享 config/类型/入口文档由 A 汇总，双方各写独立任务日志。
- 派发明确未发送与确认未知要区分；未知时保留可查询的原 task_id，不覆盖 RUNNING/终态、不自动重投。POST 去重键与消息重复领取是两层不同保护，设计见 tasks.md。
- 数据库状态为业务来源；用 claim_token 条件更新；Trainer 唯一写 metrics。M3 离线对账先停 API/Worker 并取得实例锁，不按无 Loss 超时判断正常训练失联。该策略是待实现设计，不是当前恢复能力。
- 两人使用不同 checkout/worktree 和临时 DB/队列，GPU 验收不重叠。共同主线预算约 20 人时，另 4 人时缓冲，按每人每周 6–8 小时安排约 1.25–2 周；保留必要共同确认和真实联调。

## 接口与数据边界

- 对外字段使用 snake_case，资源 ID 是服务端生成的 UUID，时间输出为 UTC/RFC 3339。
- 成功响应直接返回资源或分页对象，错误返回统一 ErrorResponse，保持真实 HTTP 状态码。
- 业务条件看稳定错误 code，message 用于展示，前端不能解析中文文案判断错误类型。
- 客户端不能提交服务器路径、用户归属、统计值或数据集哈希；不能把本机绝对路径写入响应。
- 数据集上传后不可变。文件存于 DATA_DIR/datasets/{dataset_id}/train.jsonl，数据库保存相对 DATA_DIR 的键；文件名不决定存储路径。
- 元数据入库与文件操作由 services 负责；api 负责 HTTP/序列化，models 负责类型；Trainer 不依赖 FastAPI/Celery/数据库。
- 不把数据、模型权重、数据库、日志、.env 或凭据提交到 Git。公开的格式样例、来源登记和冻结评测规范属于文档；正式语料与生成回答仍放被忽略的 data/。数据准备复用 `scripts/prepare_dataset.py`：按问答族划分、保留哈希与审核状态，冻结题/族不得用于训练或调参，不自动将 AI 草稿标为 reviewed。

## 合作与契约修改

- 成员 A 主负责后端/存储/调度，成员 B 当前主负责 frontend，之后负责训练；可按实际任务调整，不代表文件访问限制。交付任务时新增工作日志，写清接口影响、验证和待交接项。
- 修改共享字段、默认值、上限或错误语义时，在同一变更中更新 Schema、接口文档、OpenAPI 和样例，说明兼容性影响；常规实现不必反复请求确认。
- 标准查阅以本次用户要求为先；M1 字段与行为以 datasets.md 为准，类型约束以对应 Pydantic Schema 为准。两者冲突应在实现前修正，不能静默选择一份忽略另一份。
- 数据集 OpenAPI 由 `uv run --locked python scripts/export_dataset_contract.py` 从真实应用 `.openapi()` 导出，不手改生成文件；`--check` 检查漂移。导出文件使用 `/api/v1` server 与相对 paths，运行时 `/openapi.json` 使用完整 paths，操作与 Schema 必须一致。
- 新增不兼容字段/行为先更新契约版本并写明迁移方式；在已有已发布客户端依赖时，不兼容改动另开 API 主版本。
- 进入实施阶段以 OpenAPI 与真实后端响应一致作为验收条件，不能长期维护两套不同契约。
- 每个任务交付包含改动、验证、未完成项。验证聚焦行为、失败处理和接口一致性；文档或契约任务不要求执行完整 GPU 训练。
- 默认保留他人的未提交改动，不擅自覆盖；提交仅包含当前任务相关文件。分支/PR 按团队实际工作方式使用，Git 同步沿用用户授权范围。
- 每次开发开始前、每个独立部分开发完成后，以及最终提交/推送前，都执行 `git fetch origin` 并比较本地与远端，阅读队友新增提交和工作日志。落后时优先在干净工作区 `merge --ff-only`；双方分叉时在保存本次任务提交后正常 merge，逐项解决冲突并重跑受影响检查。不能覆盖队友改动、丢弃未提交文件、强推或改写共享历史。远端暂不可达时明确记录“尚未确认”，不能写成“没有新提交”。
