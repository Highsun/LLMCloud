# M3 任务共享契约 1.0.0

日期：2026-10-24。M3-01 已交付 CPU 类型、Protocol、生成样例与检查；成员 B 的消费者核对待完成。任务 SQL、迁移、HTTP、Publisher、Worker 执行与恢复仍属后续任务，当前没有任务路由。本文件是代码使用和迁移清单，执行分工见 [完整计划](../m3-development-plan.md)，HTTP 语义见 [任务 API](../api/tasks.md)。

## 导入与生成

| 内容 | 导入位置 |
| --- | --- |
| TaskCreate、TaskListQuery、TaskSubmissionHeaders、TaskSummary/Detail/Page、TaskSubmissionErrorResponse | backend.app.models.task_schemas |
| TaskStatus、TaskErrorCode、PublishOutcome、ExecutionOutcome、版本和上限 | backend.app.core.task_contract |
| TaskExecutionSpec、TaskRepository、Publisher、TaskStoreError、ExecutionSettings、TrainFunction、TaskExecutor | backend.app.core.task_protocols |

旧 backend.app.models.schemas.TaskCreate 和 entities.TaskStatus 导入保留；状态枚举移到 CPU 模块，SQL 枚举值/表结构没有变化。原 TaskCreate 尚未发布为 HTTP 接口，此次 dataset_id 从任意 UUID 收敛为项目使用的 UUIDv4；后续消费者须用真实上传返回的 ID。TrainingConfig 与 M2 契约不变。

共享类型模块不导入 FastAPI、Celery、SQLAlchemy、Settings 或训练包。字段类型/一致性验证不读取文件、校验哈希或执行授权；Protocol 本身也不自动执行 CAS。SQL 和 Worker 实现须完成执行检查。

```bash
uv run --locked python scripts/export_task_contract.py
uv run --locked python scripts/export_task_contract.py --check
```

生成 [tasks.schema.json](tasks.schema.json) 与 [测试样例](../examples/tasks/README.md)，明确 types_only/mock，无运行时 OpenAPI。不要手改生成文件。M3-03 注册路由后才从真实 app.openapi() 导出任务 OpenAPI；当前服务的能力探测继续判任务接口不可用。

## HTTP 类型与边界

- TaskCreate 只接 dataset_id、base_model、config；未知字段拒绝，默认模型和 LoRA 参数沿用现有值。
- TaskListQuery：page=1、page_size=20（上限 100）、可选五状态 status。ALL 不发送 status。Schema 接受查询字符串形式的整数；重复查询参数/头由 M3-03 的 HTTP 解析层额外拒绝，不能称类型已完成此检查。
- TaskSubmissionHeaders 是提取后的请求头 DTO，不是完整浏览器请求头集合。idempotency_key 可空，别名为 Idempotency-Key，非空必须 UUIDv4；HTTP 层须大小写无关地提取并检查重复头。
- TaskSummary 强制显式提供所有字段，未知总步数时 current_step=0、total_steps/progress=null；已知时 progress=current_step/total_steps。RUNNING 可进度 1.0，状态须等待产物审计及 DB 提交。FAILED 保留已发生步数。
- PENDING/QUEUED 无执行步数和开始/结束时间；RUNNING 有开始而无结束时间；终态有结束时间，COMPLETED 有完整步数/开始时间且无错误。FAILED 必须有 code/message。错误码与消息同时为空或同时非空。
- 时间输出 UTC/Z；有时区输入归一化输出，数据库的无时区 datetime 对象按 SQLite UTC 解释；外部无时区字符串、数字时间戳拒绝。按创建、开始、结束顺序核对。
- TaskDetail 额外包含完整 config；不接受 training_config 别名，不暴露路径、归属、claim_token 或 celery_task_id。TaskPage 对页数、数量上限、越界空页做一致性检查，SQL 实现仍须先筛选后分页。
- TaskSubmissionErrorResponse 仅用于已持久化任务的 DISPATCH_FAILED/DISPATCH_UNCERTAIN，继承统一错误核心，必填 error.task_id；其他错误仍使用原 ErrorResponse，不强加空 task_id。

任务 JSON 请求体上限固定为 MAX_TASK_BODY_BYTES=65,536（64 KiB），由 M3-03 实现运行时限制。新增 ApiErrorCode 为 TASK_NOT_FOUND、IDEMPOTENCY_CONFLICT、REQUEST_TOO_LARGE、DISPATCH_FAILED、DISPATCH_UNCERTAIN；共享枚举变化已通过脚本重导出数据集 OpenAPI。它是枚举扩展，M1 字段/错误行为和 1.0.0 契约不变，当前 M1 不因此新增这些错误行为。

## Worker 与仓储

