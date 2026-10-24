# M3 异步任务开发计划

版本：执行计划 1.2；日期：2026-10-24。状态：M3-01 的 A 侧代码/Schema/样例/检查与迁移清单已交付，待 B 核对消费者接口；M3-02～07 尚未实现。共享契约见 [任务契约 1.0.0](contracts/tasks.md)，不把类型交付写成任务 HTTP/Worker 已实现，也不冒充双方已核对。

成员 A 指当前侧/你，主负责后端；成员 B 指队友，已有前端交付。本文已合并原交接文档的任务入口与交接要求，作为 M3 分工、依赖、验收和交接的完整执行依据。对外字段与待实施 HTTP 行为见 [任务 API](api/tasks.md)。

立即接续：B 可先完成 M3-05 的“列表筛选、分页与请求竞争处理”小交付，并核对 01 已交付的实际类型/Protocol/样例。双方核对同步契约后，A 依次做 02 → 03 → 06，B 做 04 → 补齐 05；最后共同做 07。B 的首个小交付不依赖真实后端，但不代表整个 M3-05 已完成。可直接分配的工作说明见第三节。

## 一、目标与已有基础

M3 将已经通过本地验收的 Trainer 接入服务：浏览器配置 → API 持久化 → Redis/Celery → 单 GPU Worker → 原 Trainer → 产物审计 → 数据库终态 → 页面查询。

验收包含：提交请求不等待模型加载；两个真实任务串行；重复投递不重复训练；派发异常、训练失败及进程退出后的遗留状态可追踪。CPU API 不加载训练库，不在请求中训练。

| 实际基础 | 对 M3 的影响 |
| --- | --- |
| M1 数据 API、不可变存储、共享扫描器已完成 | 用已有 dataset_id 和服务端相对存储键，保持数据契约 |
| M2-01～06 工程闭环完成，174 项 CPU 检查为历史验收基线 | 复用 TrainRequest、train、TrainingProgress 和 verify_training_artifacts，不复制训练/指标逻辑 |
| TrainingTask 表只有 M0 占位字段 | 缺 revision/数据快照/领取归属/稳定错误码/请求去重等，需显式迁移，不能假定表为空 |
| M3-01 输入/响应/错误/Protocol/生成样例已交付，未注册任务路由 | 消费者核对实际类型，不另造字段；不能称任务 API 已存在 |
| worker.train 仍抛 NotImplementedError，Worker 仅配置/ping 可用 | 必须实现真实领取和执行，Celery ping 不能作为本阶段完成证据 |
| Vue 已有 TrainingPanel/TasksPanel、配置校验、轮询壳 | 主要做字段收敛、错误处理及真实联调，保留组件和视觉设计 |
| 当前任务筛选只筛当前页，指标以 step 合并 | M3 改为服务端状态筛选；M4 再改指标游标，不能沿用 step 合并 train/eval |

本阶段不实现 Loss/日志 HTTP、下载、在线推理、取消/恢复训练、自动重训、对象存储、混合部署、多 GPU 或 Kubernetes。模型仍为同一固定 revision 的 0.5B；正式语料审核和效果评测继续独立推进。

## 二、分工与可以并行的条件

本阶段把 Worker 执行层交给 B，数据库与状态更新全部由 A 提供的仓储接口负责。B 已交付前端；M2 实际交付见历史日志，不能假定 B 已参与或熟悉当前 Trainer。B 开始 04 时先阅读训练契约、入口与产物文档，复用已有训练链路。

共同起点 M3-01 只做小范围接口提交：公共 Task Schema、CPU 内部 DTO/Protocol、样例和错误语义。A 主笔，B 当场核对消费方式，建议共同讨论 30–45 分钟；这些时间计入任务工时。它是依赖，不能声称完全没有等待。

M3-01 完成前，B 按第三节先做列表小交付，使用 API 草案约定的查询参数和测试替身；不先猜 Worker 类型或写数据库逻辑。该交付不增加 API 字段，若 01 核对发现差异，先同步契约再调整测试。M3-01 合入后：

