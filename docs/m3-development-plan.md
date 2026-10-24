# M3 异步任务开发计划

版本：规划 1.0；日期：2026-10-24。状态：需求、分工和接口设计已整理，M3-01 至 M3-07 均未开始实现。本文不是已实现能力清单，也不表示队友已复核；开始编码时按 M3-01 将设计落实为共享类型和检查。

成员 A 指当前侧/你，主负责后端；成员 B 指队友，已有前端交付。本阶段按“先交付一个共同接口提交，再各自实现、最后一起验收”组织。快速接续见 [分工交接](m3-handoff.md)，对外字段草案见 [任务 API](api/tasks.md)。

## 一、目标与已有基础

M3 将已经通过本地验收的 Trainer 接入服务：浏览器配置 → API 持久化 → Redis/Celery → 单 GPU Worker → 原 Trainer → 产物审计 → 数据库终态 → 页面查询。

验收包含：提交请求不等待模型加载；两个真实任务串行；重复投递不重复训练；派发异常、训练失败及进程退出后的遗留状态可追踪。CPU API 不加载训练库，不在请求中训练。

| 实际基础 | 对 M3 的影响 |
| --- | --- |
| M1 数据 API、不可变存储、共享扫描器已完成 | 用已有 dataset_id 和服务端相对存储键，保持数据契约 |
| M2-01～06 工程闭环完成，174 项 CPU 检查为历史验收基线 | 复用 TrainRequest、train、TrainingProgress 和 verify_training_artifacts，不复制训练/指标逻辑 |
| TrainingTask 表只有 M0 占位字段 | 缺 revision/数据快照/领取归属/稳定错误码/请求去重等，需显式迁移，不能假定表为空 |
| TaskCreate 只定义输入，未注册任务路由 | 可以在发布路由前完善响应和请求去重约定；不能称任务 API 已存在 |
| worker.train 仍抛 NotImplementedError，Worker 仅配置/ping 可用 | 必须实现真实领取和执行，Celery ping 不能作为本阶段完成证据 |
| Vue 已有 TrainingPanel/TasksPanel、配置校验、轮询壳 | 主要做字段收敛、错误处理及真实联调，保留组件和视觉设计 |
| 当前任务筛选只筛当前页，指标以 step 合并 | M3 改为服务端状态筛选；M4 再改指标游标，不能沿用 step 合并 train/eval |

本阶段不实现 Loss/日志 HTTP、下载、在线推理、取消/恢复训练、自动重训、对象存储、混合部署、多 GPU 或 Kubernetes。模型仍为同一固定 revision 的 0.5B；正式语料审核和效果评测继续独立推进。

## 二、分工与可以并行的条件

不建议 A 做全部后端和 Worker、B 只等 API 改页面。这样调度工作会集中到 A，也没有充分使用 B 已了解的训练链路。本阶段把 Worker 执行层交给 B，数据库与状态更新全部由 A 提供的仓储接口负责。

共同起点 M3-01 只做小范围接口提交：公共 Task Schema、CPU 内部 DTO/Protocol、样例和错误语义。A 主笔，B 当场核对消费方式，建议共同讨论 30–45 分钟；这些时间计入任务工时。它是依赖，不能声称完全没有等待。

M3-01 完成前，B 可以按本文和 API 草案整理前端测试/独立 mock；不先猜字段写 Worker 数据库逻辑。M3-01 合入后：

| 人员 | 独立实现主线 | 不需要等另一人的部分 | 合并前交付 |
| --- | --- | --- | --- |
| A：你 | ORM/迁移、SQL 仓储、提交/查询/派发、离线对账 | 仓储并发检查用临时 SQLite；HTTP 用注入的 Publisher，无需真实 GPU Worker | 数据库迁移与状态行为检查、真实运行时 OpenAPI、任务 HTTP 检查 |
| B：队友 | Worker 编排/领取/Trainer 适配、单实例保护，再接前端 | Worker 用内存仓储和明确训练替身测试；前端用契约 fixture，不等待真实 HTTP | Worker 行为检查、前端测试/构建、自己的工作日志 |
| A+B | 接真实仓储/Publisher、Redis/GPU、浏览器和故障验收 | 这里确实需要两边完成，不能用 mock 取代 | 串行任务、重复投递、失败和浏览器证据 |