TaskExecutionSpec 字段：contract_version、task_id、dataset_id、dataset_key、dataset_sha256、dataset_size_bytes、dataset_row_count、base_model、model_revision、config、runtime。均是可序列化快照，不包含 ORM、Session、绝对路径或服务器归属。

dataset_key 必须精确等于 datasets/{dataset_id}/train.jsonl，ID 为 UUIDv4、revision 为完整 40 位小写哈希、SHA-256 为 64 位小写摘要，大小/行数为严格正整数。config 在构造时重新验证并深拷贝（包括 target_modules），避免随仓储可变对象改变；嵌套 TrainingConfig 仍是现有可变类型，消费者不应修改领取快照。runtime 复用 RuntimeOptions，本阶段禁止 local_files_only=false。

Worker 根据当前主机 Settings.data_dir/log_dir 解析路径，并用既有模型路径工具取得实际 Hub cache；原始数据/符号链接/受控根/哈希/统计、缓存完整性由执行层核验。API 不读取大模型。M3 只接上传的 train 文件，不擅自增加 validation/test 或客户端路径字段。

| TaskRepository 方法 | 参数 / 返回 | 实现必须满足 |
| --- | --- | --- |
| get_status | task_id: UUID → TaskStatus 或 None | 新事务读取已提交状态；None 仅表示不存在，DB 错误抛 TaskStoreError |
| claim | task_id: UUID, claim_token: UUID, worker_id: str → TaskExecutionSpec 或 None | PENDING/QUEUED 原子领取为 RUNNING；None 表示不存在/已领取/终态，不能访问 GPU；领取失败也不能修改旧目录 |
| record_progress | task_id, claim_token, event: TrainingProgress → bool | 只更新 RUNNING 且 token 一致；train 的总步数固定且步数不倒退，eval 不推进；不写 metrics |
| complete | task_id, claim_token, output_key: str, manifest_sha256: Sha256, summary: TrainingSummary → bool | 审计后 CAS；output_key 精确为 outputs/{task_id}，保存哈希/摘要和终态时间 |
| fail | task_id, claim_token, failure: TrainingFailure → bool | CAS，保留已发生步数；failure.task_id 为空或匹配 task_id，code/message 采用安全诊断 |

所有协议方法同步调用；领取 token 和 celery_task_id 都由服务端生成 UUIDv4，worker_id 为非空、最长 255 字符的实例标识。后续 SQL 实现负责入口值验证和短事务。三个写入方法 False 表示当前非 RUNNING、归属不符或资源不存在；对于仍持有归属的 eval/重复进度，忽略步数更新但返回 True。非法参数、损坏存量数据或 DB 操作失败不能伪装成 False/None，统一安全 TaskStoreError，底层原因仅写服务诊断且不暴露响应。

get_status 是此次补全的接口：原规划要求完成提交确认丢失后重新读取实际终态，但原四个方法无法实现该读取。有效 TrainResult 已取得后，complete 异常不能继续 fail 覆盖或删除产物；先 get_status，已 COMPLETED 可保留完成，其余保留实际状态供离线对账，读取失败也不强行修改。实际生产装配工厂约定为 SqlTaskRepository(sessions)，由 A 在 M3-02 提供，B 在 worker/tasks.py 装配；本次没有该类的实现。

TaskErrorCode 直接组合 M2 FailureCode 与 DISPATCH_FAILED/DISPATCH_UNCERTAIN/WORKER_INTERRUPTED/TASK_ABANDONED；Trainer 失败直接保留 failure.code，不改 Trainer 枚举。离线恢复原因属于 A 的恢复逻辑，不通过伪造 TrainingFailure 传给 fail。

Publisher.publish(task_id: UUID, celery_task_id: UUID) → PublishOutcome：accepted / not_sent / unknown。消息只包含 task_id，Celery 消息 ID 使用 celery_task_id；单次、有界、无隐式重发。not_sent 与 unknown 的边界、状态 CAS 与 503 行为见 API/计划。枚举只固定结果，不代表已有真实 Publisher。

TaskExecutor 固定 execute_training(task_id, repository, settings, train_fn) 的调用形状；ExecutionSettings 是仅有 data_dir/log_dir 的结构化视图，不导入实际 Settings。TrainFunction 与原 train(request, on_progress=None) 兼容。ExecutionOutcome 为 completed、failed、skipped、ownership_lost、reconciliation_required，分别表示确认 DB 完成、确认失败、未领取跳过、写入 False 后失去归属、有效产物存在但完成状态无法确认。不能将后两者统一改为 FAILED。类型检查不代替 Worker 实现及故障验收。

## 服务端配置与请求去重

