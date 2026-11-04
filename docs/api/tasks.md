# M3 任务 API 契约

更新：2026-11-04；契约 1.0.0。M3-03 已实现任务创建/列表/详情 HTTP、请求去重和真实 Redis/Celery Publisher；[任务 OpenAPI](tasks.openapi.json) 从实际 app.openapi() 导出。M3-04 Worker/公共锁已合入并完成真实 Redis 缺缓存 CPU 消费检查，05 已接通 HTTP/SQL 并审查合入，GPU 和生产浏览器链路已在 [07 A 真实运行](../worklogs/2026-11-04-m3-07-a.md) 通过，B 异步复核已通过，待同步人工联调。类型与分工见 [共享契约](../contracts/tasks.md)、[完整计划](../m3-development-plan.md) 和 [Worker](../worker.md)。

## 接口与输入

基础路径 /api/v1；资源 ID 为服务端 UUIDv4，时间为 UTC/RFC 3339。复用已有 ErrorResponse 的核心结构、request_id 和真实 HTTP 状态；客户端用稳定 code，不解析中文文案。

| 方法 | 行为 | 成功 |
| --- | --- | --- |
| POST /tasks | 保存任务/固定快照并有界派发，不等待训练 | 新任务且确认接受为 202，TaskDetail，Location=/api/v1/tasks/{id} |
| GET /tasks | 先按 status 筛选再分页，created_at DESC/id DESC | 200，TaskPage |
| GET /tasks/{task_id} | 数据库业务状态与配置详情 | 200，TaskDetail |
| GET /tasks/{task_id}/metrics | 有界指标续读，source_id/cursor/limit | 200，MetricsPage；M4-02 已实现 |
| GET /tasks/{task_id}/logs | 任务安全日志尾部，tail | 200，LogsPage；M4-02 已实现 |

POST 保留 TaskCreate 的 dataset_id/base_model/config 字段：dataset_id 必填且为 UUIDv4；base_model 默认且只允许 Qwen/Qwen2.5-0.5B-Instruct；config 默认 {}，按原 TrainingConfig 补齐默认值。未知字段拒绝。服务器固定 model_revision/runtime，不接收服务器路径、revision、max_steps、状态、哈希或用户归属。请求为未压缩 UTF-8 application/json，允许 UTF-8 charset/identity 编码；不接受重复 JSON 键（含嵌套配置）、非有限数字、无效 JSON 或非对象正文。未知/重复查询和重复去重请求头也拒绝。

任务 JSON 运行时上限为 64 KiB（65,536 字节）。声明超限不读取正文；真实分块累计也受限，伪造 Content-Length 不能绕过。415 使用 UNSUPPORTED_MEDIA_TYPE，JSON/字段错误 422/VALIDATION_ERROR，非法 Content-Length 为 400/HTTP_ERROR。M1 数据集上传上限和错误语义不变。

可选请求头 Idempotency-Key 为 UUIDv4。首次成功保存时原子绑定规范请求哈希（dataset_id/base_model/完整 config）；同键同请求返回 200 和原 TaskDetail，不重新派发；同键不同请求 409/IDEMPOTENCY_CONFLICT。服务端 revision/内部 runtime 变化不会改写已存在任务快照。没有该头时每个 POST 都是新任务。浏览器刷新后若有任务 ID，查询原任务，不盲目重新提交。

请求例子为格式说明，不是已创建任务：

```json
{
  "dataset_id": "03a853e2-1bf1-45da-92fb-5a1548499fc4",
  "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
  "config": {"lora_r": 8, "lora_alpha": 16, "learning_rate": 0.0002}
}
```

## 查询与响应

GET /tasks 接受 page（默认 1）、page_size（默认 20，1–100）、status（可省略；五个 TaskStatus 之一，区分大小写）。page 为正整数；重复/未知查询字段 422。越过末页返回 200/空 items；空结果 total_pages=0。前端切状态先回第一页，不再只筛当前页。