B 的 Worker 和前端是同一个人顺序完成的两项工作，不把它们算作两个人并行。A 也不同时开展多项主要任务。具体文件归属见第七节。

## 三、任务、依赖和工时

总基线 20 人时，A/B 各约 10 人时；另预留双方各 2 人时故障缓冲。按每人每周 6–8 小时，需要约 1.25–2 周，不能硬算成一周。原 W3（11/02–11/08）保留为八周排期基线；目前已提前完成 M2，可提前实施 M3，但不改变总截止目标。

| 编号 | 主负责 | 依赖 | 交付与主要文件 | 人时 | 状态 |
| --- | --- | --- | --- | --- | --- |
| M3-01 共用契约 | A+B，各 1 | 阅读本计划 | Task Schema、task_protocols、生成样例/契约检查；API 字段/迁移清单确认 | 2 | 待办 |
| M3-02 存储与状态 | A | 01 | entities、task_repository、task_migration/migrate_tasks；CAS、所有权、唯一请求键 | 3 | 待办 |
| M3-03 API 与派发 | A | 01/02 | api/tasks、services/tasks、task_dispatch、运行时 OpenAPI 导出与 HTTP 检查 | 2.5 | 待办 |
| M3-04 Worker 适配 | B | 01；真实仓储接入等 02 | worker/execution、tasks、单实例锁、Trainer/路径/产物适配及替身检查 | 4 | 待办 |
| M3-05 前端接通 | B | 01；真实联调等 03 | 现有 TrainingPanel/TasksPanel/workspace/api.js 的局部修改与前端检查 | 3 | 待办 |
| M3-06 离线对账 | A | 02；真实进程失败证据等 04 | reconcile_tasks 只读检查/显式应用、终态修复与隔离检查 | 1.5 | 待办 |
| M3-07 共同验收 | A+B，各 2 | 02～06 | 真实 Redis/两任务串行/失败/重复消息/浏览器；项目状态与日志归档 | 4 | 待办 |

可并行主线为 A：02 → 03 → 06；B：04 → 05。03 不依赖 04，04 不依赖 SQL 实现，05 的 fixture 测试不依赖 03。07 才汇合真实能力。若迁移/异常排查超时，先使用缓冲，不削掉正确状态、去重或真实联调来追赶表格。

## 四、共同边界：M3-01 必须落地什么

### 4.1 公共 HTTP

按 [任务 API 草案](api/tasks.md) 形成 TaskCreate、TaskSummary、TaskDetail、TaskPage 和提交错误类型；保留现有 TrainingConfig。客户端不提交 revision、路径、RuntimeOptions、状态或归属，服务端生成 UUID 并保存固定 revision/配置/数据统计快照。

样例从共享类型生成，明确为 fixture。M3-01 可生成 JSON Schema/样例，不把未注册的接口伪装成运行时 OpenAPI；M3-03 注册路由后，从真实 app.openapi() 导出任务接口。共享 ErrorCode 如有扩展，同时重导出受影响的数据集契约，不能手改生成文件。

### 4.2 Worker 与 SQL 的内部接口

新增 backend/app/core/task_protocols.py，A 在 01 主改、B 复核；只放 CPU 可导入的 DTO/Protocol，不放 SQL、Celery、Settings 或 GPU 执行代码。以下是拟定签名，01 通过类型/行为检查固定，后续双方不得各自改一套：

```text
TaskRepository.claim(task_id, claim_token, worker_id) -> TaskExecutionSpec | None
TaskRepository.record_progress(task_id, claim_token, event: TrainingProgress) -> bool
TaskRepository.complete(task_id, claim_token, output_key, manifest_sha256, summary) -> bool
TaskRepository.fail(task_id, claim_token, failure: TrainingFailure) -> bool

Publisher.publish(task_id, celery_task_id) -> PublishOutcome
PublishOutcome = accepted | not_sent | unknown

execute_training(task_id, repository, settings, train_fn) -> execution outcome
```