Settings 新增 default_model_revision（已验收的 7ae557604adf67be50417f59c2c2f167def9a775）、training_precision（bf16 默认，也允许 fp32）、training_max_steps（默认 None，显式内部冒烟可设正整数）。对应环境变量为 DEFAULT_MODEL_REVISION、TRAINING_PRECISION、TRAINING_MAX_STEPS，最后一项不用时不设置，不填空字符串。API 创建时保存配置快照，Worker 使用快照，不用执行时的新默认值覆盖。

构造 runtime：RuntimeOptions(precision=settings.training_precision, max_steps=settings.training_max_steps, local_files_only=True)。此配置已经可加载，但尚未被任务服务消费，任务创建由 M3-03 实施。

M3-02/03 的请求哈希输入固定为 TaskCreate 补默认后的 model_dump(mode="json")：只包含 dataset_id、base_model、完整 config；JSON 使用 sort_keys=True、ensure_ascii=False、separators=(",", ":")、allow_nan=False，UTF-8 后 SHA-256。UUID 用规范字符串，target_modules 保持请求顺序，不推断语义等价。revision/runtime 不加入请求哈希，同键重放必须读取旧快照。此处是实现要求，01 不提前实现唯一索引/去重业务。

## M3-02 显式迁移清单（未实施）

本次只迁出 TaskStatus 定义，未增加 ORM 列、未执行任何任务表迁移，也未新增迁移命令。下面固定后续列名、空值与索引，不可用 create_all 或删库替代。

| 新列 / 类型 | 空值 / 约束 | 可信来源 |
| --- | --- | --- |
| model_revision / String(40) | 非空，完整 revision | 创建时 Settings 快照；旧行须显式映射 |
| dataset_key / Text | 非空，datasets/{dataset_id}/train.jsonl | 已登记的受控数据集键，并与 ID 核对 |
| dataset_sha256 / String(64) | 非空，完整 SHA-256 | 数据集元数据快照 |
| dataset_size_bytes / Integer | 非空，>0 | 数据集元数据快照 |
| dataset_row_count / Integer | 非空，>0 | 数据集元数据快照 |
| runtime_options / JSON | 非空，RuntimeOptions，离线加载 | 创建时服务端配置；旧行须可信映射 |
| claim_token / String(36) | 可空，UUIDv4 | 领取时生成，和 worker_id 同时为空或同时非空 |
| worker_id / String(255) | 可空，非空值长度 1–255 | 领取实例标识；终态保留领取信息 |
| error_code / String(64) | 可空，TaskErrorCode | 业务失败/暂态诊断；有 code 时必须有安全 message |
| idempotency_key / String(36) | 可空，UUIDv4，唯一索引 | 可选请求头；无键请求允许多行 NULL |
| request_sha256 / String(64) | 与 idempotency_key 同空/同非空 | 上述规范请求哈希，不对其单独建唯一索引 |
| manifest_sha256 / String(64) | 可空，COMPLETED 非空 | 对已审计成功清单原始字节取摘要 |

既有 output_path 保持可空 Text，COMPLETED 必须为 outputs/{task_id}；celery_task_id 创建时生成，保留原列类型，值采用 UUIDv4。既有 status、progress/current_step/total_steps 和时间列保留；SQL 初始 total_steps=0/progress=0 映射到响应 null/null，不能显示成已知总步数。已知真实步数禁止回退；终态错误和时间按上述 DTO 语义处理。新表保留 status/dataset_id 索引，并增加 (created_at,id) 及 (status,created_at,id) 索引支持默认排序/筛选；SQLite 约束与应用验证共同保证快照/去重一致性。

迁移前停 API/Worker，用 SQLite backup 备份；先 --check 报告表结构、旧行与阻塞，再显式 --apply。空旧表可重建复制结构；非空旧表逐行核对数据集键/摘要/统计和 revision/runtime 来源，缺少可信资料必须阻塞或要求显式映射，禁止填 main 或用当前默认值冒充旧执行记录。旧 COMPLETED 必须有可信成功产物和清单，否则阻塞；旧 RUNNING 缺领取信息不得凭空伪造活实例，需明确人工处置方案后再迁移。迁移用事务保留主外键与历史，不丢行；应用启动检查拒绝旧任务结构。数据集迁移仍是独立入口。

## 两人接续核对

A 侧代码和检查可独立交付，不能代表 B 已核对。B 请确认：实际导入位置、五个仓储方法、Spec/runtime 字段、完成确认丢失的读状态流程、提交去重/专用错误及所有 fixture。差异在共享小提交一次同步，不各自复制类型。核对后按 M3-04 做独立 Worker；真实 SQL 装配等 M3-02，完整前端接通等 M3-03，Redis/GPU/浏览器仍在 M3-07 共同验收。
