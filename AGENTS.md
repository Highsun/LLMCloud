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

执行 M3 前继续读 [完整计划](docs/m3-development-plan.md)、[任务 API](docs/api/tasks.md)、[共享契约](docs/contracts/tasks.md)、[Worker](docs/worker.md)、[对账](docs/task-reconciliation.md) 及 [M3-05 审查](docs/worklogs/2026-11-04-m3-05-a-review.md)。M3-01～06 已交付；07 的 A 真实 GPU 自动验收、B 异步证据/既有任务页面复查及 A 本机审查回归均通过，61d8703 已审查合入。双方从新上传到实际 GPU 完成的同步人工联调尚未执行，M3 保持待共同验收；M4-01 A 侧类型/样例已交付，B 核对待记录，02～07 待实施。

执行 M4 前读 [完整计划 1.1](docs/m4-development-plan.md)、[观测契约 1.0.0](docs/api/task-observability.md) 和 [M4-01 日志](docs/worklogs/2026-11-04-m4-01.md)。01 A 侧 CPU 类型/常量、内部完成 DTO/Protocol、生成样例/检查已交付，待 B 消费者核对；02～07 待实施。B 可先做 04a 图表，再按实际类型/fixture 核对和实现 04/05。当前没有指标/日志/下载路由或文件服务，不得把 Schema/样例当真实 OpenAPI 能力。M3 剩余同步人工流程可与 M4-07 同场分别记录。

## 当前事实与任务边界

- M0 环境和骨架已完成。健康检查、模型目录与 Celery ping 已实现。
- M1-01 交付接口约定、Pydantic Schema、离线 OpenAPI 设计稿和样例。
- M1-02 已完成共享 JSONL 扫描器、数据集创建/查询服务、失败清理/只读审计、新字段及 SQLite 显式迁移；详见 [工作日志](docs/worklogs/2026-10-21-m1-02.md)。
- M1-03 已完成数据集上传/列表/详情 HTTP 路由、multipart/请求体限制、request_id、统一错误与运行时 OpenAPI；详见 [工作日志](docs/worklogs/2026-10-21-m1-03.md)。M1-04 已在成员 B 页面基础上完成数据集浏览器功能验收及局部修复，见 [接续日志](docs/worklogs/2026-10-22-m1-04-integration.md)。M1-05 故障验收/CPU CI 已完成且 GitHub 首次运行成功，见 [日志](docs/worklogs/2026-10-22-m1-05.md)。M1-06 来源说明、可复现划分工具和 12 道冻结题已交付，见 [数据说明](docs/data/README.md)。M1 计划范围已验收，可进入 M2；正式语料仍需人工编写/审核。
- `trainer.dataset.iter_records` 与上传服务共用 DatasetScanner/InstructionRecord，不能另写一套宽松的文件校验。
- 新库启动直接创建新表，旧库先运行 `scripts/migrate_datasets.py --check`，确认报告后显式 `--apply`；禁止用 create_all 或删库替代迁移。
- `trainer.train` 已实现单 GPU 真实 LoRA 与 CLI，`worker.train` 已在 M3-04 接入领取/校验/原 Trainer/审计/状态更新，真实 GPU 任务链路已在 M3-07 A 自动验收通过，B 异步复核已通过，待同步人工联调。真实训练证据见 [M2-04 日志](docs/worklogs/2026-10-23-m2-04.md)，格式草稿不代表效果提升。
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