| 字段 | TaskSummary / TaskDetail 语义 |
| --- | --- |
| id / dataset_id | UUIDv4 |
| base_model / model_revision | 受控模型 ID / 完整固定 40 位 revision |
| status | PENDING、QUEUED、RUNNING、COMPLETED、FAILED |
| current_step | 非负优化器更新步数，初始 0 |
| total_steps | 正整数或 null；未收到真实 train 事件时 null |
| progress | 0–1 或 null；total_steps 未知时 null，已知时 current_step/total_steps |
| error_code / error_message | 可空稳定码/安全说明；无服务器路径/原始样本/凭据 |
| created_at / started_at / finished_at | UTC；开始/结束未发生时 null |
| config | 仅 TaskDetail 包含完整补默认 TrainingConfig；对外只用 config，不暴露 SQL training_config 别名 |

TaskPage 为 items、total、page、page_size、total_pages。列表用 TaskSummary，详情/创建用 TaskDetail。SQL 既有 total_steps=0、progress=0 不表示已知计划总步数，DTO 映射须转为上述 null 语义。FAILED 保留已发生的真实步数，不重置成 0；完成步数可以先到 100% 而状态仍 RUNNING，前端不能据 progress 自行判定完成。

以下只是列表格式 fixture；数值/ID/时间不是训练证据：

```json
{
  "items": [{
    "id": "992aa53a-a246-45de-a8f1-4d4164d9b42e",
    "dataset_id": "03a853e2-1bf1-45da-92fb-5a1548499fc4",
    "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
    "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "status": "RUNNING", "current_step": 0, "total_steps": null, "progress": null,
    "error_code": null, "error_message": null,
    "created_at": "2026-10-24T01:00:00Z", "started_at": "2026-10-24T01:00:01Z", "finished_at": null
  }],
  "total": 1, "page": 1, "page_size": 20, "total_pages": 1
}
```

PENDING 是保存成功但尚未确认派发；QUEUED 是确认接受后等待领取；RUNNING 包含加载/预处理/训练/保存；COMPLETED 晚于训练及产物审计/数据库提交。FAILED 有明确原因。不承诺排队名次、预计完成时间或每项任务已执行生成验收。

TaskDetail.error_code 是业务诊断，和 HTTP error.code 不必相同：训练失败复用现有 TrainingFailure code，离线恢复另需 WORKER_INTERRUPTED/TASK_ABANDONED，派发未知可暂为 DISPATCH_UNCERTAIN，成功领取/确认后清除该暂态说明并保留服务日志。不要为这些任务级原因修改 Trainer 的既定枚举；M3-01 单独定义业务错误集合及映射。

不返回 output_path、cache_dir、log_path、celery_task_id、claim_token 或用户归属。不返回虚构 Loss，也不新增 metrics/logs/adapter/inference 路由；这些继续按 M4/M5 实施。模型目录不等于缓存就绪。

## 错误和派发不确定性

| HTTP / code | 条件 | 前端处理 |
| --- | --- | --- |
| 422 / VALIDATION_ERROR | UUID、配置、查询或去重头格式错误 | 展示字段错误，不提交 |
| 404 / DATASET_NOT_FOUND | 创建引用不存在的数据集 | 刷新数据列表 |
| 404 / TASK_NOT_FOUND | 详情不存在 | 明确缺失，不显示假任务 |
| 409 / IDEMPOTENCY_CONFLICT | 同键请求内容不同 | 保留原意图，用户明确新任务时换键 |
| 413 / REQUEST_TOO_LARGE | 任务 JSON 超过 64 KiB | 缩小配置；不得影响 M1 的 UPLOAD_TOO_LARGE |
| 503 / DATABASE_UNAVAILABLE | 事务/查询不可用 | 未确认提交时不自动重发 |
| 503 / DISPATCH_FAILED | 明确未派发，保存的任务已条件更新 FAILED | 用 task_id 查询失败记录 |
| 503 / DISPATCH_UNCERTAIN | 可能已派发、确认或后续状态写入失败 | 查询同一 task_id，保留去重键；可能稍后 RUNNING |

