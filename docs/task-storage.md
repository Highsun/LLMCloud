# M3-02 任务存储、状态与迁移

日期：2026-11-02，更新：2026-11-04。SQL 仓储/任务表/显式迁移、03 HTTP/Publisher、04 Worker 独立实现与 06 对账均已交付；本机 328 项回归和真实 Redis/生产 Worker 缺缓存 CPU 冒烟通过。GPU 串行/中断及成功产物恢复已在 [M3-07 A 真实运行](worklogs/2026-11-04-m3-07-a.md) 另行通过，B 异步复核已通过，待同步人工联调，不把 SQL/CPU 消费当成 GPU 证据。[共享契约](contracts/tasks.md) 的五个 Worker 方法保持不变。

## 使用仓储

```python
from backend.app.core.database import SessionLocal
from backend.app.services.task_repository import SqlTaskRepository

repository = SqlTaskRepository(SessionLocal)
```

每次操作使用独立 Session 和短事务，不保存 ORM 对象。SQLite 写事务在查询前 BEGIN IMMEDIATE，领取和归属写入另有 SQL 条件；读事务显式 BEGIN，使筛选计数与当前页读取一致。一个数据库同一时间一个写事务是 SQLite 的本机取舍，事务中不做联网、训练或文件审计。当前只验收 SQLite，不宣称 PostgreSQL 或多机协调已完成。

| 入口 | 行为 |
| --- | --- |
| create(request, model_revision=..., runtime=..., idempotency_key=None) | 查数据集元数据并保存不可变快照，生成业务 UUID 和独立 celery UUID；不读取数据文件/模型，不发消息 |
| 返回 TaskCreation | task 为 TaskDetail、created 表示首次创建、celery_task_id 为 UUID；重放返回原快照及同一消息 ID，不应再发布 |
| get_detail(task_id) / get_status(task_id) | 每次新事务读取；仅不存在返回 None，损坏记录/SQL 故障返回安全 TaskStoreError |
| list(TaskListQuery(...)) | 先 status 筛选，再 created_at DESC/id DESC 分页；返回 TaskPage，隐藏内部路径、归属、配置摘要和消息 ID |
| mark_queued(task_id) | 仅 PENDING → QUEUED，清除派发未知诊断；快 Worker 已领取时返回 False，不覆盖 RUNNING/终态 |
| mark_dispatch_failed(task_id) | 仅仍 PENDING 时记 FAILED/DISPATCH_FAILED，保留可查询记录 |
| mark_dispatch_uncertain(task_id) | 仅 PENDING/QUEUED 记录未知说明，不改状态，不覆盖 RUNNING/终态 |
| claim / record_progress / complete / fail | 按共享 Protocol 原子领取、核对 token、推进 train 事件、保存终态或失败；不写指标文件、不打开产物 |

HTTP 调用者已由 M3-03 TaskService/任务路由提供：将 TaskDatasetNotFound 映射 404、IdempotencyConflict 映射 409、TaskStoreError 映射安全存储错误。该 HTTP 交付独立于本节 M3-02 SQL 验收。调用 mark_* 后应读取真实 TaskDetail，不硬编码返回 QUEUED。完整离线恢复与重投不在本仓储自动执行。

同键同规范请求返回 created=False，同键异请求冲突；未提供键或不同键的相同请求允许分别创建。规范请求哈希复用共享契约的补默认/排序 JSON 规则，revision/runtime 不加入哈希；重放不会用新默认覆盖旧快照。SQLite 写锁配合数据库完整唯一索引防止并发先查后插产生重复，NULL 去重键可重复。

仅 PENDING/QUEUED 能被领取；领取清除暂态派发诊断，RUNNING 必须有领取归属。train 总步数一旦已知不能变化（有内部 max_steps 时也必须匹配），较旧/重复步数和 eval 在仍持有归属时返回 True 而不推进。失去 token/非 RUNNING/不存在返回 False，非法参数或损坏记录不能冒充 False。

complete 接收 Worker 已审计的 output_key、manifest_sha256、TrainingSummary，校验键/摘要类型与步数一致性后保存清单哈希、training_summary 和终态。SQL 层不重复打开模型/产物，Worker 必须先调用真实产物审计。失败保留进度；完成或失败后，晚到回调/发布结果不能覆盖终态。提交确认丢失抛 TaskStoreError，调用者须 get_status；测试覆盖“实际已提交”和“提交前回滚”，不能在异常处理中继续 fail 覆盖有效成功。

## 表结构与启动

列/索引以 models/entities.py 和 [迁移清单](contracts/tasks.md) 为准。实现补充了 training_summary JSON（可空，COMPLETED 必填），用于持久化 complete 已有的 summary 参数；celery_task_id 保留原 String(255) 类型并收敛为非空。没有改动 Worker 方法签名或公开响应字段。