- M3-01 的共享类型/Protocol/样例与 B 消费者核对已完成；M3-02 SQL/迁移、M3-03 HTTP/Publisher、M3-04 Worker 均已实现。运行时 OpenAPI 用 scripts/export_task_openapi.py 从真实 app.openapi() 导出，类型/样例用 scripts/export_task_contract.py 检查漂移；CPU/HTTP/真实 Redis 缺缓存检查不能代替 GPU 验收。
- M3-02 的 SqlTaskRepository(sessions) 位于 services/task_repository.py，五个 Worker 方法不变；额外提供 create/get_detail/list 与 mark_queued/mark_dispatch_failed/mark_dispatch_uncertain。SQLite 写锁/条件更新/唯一索引保护状态和去重，complete 持久化 training_summary，不读产物文件。旧库先 scripts/migrate_tasks.py --check，再停 API/Worker 后显式 --apply；不补造旧 revision/归属，未知旧结构阻塞。本机空旧任务表已备份升级，231 项 CPU/HTTP 检查通过，真实 Worker/SQL 装配和 Redis 缺缓存 CPU 消费已验收；GPU 串行/恢复已在 M3-07 A 自动验收通过，B 异步复核已通过，待同步人工联调。
- TaskStatus 在 core/task_contract.py（entities 原导入保留），TaskCreate 在 models/task_schemas.py（schemas 原导入保留）。TaskRepository 固定 get_status/claim/record_progress/complete/fail 五个方法，新增只读 get_status 用于完成写入确认丢失时读真实状态。Spec 固定 dataset_key/sha256/size/rows 和 config/runtime 快照，不能传 SQL 对象；有效产物已存在但完成提交失败时不得继续 fail 覆盖，应读状态并留待对账。详见共享契约。
- M3-03 TaskService/CeleryPublisher 已接入：先提交 DB，再按 worker.train 发布 task_id；同键重放 200 不重发，新建确认接受 202。连接/发送/Redis 命令均禁用重试；TASK_PUBLISH_TIMEOUT_SECONDS 默认每操作 1 秒。not_sent 与 unknown 分开，已持久化的派发 503 必须保留 error.task_id/Location，不覆盖 RUNNING/终态。POST 64 KiB、重复 JSON/查询/头、统一错误/CORS 已实现；真实 Redis 冒烟不启动 Worker/GPU。
- A 主改 SQL 仓储/状态/迁移/任务 HTTP/Publisher/离线对账；B 主改 Worker 执行/进程实例锁和 frontend。B 按 TaskRepository Protocol 用替身独立检查，不写 SQL、不复制 Trainer；A 不为了联调改 B 页面。共享 config/类型/入口文档由 A 汇总，双方各写独立任务日志。
- B 已交付完整 M3-05：服务端筛选/分页/请求竞争、冻结正文/Idempotency-Key、error.task_id 查询、sessionStorage 刷新恢复、正式 config/null 进度和终态轮询。5ec660f 已经 A 本机回归合入；05 历史浏览器测试使用实际 HTTP/SQL 和明确的 Publisher/执行事件替身。07 A 已另行通过实际 Redis/Worker/GPU/生产浏览器验收，B 异步复核已通过，待同步人工联调。
- 派发明确未发送与确认未知要区分；未知时保留可查询的原 task_id，不覆盖 RUNNING/终态、不自动重投。POST 去重键与消息重复领取是两层不同保护，设计见 tasks.md。
- 数据库状态为业务来源；用 claim_token 条件更新；Trainer 唯一写 metrics。M3-06 已交付 scripts/reconcile_tasks.py：默认只读 --check；--apply 必须 --services-stopped 且取得实例锁。核对成功产物/固定快照后恢复 RUNNING 为 COMPLETED，否则 WORKER_INTERRUPTED；等待任务 TASK_ABANDONED，终态不动，不重投、不改文件。短事务重读全行指纹和 token，未知提交不继续 fail。真实 Worker 锁互斥/停止释放已验收，GPU 中断/成功产物遗留恢复已在 M3-07 A 实测通过，B 异步复核已通过，待同步人工联调。
- M3-06 的公共锁原语为 core/worker_lock.WorkerInstanceLock(log_dir)，固定 LOG_DIR/worker.lock，禁止删除/替换锁文件。B 的 worker/instance_lock.py 和启动/worker_init 生命周期必须复用同一原语/handle，不能另建一把锁；M3-04 已接入标准及直接 Celery 入口。本机实际生产 Worker 与对账 CLI 互斥已验证；25 项独立检查、328 项总回归与 CPU 消费是历史基线；M3-07 A 已另行通过真实 GPU 退出/对账验收，不能混淆两类证据。
- 两人使用不同 checkout/worktree 和临时 DB/队列，GPU 验收不重叠。共同主线预算约 20 人时，另 4 人时缓冲，按每人每周 6–8 小时安排约 1.25–2 周；保留必要共同确认和真实联调。