TaskExecutionSpec 包含 task_id/dataset_id、原始数据相对键及 sha256/size_bytes/row_count、base_model/model_revision、完整 TrainingConfig/RuntimeOptions；不把 SQL Session/实体传给 Trainer。config 做深拷贝，claim_token 由 Worker 每次尝试生成并用于后续条件更新。TaskRepository 的 SQL 实现放 A 的 services/task_repository.py，B 提供同接口内存替身测试；生产装配在 B 的 worker/tasks.py，使用约定的 SqlTaskRepository(sessions) 工厂。

claim 以单个条件更新事务领取 PENDING/QUEUED；返回 None 表示已被领取/终态/不存在，Worker 直接跳过，不访问 GPU 或删除目录。数据库错误抛安全 TaskStoreError，不当成正常跳过。record_progress/complete/fail 仅允许 RUNNING 且 token 一致；更新 0 行表示失去归属，不能继续把状态改为完成。B 不写 SQL，A 不调用 GPU。

### 4.3 持久化与迁移

在现有任务字段上增加：model_revision、dataset_sha256/size_bytes/row_count 快照、runtime_options、claim_token/worker_id、error_code、请求去重键/规范请求哈希、manifest_sha256；output_path 继续保存相对 DATA_DIR 的 outputs/{task_id} 键。具体列空值/索引在 01 定稿，由 A 一次维护 ORM/迁移/检查。

新增 scripts/migrate_tasks.py --check/--apply：停止 API/Worker、SQLite backup、显式事务迁移、旧行核对。旧记录缺少可信 revision/数据快照时报告阻塞或要求显式映射，不擅自填 main、不删库。不用 create_all 变更既有表；启动检查阻止旧结构继续提供业务服务。新库正常创建当前表。

01 同时确认服务端固定 revision/精度的配置字段（默认沿用已验收的 40 位 revision、BF16、max_steps=null），由 A 维护 Settings/.env.example。HTTP 创建只读数据库数据集元数据，不校验大模型权重；Worker 才核验实际文件和缓存。跨机器不传本机绝对路径，缓存解析显式结合当前 Settings/既有模型路径工具。

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

先合入 01，小提交固定共享类型。A、B 分支同时从该提交出发；02/03/04/05/06 各自通过其独立测试即可发起合并，不必等两个巨大分支同时完工。B 的 Worker 依赖 Protocol 而非复制 SQL；A 的 Publisher 接口不从 B 尚未交付的业务 task 导入实现，发送可使用稳定任务名 worker.train。

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

建议分支 feature/m3-api-state 和 feature/m3-worker-ui。两人使用不同 checkout；若同一机器，使用独立 worktree、环境和临时 DB/Redis 队列，不能在同一工作目录靠切分支隔离编辑。只读基础缓存可共用，业务库与 GPU 验收环境由一人维护。

每项日志命名 YYYY-MM-DD-m3-XX-a/b.md，记录基线、主改文件、协议版本、已测/未测与下一位调用方式。开始/部分完成/提交推送前均 fetch 读新日志；分叉正常 merge，不强推，不覆盖别人的未提交工作。代码冲突少不代表语义正确：合并后仍重跑受影响的共享契约、状态和真实接入检查。

## 八、完成定义

- [ ] 01 共享类型/样例和文件边界落地，两边可各自编译/检查。
- [ ] 任务 API、SQLite 显式迁移、派发结果语义符合运行时 OpenAPI。
- [ ] Worker 只接任务 ID，原子领取、持有归属、单实例、复用 Trainer/审计。
- [ ] 两个真实任务串行完成，重复投递/不确定提交不会重复训练。
- [ ] 前端使用真实任务 API，状态/分页/错误正确，无虚构数据。
- [ ] 最低限度的离线对账有失败/恢复证据，无自动重训或覆盖。
- [ ] 本阶段日志、测试证据和共享文档同步，正式效果/后续阶段边界明确。

当前这些项全部属于计划，本次只交付规划文档，不运行或声称已实现 M3 服务。
