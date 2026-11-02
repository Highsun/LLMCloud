# M3-01 B 侧 Worker 消费者核对

日期：2026-11-02。契约 1.0.0。B 侧核对依据为实际 core/task_contract.py、core/task_protocols.py、models/task_schemas.py、原 Trainer/缓存/产物审计和 A 的 M3-01/02/03 日志，不以阅读文档代替运行检查。用户要求完成核对并接续 M3-04。

## 同步与结论

起点工作区干净，但工作分支 cacb198 尚未包含远端 ec9fb5c。先快进同步 M3-02，保留前端小交付。开发期间 fetch 发现 d077f84（M3-03）；核对新增日志、变更文件和共享契约，确认不修改本次 Worker 文件后再次快进同步，保留本次未提交实现。M3-03 没有改变五个 Worker Protocol 方法。

**B 侧 Worker 契约核对完成，现有类型足够实现 M3-04，无需新增共享字段或复制一套类型。** 这是本侧核对结果，供 A 汇总；不代表双方已经完成真实 Redis/GPU 验收。共享入口/状态/索引仍由 A 汇总，本次新增自己的核对和交付日志。

| 核对项 | 结果及实施对应 |
| --- | --- |
| 导入与 CPU 边界 | TaskStatus/ExecutionOutcome 在 core/task_contract；TaskExecutionSpec/TaskRepository/ExecutionSettings/TrainFunction 在 core/task_protocols。执行层使用这些原类型，生产模块可在禁止 torch/numpy/HF 导入时加载 |
| 五个仓储方法 | claim 返回快照或 None；record_progress/complete/fail 的 False 表示无归属；get_status 为完成确认丢失后读取已提交状态。方法同步调用，异常不冒充 None/False |
| 执行快照 | dataset_key/hash/size/rows、固定 revision、config/runtime 足够构造原 TrainRequest。重新验证并复制可变 config；实际文件、链接和哈希由执行层检查，不能只信 Schema |
| 进度与指标 | TrainingProgress 是 Trainer flush 后的同源事件；仓储处理 train/eval/重复步数，Worker 不再写 metrics。失去 token 时停止，不让被包装的回调错误覆盖为 FAILED |
| 成功与完成写入 | 使用真实 verify_training_artifacts 和清单摘要、比对领取快照，再 complete；有有效产物但确认丢失时 get_status，保留真实终态/产物或留待对账 |
| 错误与执行结果 | 保留 M2 TrainingFailure code；区分 completed/failed/skipped/ownership_lost/reconciliation_required。生产诊断不记录原始异常文本、路径或训练正文 |
| 生产工厂/队列 | SqlTaskRepository(SessionLocal) 由 A 提供，B 只在 tasks.py 装配；实际 Publisher 使用 worker.train，args 只有 task_id，消息 ID 独立于业务 ID，生产任务名保持一致 |
| HTTP 消费者边界 | 已核对 TaskDetail.config、null 进度、专用 error.task_id 与 Idempotency-Key 重放语义。它们属于后续完整 M3-05 接通，本次不声称已实现提交去重前端 |
| fixture/导出 | 沿用生成的任务/训练/数据集类型和样例，不手改生成文件；只读漂移检查随 M3-04 回归记录 |
| 单实例与对账交接 | 无需新增 Settings 字段；使用已有 LOG_DIR，锁路径为 worker.lock。最终推送前已同步 A 的 M3-06（056f8e1），Linux Worker 复用其公共 WorkerInstanceLock(log_dir)，并补充双向跨进程互斥检查；仍须先停服务再应用离线对账 |

## 验证与待交接

Worker 独立测试包含内存 Protocol 替身、临时真实 SQL 工厂、真实 CPU 审计、两种实际进程启动拒绝以及 CPU-only 导入检查；结果见同日 [M3-04 B 侧日志](2026-11-02-m3-04-b.md)。所有数据和产物是隔离测试替身，不能当 GPU 训练证据。

本次不修改 A 的 SQL、HTTP、共享 Schema、默认字段或原 Trainer。M3-04 后需接续完整 M3-05 的提交/详情/去重与错误处理，并安排 M3-06/07 的真实 Redis/GPU/浏览器验收。