## 接口与数据边界

### M4 实施时延续的约束

- 分工及验收以 [M4 计划](docs/m4-development-plan.md) 为准：A 主改 CPU 类型/只读仓储投影/文件服务/HTTP/共享文档，B 主改现有曲线、观测/下载控制器和前端测试；01 共同核对，06/07 需要实际配合。
- 指标使用 01 正式 MetricsQuery/MetricsPage/MetricRecord：source_id + 字节 cursor 增量读取、offset 标识完整行，同 step 的 train/eval 不覆盖，终态空页也合法。类型只校验局部结构，真正文件身份/行边界/扫描预算留给 02。HTTP 包装不修改 M2 TrainingProgress 或原 metrics.jsonl；Trainer 唯一写入，不新增重复数据库指标表。
- 日志使用 LogsQuery/LogsPage，安全字段常量在 core/observability_contract.py；投影/读取器尚未实现。failure 不透传自由文本 message，说明读取 TaskDetail；filtered_lines 按窗口内修改/丢弃的记录逐行计一次。只读任务有限尾部，不转发共享 Worker stdout、不获取 GPU 锁或加载训练库。新常量/类型/错误上限同笔更新正式文档及生成样例。
- 下载要求 SQL COMPLETED、固定快照/manifest 哈希与原共享 CPU 审计一致；临时 ZIP 位于独立 DATA_DIR/downloads，不污染原输出目录，只复制已审计文件。响应体/取消清理和实际复制哈希必须验证。
- B 替换现有 after_step/Map(step) 逻辑；终态还需补齐指标尾页和最终日志。下载先捕获任务 ID，blob 读取期间保持 timeout/abort 有效，任务切换不得污染新任务或文件名。
- 01 类型生成用 scripts/export_observability_contract.py --check，所有示例均标为 mock；Schema types_only/HTTP not_asserted 不代替运行时能力探测。ApiErrorCode 新增八个观测/下载 code，已有代码及原任务/训练契约不变，相关原 Schema 已重导出。CompletedArtifactRepository 为额外只读 Protocol，SQL 方法待 03，不改 Worker 五方法。02/03 实施后扩展真实任务 OpenAPI，并更新 01 阶段“无 M4 路由”的保护测试预期。工程草稿/受控测试不代表质量提升或 GPU 验收。

### 共同接口规则

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

M3-07 的 A 自动验收和 B 独立异步证据/既有页面复核均已通过，61d8703 已经 A 本机 7 项复核器、56 项前端、29 项浏览器及 9 个真实快照任务检查后合入，四份原成功产物独立 CPU 审计也通过。依据：[B 日志](docs/worklogs/2026-11-04-m3-07-b.md)、[A 审查](docs/worklogs/2026-11-04-m3-07-a-review.md)。下一步补原计划的双方同步人工“新上传→实际 GPU 完成”操作；没有此项记录前不将 M3 全阶段标为完成。M4 可先规划，仍未实现 Loss/日志/下载及在线推理。

2026-11-04 用户明确授权将 data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip 及同名 .zip.sha256 纳入 Git，作为当前数据/产物忽略规则的两个固定特例；其余原目录、解压内容、数据/权重/数据库/日志继续保持忽略。B 同步 main 后按 [交接说明](docs/m3-acceptance.md#跨机器证据交接) 校验、解压并复核；本次决定见 [Git 交付日志](docs/worklogs/2026-11-04-m3-07-evidence-git.md)。原 report.browser_url 是已停止的历史地址；拉取证据、既有页面复查不等于重跑 GPU 或完成双方人工联调，B 已交独立复核日志，后续同步人工操作另记结果。
