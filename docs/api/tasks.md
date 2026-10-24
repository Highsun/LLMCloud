# M3 任务 API 设计草案

日期：2026-10-24；设计基线 0.1。状态：仅规划，未注册路由、未发布 API，也未生成运行时 OpenAPI。M3-01 固定 Pydantic 类型/生成样例，M3-03 从真实应用导出，不能手工维护另一份长期 OpenAPI。总计划见 [M3 开发计划](../m3-development-plan.md)。

## 接口与输入

基础路径 /api/v1；资源 ID 为服务端 UUIDv4，时间为 UTC/RFC 3339。复用已有 ErrorResponse 的核心结构、request_id 和真实 HTTP 状态；客户端用稳定 code，不解析中文文案。

| 方法 | 行为 | 成功 |
| --- | --- | --- |
| POST /tasks | 保存任务/固定快照并有界派发，不等待训练 | 新任务且确认接受为 202，TaskDetail，Location=/api/v1/tasks/{id} |
| GET /tasks | 先按 status 筛选再分页，created_at DESC/id DESC | 200，TaskPage |
| GET /tasks/{task_id} | 数据库业务状态与配置详情 | 200，TaskDetail |

POST 保留现有 TaskCreate：dataset_id 必填；base_model 默认且只允许 Qwen/Qwen2.5-0.5B-Instruct；config 默认 {}，按原 TrainingConfig 补齐默认值。未知字段拒绝。服务器固定 model_revision/runtime，不接收服务器路径、revision、max_steps、状态、哈希或用户归属。任务 JSON 请求体上限拟定 64 KiB，由 01 明确并检查；不改变数据集上传上限。

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

413 新错误 code、TASK_NOT_FOUND、去重/派发 code 均由 01 加入对应类型，不能在实现时临时用中文文案兼容。已有数据接口错误保持原含义；若共用 enum 变化影响导出，同提交重导出和检查。

若任务已持久化而 POST 返回派发错误，采用专用 TaskSubmissionErrorResponse：仍为顶层 error，继承原 code/message/details/details_truncated/request_id 核心字段，新增必填 error.task_id。仅该响应子类型增加字段，不给所有数据集错误强行增加 null 字段。数据库在任务创建前失败时仍用原 ErrorResponse，无可用任务 ID，不伪造 ID。

规划错误样例，未发生实际发送：

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

01 前 B 可先按本草案完成列表筛选/分页/请求竞争小交付，范围与验收见 [完整计划第三节](../m3-development-plan.md)。ALL 不发送 status，其余发送五状态之一；切状态回第一页，翻页/刷新/轮询保留筛选；旧成功、失败及 finally 不能覆盖最新状态。该小交付只计为 05 部分完成，不抢先猜 Worker 类型。

01 共享类型生成 fixture 后同步前端测试；B 的测试替身必须显式标为 mock、单独用于测试，不能形成第二套长期响应约定。未注册真实路由时 supports 仍返回 false。03 实现后导出 docs/api/tasks.openapi.json，路径采用 /api/v1 server + 相对 paths，运行时完整 paths 与操作/Schema 一致。不要在当前规划阶段伪造已实现的 OpenAPI。

B 修改通用 request 以可选 headers 携带去重键、读取专用 error.task_id，A 修改允许头以配合跨域；不改变数据集上传行为。任务列表状态筛选上送服务端，过时请求不能覆盖较新页/筛选结果，终态停止详情轮询。M3 不接通 Loss/日志/下载：保持能力探测和未实现提示，不在真实 API 请求失败后自动回退 mock。