| 人员 | 独立实现主线 | 不需要等另一人的部分 | 合并前交付 |
| --- | --- | --- | --- |
| A：你 | ORM/迁移、SQL 仓储、提交/查询/派发、离线对账 | 仓储并发检查用临时 SQLite；HTTP 用注入的 Publisher，无需真实 GPU Worker | 数据库迁移与状态行为检查、真实运行时 OpenAPI、任务 HTTP 检查 |
| B：队友 | 先交付列表基础功能；01 后做 Worker 编排/领取/Trainer 适配、单实例保护，最后补齐前端 | 列表基础功能用隔离测试替身；01 后 Worker 用内存仓储与训练替身、前端用生成的契约 fixture，不等待 SQL/HTTP 完整实现 | 分批提交列表、Worker、完整前端；各自测试/构建和工作日志 |
| A+B | 接真实仓储/Publisher、Redis/GPU、浏览器和故障验收 | 这里确实需要两边完成，不能用 mock 取代 | 串行任务、重复投递、失败和浏览器证据 |

B 的列表小交付、Worker 和前端收尾由同一个人顺序完成，不计成额外人力。M3-01 核对是双方预留的短时合作，不要求 B 在同一工作时段同时实现 Worker 和前端。A 也不同时开展多项主要任务。具体文件归属见第七节。

## 三、任务、依赖和工时

总基线 20 人时，A/B 各约 10 人时；另预留双方各 2 人时故障缓冲。按每人每周 6–8 小时，需要约 1.25–2 周，不能硬算成一周。原 W3（11/02–11/08）保留为八周排期基线；目前已提前完成 M2，可提前实施 M3，但不改变总截止目标。

| 编号 | 主负责 | 依赖 | 交付与主要文件 | 人时 | 状态 |
| --- | --- | --- | --- | --- | --- |
| M3-01 共用契约 | A+B，各 1 | 阅读本计划 | Task Schema、task_protocols、生成样例/契约检查；API 字段/迁移清单确认 | 2 | 待验收：A 侧已交付，B 核对待完成 |
| M3-02 存储与状态 | A | 01 | entities、task_repository、task_migration/migrate_tasks；CAS、所有权、唯一请求键 | 3 | 待办 |
| M3-03 API 与派发 | A | 01/02 | api/tasks、services/tasks、task_dispatch、运行时 OpenAPI 导出与 HTTP 检查 | 2.5 | 待办 |
| M3-04 Worker 适配 | B | 01；真实仓储接入等 02 | worker/execution、tasks、单实例锁、Trainer/路径/产物适配及替身检查 | 4 | 待办 |
| M3-05 前端接通 | B | 列表基础可先做；完整契约等 01，真实联调等 03 | 先做 TasksPanel/workspace 列表，再补 TrainingPanel/api.js 提交/详情接通 | 3 | 待办 |
| M3-06 离线对账 | A | 02；真实进程失败证据等 04 | reconcile_tasks 只读检查/显式应用、终态修复与隔离检查 | 1.5 | 待办 |
| M3-07 共同验收 | A+B，各 2 | 02～06 | 真实 Redis/两任务串行/失败/重复消息/浏览器；项目状态与日志归档 | 4 | 待办 |

实际启动顺序：A 做 01，同时 B 做 05 的列表基础；01 合入后，A：02 → 03 → 06，B：04 → 05 剩余部分。03 不依赖 04，04 的替身测试不依赖 SQL 实现，05 的 fixture 测试不依赖 03。真实仓储装配要等 02/04，真实页面接通要等 03，07 汇合全部能力。若迁移/异常排查超时，先使用缓冲，不削掉正确状态、去重或真实联调来追赶表格。

### 3.1 现在分配给 A：M3-01 共用契约

- 阅读本文、API 草案、现有 TaskCreate/TrainingTask、Trainer 契约与新增工作日志。
- 主改 CPU Task Schema、task_protocols、任务错误集合、生成 fixture/检查；列清 ORM 迁移和 Settings/.env.example 后续需求，字段细则见第四节。
- 请 B 用 Worker 消费者和前端消费者的角度核对：五个仓储方法（含 get_status）、执行快照、三种派发结果、分页/空进度、提交错误及去重语义是否足够。
- 交付一个小型共享提交，记录提交号、类型导入位置、生成命令、迁移清单和未实现项。B 同步该提交后才按实际类型编写 04。
- 验收：CPU 无训练依赖可导入；生成样例合法且可检查漂移；未知字段/非法状态等被类型拒绝；不注册空任务路由，不以文档或样例代替 01 代码完成。