上述错误已接入实际路由/错误处理；已有数据接口错误保持原含义。通用错误无 task_id，已持久化任务的派发错误才使用专用 TaskSubmissionErrorResponse。错误与成功均返回服务端 X-Request-ID；202、200 重放及带 task_id 的 503 返回该任务的 Location。

若任务已持久化而 POST 返回派发错误，采用专用 TaskSubmissionErrorResponse：仍为顶层 error，继承原 code/message/details/details_truncated/request_id 核心字段，新增必填 error.task_id。仅该响应子类型增加字段，不给所有数据集错误强行增加 null 字段。数据库在任务创建前失败时仍用原 ErrorResponse，无可用任务 ID，不伪造 ID。

以下仍为格式样例，不对应某次实际请求：

```json
{
  "error": {
    "code": "DISPATCH_UNCERTAIN", "message": "任务派发结果待确认，请查询该任务。",
    "details": [], "details_truncated": false,
    "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df",
    "task_id": "992aa53a-a246-45de-a8f1-4d4164d9b42e"
  }
}
```

503 不等于任务绝对未执行。若 Worker 已领取，API 必须保留 RUNNING/终态，不用派发错误覆盖。初始 publish accepted 后 QUEUED 写入失败也应提供可查询的原 task_id；相同去重键重放读取原任务，不自动补发。用户查询后的重试/新任务必须明确区分。

## 交付和前端接入

B 已交付列表筛选/分页/请求竞争小交付，范围与验收见 [完整计划第三节](../m3-development-plan.md)。ALL 不发送 status，其余发送五状态之一；切状态回第一页，翻页/刷新/轮询保留筛选；旧成功、失败及 finally 不能覆盖最新状态。该小交付是当时的部分交付；目前 Worker 核对/实现及完整 05 已合入，生产 GPU 已由 07 A 实测，B 异步复核已通过，待同步人工联调。

01 的 [fixture](../examples/tasks/README.md)继续用于隔离测试，scripts/export_task_contract.py --check 检查类型样例漂移。03 已实现原始重复字段解析，并用 scripts/export_task_openapi.py 从实际路由生成任务 OpenAPI：/api/v1 server + 相对 paths，运行时 /openapi.json 使用完整 paths，操作/Schema 一致。此输出表示 HTTP 已实现，不证明 Worker/GPU 就绪。

M3-05 已为 request 透传去重头、读取 error.task_id，冻结正文并支持 sessionStorage 刷新恢复；后端 CORS 已允许 Content-Type/Idempotency-Key，并暴露 X-Request-ID/Location，不启用凭据。05 的列表/提交/详情 HTTP/SQL 浏览器检查使用明确的 Publisher/执行事件替身；07 A 已另行通过实际 Redis/Worker/GPU/生产浏览器自动验收，B 异步复核已通过，待同步人工联调。M3 不接通 Loss/日志/下载：这些能力继续禁用，不能在 API 出错后回退 mock；本次没有修改 B 的前端代码。

## M4 规划中的观测与交付

M4 的 [观测契约 1.0.0](task-observability.md) 和 CPU 类型/常量/格式样例已由 01 A 侧交付，B 消费核对待记录；02 已实现指标/日志只读服务、安全投影和 HTTP；下载仍待 03。原 TaskCreate/TaskDetail 和派发语义不变。02 已扩展 export_task_openapi.py 导出全部实际任务子路径，不提前登记下载空路由。前端旧 after_step/Map(step) 仍由 04 按新契约替换。

## Publisher 与失败边界