SQL 约束检查快照长度/正统计、canonical 数据键、步数/进度、领取对、请求键/哈希对、错误对、生命周期及成功产物元数据；Python 层补充完整 UUID/revision/摘要格式、配置/运行时和响应一致性验证。新增完整去重唯一索引及两种时间/状态排序索引，保留数据集/状态索引。部分唯一索引不能冒充完整去重索引。

新库由启动创建完整表；已有旧任务表或不符合要求的当前结构在 create_all 前被拒绝，显示迁移命令。服务不会自动升级旧表或删除历史记录。CLI 对未知列、未知表约束、旧自定义触发器/相关视图报告 unsupported_schema；保留可识别旧表的自定义索引和主外键关系，不对未知扩展强制覆盖。

## 显式迁移

先停止 API/全部 Worker。检查默认只读，不创建缺失数据库、备份、表或目录：

```bash
uv run --locked python scripts/migrate_tasks.py --check
uv run --locked python scripts/migrate_tasks.py --apply
uv run --locked python scripts/migrate_tasks.py --check
```

仅当报告 ready 时才应用。apply 使用 SQLite backup（包含 WAL）保存 data/backups/tasks-before-m3-{UUID}.sqlite3，权限 0600；再取得写锁重新核对计划，事务重建任务表并复制行/索引/检查外键。建表、复制或重命名失败整笔回滚，备份保留，不覆盖遗留 staging 对象。current 不重复备份，not_initialized 不创建空数据库，blocked/unsupported_schema 不改表。主机进程停止是操作前提，SQLite 写锁不等于证明 API/GPU Worker 已停止。

其他路径可指定 --database-url 和 --data-dir；这是可信运维 CLI 参数，不是 HTTP 输入。检查输出只包含任务 ID、稳定原因码与统计，不输出训练正文或原始数据库异常。

非空旧表必须提供可信 --snapshots JSON，存放在被忽略的 data/ 运维目录。格式示例仅说明映射，不是训练证据：

```json
{
  "11111111-1111-4111-8111-111111111111": {
    "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "runtime": {"precision": "bf16", "max_steps": null, "local_files_only": true}
  }
}
```

```bash
uv run --locked python scripts/migrate_tasks.py --check --snapshots data/task-snapshots.json
uv run --locked python scripts/migrate_tasks.py --apply --snapshots data/task-snapshots.json
```

revision/runtime 必须来自该旧任务的可信记录，不用当前默认值或 main 补造。旧 celery_task_id 为空时还须显式提供 UUIDv4；已有值必须一致，不伪造已发送消息。核对已登记数据集的实际文件、SHA-256/大小/行数，复用共享扫描器；缺文件、统计不符或不可信记录均阻塞整批。

- PENDING/QUEUED 保留状态及原创建时间，不自动派发。
- FAILED 还须 failure_code/failure_message 的安全诊断映射，不能把旧原始路径/异常直接返回给用户。
- RUNNING 默认阻塞。确认服务停止后，可在该项显式设置 interrupt_running=true，结束为 FAILED/WORKER_INTERRUPTED，保留真实已有进度/开始时间、记录迁移结束时间，不伪造 claim_token/worker_id 或重训。这只是迁移处置，不是 M3-06 在线恢复能力。
- COMPLETED 必须通过现有共享 CPU 产物审计，ID/revision/config/runtime/数据摘要与快照一致，保留有效历史进度与时间，存入成功清单摘要和 summary。目录或格式样例存在不能冒充有效产物。

未完成旧任务的 canonical output_path 不作为成功产物发布：新行清空该字段，备份保留旧值、原文件保留。未知路径或不一致状态阻塞，不删文件、不覆盖产物。

本机 2026-11-02 检查旧任务表为 0 行且未发现 API/Worker 进程，已显式备份升级并复查 current；不是迁移了真实历史训练任务。其他成员机器仍按各自报告执行，不复制本机数据库。

## 验证与下一步

隔离 SQLite 测试覆盖并发同键创建、并发领取、快 Worker 与派发竞争、归属丢失、重复/eval 事件、失败保留进度、终态保护、完成提交失败/确认丢失、迁移备份/外键/索引/阻塞/回滚与 CLI。旧成功产物迁移使用显式标识的合成 CPU bundle 调用真实审计器，不是新增 GPU 训练证据。

M3-03 已装配 HTTP/Publisher，M3-04 已使用 SqlTaskRepository(SessionLocal) 和公共实例锁，M3-06 已提供独立对账。见 [Worker](worker.md)、[对账说明](task-reconciliation.md) 和 [A 侧正式审查](worklogs/2026-11-03-m3-04-a-review.md)。真实 SQL/生产 Worker 缺缓存 CPU 消费已验收，完整 GPU/浏览器联调仍在 07。