### 3.2 现在分配给 B：M3-05 首个小交付

任务目标：把任务列表从“当前页本地筛选”改为“按服务端状态查询并分页”，处理快速切换和轮询造成的旧响应覆盖。先读 [AGENTS](../AGENTS.md)、本文、API 草案和最新工作日志。主要改 frontend/src/workspace.js、frontend/src/components/TasksPanel.vue 及对应 frontend/tests；保留现有视觉和数据集功能。

| 行为 | 本次交付的验收要求 |
| --- | --- |
| 状态筛选 | 包含 ALL 及 PENDING/QUEUED/RUNNING/COMPLETED/FAILED；ALL 不发送 status，其余发送同名查询参数；不能用当前页本地过滤冒充全量筛选 |
| 分页 | 默认 page_size=20；切换状态回第 1 页；翻页、刷新和每次轮询保留当前状态。例如 /tasks?status=RUNNING&page=1&page_size=20 |
| 加载与空结果 | 正确区分加载、空列表和错误；无结果时总页数为 0，分页按钮有效禁用，不展示假任务 |
| 请求竞争 | 新筛选/翻页不会被 taskLoading 直接丢弃；旧请求的成功、失败和 finally 均不能覆盖最新列表、错误或加载状态。可参考已有数据集请求序号/AbortController 实现 |
| 页面生命周期 | 切出任务页停止轮询，页面隐藏暂停；旧的轮询响应不能覆盖新的用户选择；保留现有详情和其他入口的能力探测 |
| 后端未就绪 | 网络替身与样例只用于隔离测试并明确标识；真实页面仍按运行时 OpenAPI 启用功能，API 报错不能回退假数据 |

测试至少覆盖查询参数、状态切换回首页、翻页/轮询保留筛选、空结果、错误、乱序成功/失败及旧 finally。运行 cd frontend 后 npm test 和 npm run build；测试应覆盖实际修改的请求逻辑，不能只测试另一份模拟实现。

本次不做 Worker、后端、Loss、日志、下载或推理，也不重构页面。先提交列表代码和 YYYY-MM-DD-m3-05-b-list.md 日志，写清已测/未测和待接真实 API；独立验收后可先合入，但 M3-05 仍为部分完成。M3-05 原约 3 人时可先按列表约 1.5、后续接通约 1.5 人时拆分；是估时，不增加一个任务预算，超出时更新剩余估算并使用缓冲。

### 3.3 契约合入后给 B：M3-04 Worker 适配

同步 01 提交，阅读 [训练契约](contracts/training.md)、[训练入口](training.md)、[数据处理](training-data.md)、[产物审计](training-artifacts.md)，再按 task_protocols 接入。主要文件为 worker/execution.py、tasks.py、instance_lock.py、celery_app.py、__main__.py、scripts/start_worker.sh 和 tests/test_worker_*。

先实现可注入 repository/settings/train_fn 的执行入口，再装配 Celery。用内存仓储和训练替身独立检查领取成功/重复跳过、路径与摘要核验、真实事件回调、产物核对、失败和失去归属；同时验证重复 Worker 实例被拒绝。细节以第四、五节为准。B 不写 SQL、不补表、不复制 Trainer、不重复写 metrics、不预建 Trainer 独占目录/日志。缺少共享类型/配置时提出具体字段需求，由 A 在共享提交中同步。

独立交付包含代码、CPU 行为测试、工作日志和真实装配说明；02 未完成时明确“真实 SQL 未验收”，不能阻碍独立实现，也不能将替身测试写成 Redis/GPU 通过。02/04 就绪后安排短时共同装配。

### 3.4 B 最后补齐 M3-05，再共同验收

按 01 的实际类型补齐 TrainingPanel、TasksPanel、workspace 和 api.js：POST 读取 TaskDetail.id，详情只用 config；发送/保留 Idempotency-Key，读取专用 error.task_id，不确定提交查询原任务而不盲目重发；正确显示 null 进度、真实步数、失败原因和终态轮询行为。保持 M1 上传语义，M4/M5 操作继续按能力探测禁用。