API 的 TaskService 先通过 SqlTaskRepository 保存任务/快照，再调用 Publisher，一次提交只有一次发布尝试。重放 created=False 直接返回原任务，不补发；即使原记录停在 PENDING 或已有失败，也不自动创建/发布第二项任务。Broker 状态不作为查询任务的来源。

CeleryPublisher 使用独立客户端，以 worker.train 名称发送 args=[task_id]，消息 ID 使用单独保存的 celery_task_id，队列取 TRAINING_QUEUE；不导入 worker.tasks、Trainer、GPU 或结果后端。连接/读写按 TASK_PUBLISH_TIMEOUT_SECONDS 配置，默认每次操作 1 秒（可设 >0 且 ≤5）；Kombu 建连 max_retries=0、发送 retry=False、Celery 发布重试关闭，Redis 命令重试也显式设为 0。仅支持一个 Redis/rediss/redis+socket URL，不配置备用 Broker 自动切换。实现同时核对了锁定的 Celery 5.6.3/Kombu 5.6.2/redis 6.4.0 源码；参考 [Celery 消息发布/重试](https://docs.celeryq.dev/en/stable/userguide/calling.html#message-sending-retry)、[Kombu 连接接口](https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.connection.html)。

建连/发送前失败才为 not_sent；进入 send_task 后任何异常保守为 unknown，即使可能发生在实际写入前。accepted 仅证明本次调用确认成功，不承诺 Redis 崩溃后的消息持久性。清理失败不会抹去已确认的发布。Socket 超时按操作计算，SQLite 锁等待和操作系统 DNS 耗时另计；这不是整个 HTTP 请求必定在 1 秒内结束的承诺，正常本机约 2 秒仍为性能目标。

accepted 后仅条件更新仍 PENDING 为 QUEUED，再重读真实 TaskDetail；若快 Worker 已 RUNNING/终态，直接保留。not_sent 仅在本次确实把仍 PENDING 改为 FAILED 后返回 DISPATCH_FAILED；若已有领取/终态等矛盾结果，保守返回 DISPATCH_UNCERTAIN。unknown 或发布确认后的状态写入/查询失败返回带原 ID 的 503，暂态诊断写入失败也不丢弃 ID，不覆盖 RUNNING/终态。

数据库在创建完成确认前失败时可能没有可用任务 ID，返回通用 DATABASE_UNAVAILABLE，且不发布消息。同一去重键之后可读取已提交记录，但不会自动补发；M3-06 已提供 [离线对账/显式处置工具](../task-reconciliation.md)，共享锁已由实际 Worker 复用并经 CPU 互斥/停止释放检查，GPU 退出恢复已在 07 A 实测并经 B 异步复核，双方同步人工端到端操作仍待完成。这是无 outbox/自动重投 MVP 的已知边界。

## 运行与验证

服务按根 README 启动；先上传数据取得 dataset_id，再按上述 JSON 提交。无 Worker 时接受发布的任务保持 QUEUED，不能把 HTTP 202 当作训练成功。worker.train 已由 M3-04 实现，生产 Worker 的真实 Redis 缺缓存 CPU 消费已通过；真实 GPU 训练已在 M3-07 A 自动验收通过，双方同步人工流程仍待执行；Celery ping 或该 CPU 路径不能代替训练成功。

```bash
uv run --locked python scripts/export_task_openapi.py --check
uv run --locked python scripts/check_task_http.py
```

check_task_http.py 需要 redis-server，自动启动仅本进程拥有的临时 Redis Unix socket、临时 SQLite/文件和真实 TCP API；不访问业务队列、不开 Worker/GPU。检查真实消息名/两个 ID/仅 task_id 载荷、202/200 重放且队列不增长、筛选/详情、实际 LPUSH 后注入确认丢失并保持同一任务、Broker 停止后可查询失败，以及提前 413。输出明确标注 lost_ack_injected、worker_started=false、gpu_execution_verified=false；确认丢失是受控故障，不谎称自然网络故障。