03 路由/真实 OpenAPI 可用后验证页面与真实响应一致；05 完成需要列表小交付、提交/详情接通、测试/构建以及真实 HTTP/浏览器证据，不能只凭截图或第一笔代码提交标完成。最终 07 仍需真实 Redis/Worker/GPU 联调，详见第六节。

### 3.5 工作时段与反馈约定

分配任务时双方约定一个具体截止日期和时间，写在该任务的沟通记录或工作日志中；本计划不代替尚未约定的个人日程。B 首个实现时段只完成 3.2，A 同期只推进 01；之后按上述顺序领取任务。

开始时用三句话确认“本次做什么、不做什么、如何验收”。约定一次中途同步，给出分支/当前提交、已通过检查和阻塞；卡住约 30 分钟就反馈具体报错、已尝试步骤和所需接口。到约定时间即使未完成也提交可检查的进度及剩余项，不把失败测试或未联调写成通过。接收方按本次范围及时核对，新需求另记，不临时扩大验收范围。这些同步计入原工时，不新增审批环节。

## 四、共同边界：M3-01 交付内容

### 4.1 公共 HTTP

按 [任务 API 草案](api/tasks.md) 形成 TaskCreate、TaskSummary、TaskDetail、TaskPage 和提交错误类型；保留现有 TrainingConfig。客户端不提交 revision、路径、RuntimeOptions、状态或归属，服务端生成 UUID 并保存固定 revision/配置/数据统计快照。

样例已由 scripts/export_task_contract.py 从共享类型生成，明确为 fixture；--check 检查漂移。M3-01 只生成 JSON Schema/样例，不把未注册的接口伪装成运行时 OpenAPI；M3-03 注册路由后，从真实 app.openapi() 导出任务接口。共享 ErrorCode 已扩展并重导出数据集契约，不能手改生成文件。

### 4.2 Worker 与 SQL 的内部接口

已新增 backend/app/core/task_protocols.py，A 在 01 主改、B 待核对；只放 CPU 可导入的 DTO/Protocol，不放 SQL、Celery、Settings 或 GPU 执行代码。以下已落实为契约 1.0.0，完整参数类型、返回/失败含义见 [共享契约](contracts/tasks.md)，后续双方不得各自改一套：

```text
TaskRepository.get_status(task_id) -> TaskStatus | None
TaskRepository.claim(task_id, claim_token, worker_id) -> TaskExecutionSpec | None
TaskRepository.record_progress(task_id, claim_token, event: TrainingProgress) -> bool
TaskRepository.complete(task_id, claim_token, output_key, manifest_sha256, summary) -> bool
TaskRepository.fail(task_id, claim_token, failure: TrainingFailure) -> bool

Publisher.publish(task_id, celery_task_id) -> PublishOutcome
PublishOutcome = accepted | not_sent | unknown

execute_training(task_id, repository, settings, train_fn) -> execution outcome
```

TaskExecutionSpec 固定 contract_version、task_id/dataset_id、dataset_key/dataset_sha256/dataset_size_bytes/dataset_row_count、base_model/model_revision、config/runtime；不把 SQL Session/实体传给 Trainer。config 构造时重新验证并深拷贝，claim_token 由 Worker 每次尝试生成并用于后续条件更新。TaskRepository 的 SQL 实现放 A 的 services/task_repository.py，B 提供同接口内存替身测试；生产装配在 B 的 worker/tasks.py，使用约定的 SqlTaskRepository(sessions) 工厂。

get_status 用于完成写入确认丢失时读取真实已提交状态，不能凭异常将有效产物改为失败；读取异常抛 TaskStoreError。新增该只读方法是补全原故障设计所需，原四个写入/领取方法语义不变。ExecutionOutcome 同时区分 completed/failed/skipped/ownership_lost/reconciliation_required，不把失去归属和待对账统一当作失败。

claim 以单个条件更新事务领取 PENDING/QUEUED；返回 None 表示已被领取/终态/不存在，Worker 直接跳过，不访问 GPU 或删除目录。数据库错误抛安全 TaskStoreError，不当成正常跳过。record_progress/complete/fail 仅允许 RUNNING 且 token 一致；更新 0 行表示失去归属，不能继续把状态改为完成。B 不写 SQL，A 不调用 GPU。

### 4.3 持久化与迁移

M3-02 在现有任务字段上增加：model_revision、dataset_key/dataset_sha256/dataset_size_bytes/dataset_row_count 快照、runtime_options、claim_token/worker_id、error_code、idempotency_key/request_sha256、manifest_sha256；output_path 继续保存相对 DATA_DIR 的 outputs/{task_id} 键。具体列类型/空值/索引与旧行处置已在 [迁移清单](contracts/tasks.md) 固定，01 没有增加 ORM 列或执行迁移；02 由 A 一次维护 ORM/迁移/检查。

新增 scripts/migrate_tasks.py --check/--apply：停止 API/Worker、SQLite backup、显式事务迁移、旧行核对。旧记录缺少可信 revision/数据快照时报告阻塞或要求显式映射，不擅自填 main、不删库。不用 create_all 变更既有表；启动检查阻止旧结构继续提供业务服务。新库正常创建当前表。

01 已新增 Settings/.env.example 的 DEFAULT_MODEL_REVISION、TRAINING_PRECISION、可选 TRAINING_MAX_STEPS（默认已验收的 40 位 revision、BF16、max_steps=null）；尚无任务服务消费。HTTP 创建只读数据库数据集元数据，不校验大模型权重；Worker 才核验实际文件和缓存。跨机器不传本机绝对路径，缓存解析显式结合当前 Settings/既有模型路径工具。

## 五、状态、派发和故障原则

### 5.1 数据库是业务状态来源

| 更新方/条件 | 状态变化 | 约束 |
| --- | --- | --- |
| API 数据事务提交 | 新建 PENDING | 消息在事务提交后发送；短事务内不做网络/GPU 操作 |
| Publisher 明确接受且当前仍 PENDING | PENDING → QUEUED | 不能覆盖已 RUNNING/终态 |
| Worker 带 token 原子领取 | PENDING 或 QUEUED → RUNNING | 同一 task_id 只允许一个领取成功 |
| Trainer 返回且再次产物审计通过，归属仍一致 | RUNNING → COMPLETED | 保存输出相对键/清单哈希/结束时间；不能只看 Celery SUCCESS |
| 明确未派发、领取后数据/模型/训练/写入失败 | 条件更新为 FAILED | 安全 error_code/error_message，保留本次诊断和已发生进度 |

PENDING 可以被快 Worker 直接领取。QUEUED 表示已接受派发，不表示 FIFO 名次或 GPU 一定即刻可用。数据库事务失败时不能发送未提交的任务 ID。

Trainer 是 metrics.jsonl 唯一写入方，Worker 回调只更新数据库。仅用 train 事件更新 current_step/total_steps/progress，eval 同一步不重复推进。加载阶段 total_steps=null/progress=null；实际完成步数可以先到 100% 而状态仍 RUNNING，直到产物校验/事务完成。不要用定时器增长进度。

### 5.2 发送异常不能一律当作未执行

必须区分明确未发送和“可能已发出但确认丢失”。前者可将仍 PENDING 的任务标 FAILED；后者保留当前状态（可能已经 RUNNING），记录 DISPATCH_UNCERTAIN 并返回带 task_id 的 503，让用户查询同一个任务。不能把正在训练的行改成失败，也不能因此自动创建/发布第二项任务。

Publisher 在发送前的连接建立失败可归为 not_sent；进入发送阶段后的异常保守归 unknown，不能仅凭异常名字推断消息没到。accepted 只表示当前派发调用确认成功，不承诺 Redis 崩溃后的持久性。设置有界连接/读写超时，禁用提交路径的隐式发布重试；正常本机约 2 秒返回为目标，超时故障耗时另外记录。

POST 支持可选 Idempotency-Key（UUIDv4）；B 的真实表单每次明确的新提交生成一个键，超时/不确定结果保留它。相同键/相同规范请求返回原任务，不重新派发；相同键/不同请求 409。未提供键时每个 POST 都是新任务，不假装服务端能判断两个相同训练是否用户有意重复。唯一索引处理并发，而不是先查后插。

### 5.3 Worker 资源和执行

B 接入仍使用 solo、concurrency=1、prefetch_multiplier=1，只发 task_id，沿用早确认，不启用自动重训/晚确认来替代幂等。早确认不能保证 Worker 崩溃后自动恢复，必须由 06 处理遗留任务；此处不承诺 exactly-once。[Celery 任务说明](https://docs.celeryq.dev/en/stable/userguide/tasks.html)、[配置说明](https://docs.celeryq.dev/en/stable/userguide/configuration.html)。

Worker 启动前持有同主机/同 LOG_DIR 的非阻塞进程文件锁（独立 worker/instance_lock.py）；重复启动明确失败。标准启动与 Celery worker_init 钩子都接入，避免绕过脚本；Worker 全生命周期持锁，不用超时 Redis 锁冒充进程存活。solo/预取设置只约束一个 Worker 的行为，不自行证明没有第二实例。[预取说明](https://docs.celeryq.dev/en/stable/userguide/optimizing.html#prefetch-limits)。

同一物理 GPU 的实例必须共享锁位置，M3 演示期间不同时手工运行训练/重载 CLI；该锁不解决多机共享 GPU 或全部外部程序互斥。GPU 真实验收由 B 预约执行，A 同时可做 CPU/HTTP 检查。

B 从 claim 的 DTO 校验数据相对键与实际文件哈希/统计，复用已有路径解析、DatasetScanner 和 resolve_model_paths；构造原 TrainRequest，路径按当前主机解析。缺缓存只失败，不在请求或 Worker 中自动下载。Trainer 返回后 verify_training_artifacts 并比对 ID/revision/配置/数据摘要，再调用仓储 complete。若成功清单已写但 SQL 完成更新失败，不删成功产物、不假装 SQL 已完成，留给对账。

Worker 要区分“Trainer/产物失败”和“已取得有效 TrainResult 后 SQL 提交异常”：后者不能在统一 except 中继续覆盖为 FAILED，应记录任务 ID/安全诊断并保留当前 SQL 状态供对账；若只是完成提交的回复丢失，应读取并保留实际终态。API 同样返回重新读取的当前状态，不能把快 Worker 已写的 RUNNING 强制序列化成 QUEUED。

API/Worker 不预先创建 outputs/{task_id} 或 tasks/{task_id}.log；这两处由现有 Trainer 独占创建。领取/派发/前置校验诊断写服务/Worker 普通日志并带 task_id，不能为了写任务日志让 Trainer 遇到“文件已存在”。单实例验收还须用直接 Celery 入口启动第二进程，确认确实拒绝消费并非只记录一条锁错误。

### 5.4 最低限度恢复范围

M3-06 提供只读 reconcile_tasks --check 与显式 --apply，先停止 API/全部 Worker，并能取得实例锁再应用。只凭长时间无 Loss 不能判正常训练失联；不在 API 启动时按时间粗暴标 FAILED。

对账在短事务条件更新中处理：遗留 RUNNING 且完整产物与任务快照完全相符 → COMPLETED；否则结束为 FAILED/WORKER_INTERRUPTED，保留部分文件。遗留 PENDING/QUEUED 没有成功产物时标 FAILED/TASK_ABANDONED，不自动重投或覆盖旧目录。队列残留消息之后到达也只会跳过终态。检查报告和应用结果写日志，不能自动重训。在线 heartbeat/租约接管/outbox/自动补发留给后续扩展。

## 六、共同验收及合并顺序

01 用小提交固定共享类型。B 的 05 列表小交付可从当前基线先做并独立合入；01 合入后，双方同步包含该契约的主线，已有分支正常 merge，不要求丢弃列表工作或改写历史。02/03/04/05/06 各自通过其独立测试即可发起合并，不必等两个巨大分支同时完工。B 的 Worker 依赖 Protocol 而非复制 SQL；A 的 Publisher 接口不从 B 尚未交付的业务 task 导入实现，发送可使用稳定任务名 worker.train。

有意义的共同检查点必须保留：01 接口读通、04 与 02 的真实仓储装配、07 的真实链路。测试替身只能证明本模块，不能记录“GPU 串行验收通过”。

| 证据 | 通过条件 | 主要配合 |
| --- | --- | --- |
| 迁移/CPU | 新库/旧库/拒绝不可信旧记录，数据 API/174 基线不回退 | A，B 复核接口 |
| 并发/派发 | 两次领取只执行一次；发布确认晚到不覆盖 RUNNING；未知发送结果可追踪；同键不重派 | A+B，用受控故障注入 |
| 真实 Redis | 独立 API/真实 Worker，不用 eager 冒充队列 | B 运行，A 查 DB/API |
| 真实 GPU | 同时提交两项小数据训练，两项产物独立有效；开始/结束时间不重叠、任一时刻仅一项 RUNNING | A+B，各留时间戳/ID/清单证据 |
| 故障 | 缺缓存/非法数据/保存错误/Worker 退出均非成功；恢复不覆盖活任务或重复启动 | A+B，明确哪些是受控异常，非实测 OOM |
| 浏览器 | 真实上传数据→配置→提交→全量状态筛选/分页/详情→完成或错误；不确定提交查询原任务 | B 操作，A 配合服务 |
| 旧功能/产物 | Dataset API/前端回归、运行时 OpenAPI、Trainer CPU 导入、真实产物只读审计 | 双方按影响范围检查 |

M3 不要求每个服务任务自动执行文本生成。COMPLETED 表示训练保存及产物审计完成，下载时 M4 仍重新核验，M5 才提供在线生成；正式质量评测另行记录。原架构“可加载产物”不能被前端理解为每项任务都已经通过 M2-06 文本生成测试。

## 七、文件所有权与交接规则

| 文件范围 | 主改人 | 合作方式 |
| --- | --- | --- |
| core/task_protocols、models/task_schemas、共享错误类型、config/.env.example | A，01 共同确认 | 共享提交后稳定；B 提变更需求，A 同提交更新类型/文档/样例 |
| models/entities、task_repository、task_migration、api/tasks、services/tasks/task_dispatch、main.py | A | B 不在 Worker 内复制 SQL、补表或注册路由 |
| worker/tasks、execution、instance_lock、celery_app、__main__、start_worker | B | 只在已定配置字段内装配；缺字段交 A 修改，避免同文件编辑 |
| frontend/src、frontend/tests/e2e | B | 保留组件；A 不为联调方便另写一套任务页面 |
| scripts/migrate_tasks、reconcile_tasks、export_task_contract | A | 新脚本，不混入数据集迁移/训练 CLI |
| tests/test_task_* | A | 状态、SQL、迁移、HTTP/派发及契约 |
| tests/test_worker_*、前端测试 | B | 内存仓储/训练替身与真实接入差异明确 |
| README、AGENTS、project-memory/plan、架构/需求、日志索引 | A 汇总 | 两边各写独立日志，阶段合并时统一更新共享入口 |

建议 A 用 feature/m3-api-state；B 将首个列表小交付放 feature/m3-task-list，再用 feature/m3-worker 和 feature/m3-task-ui 分批交付。不同分支是提交边界，B 的实现仍顺序进行。两人使用不同 checkout；若同一机器，使用独立 worktree、环境和临时 DB/Redis 队列，不能在同一工作目录靠切分支隔离编辑。只读基础缓存可共用，业务库与 GPU 验收环境由一人维护。

每项日志命名 YYYY-MM-DD-m3-XX-a.md 或 YYYY-MM-DD-m3-XX-b.md；同任务分批可加 -list/-integration 等后缀。记录基线、主改文件、协议版本、已测/未测与下一位调用方式。开始/部分完成/提交推送前均 fetch 读新日志；分叉正常 merge，不强推，不覆盖别人的未提交工作。代码冲突少不代表语义正确：合并后仍重跑受影响的共享契约、状态和真实接入检查。

## 八、完成定义

- [ ] 01 共享类型/样例和文件边界落地，两边可各自编译/检查（A 侧已交付，B 核对待完成）。
- [ ] 任务 API、SQLite 显式迁移、派发结果语义符合运行时 OpenAPI。
- [ ] Worker 只接任务 ID，原子领取、持有归属、单实例、复用 Trainer/审计。
- [ ] 两个真实任务串行完成，重复投递/不确定提交不会重复训练。
- [ ] 前端使用真实任务 API，状态/分页/错误正确，无虚构数据。
- [ ] 最低限度的离线对账有失败/恢复证据，无自动重训或覆盖。
- [ ] 本阶段日志、测试证据和共享文档同步，正式效果/后续阶段边界明确。

当前只交付 01 的共享代码与检查，B 核对及后续业务均待完成；M3 服务验收项不能由类型/fixture 测试代替。
