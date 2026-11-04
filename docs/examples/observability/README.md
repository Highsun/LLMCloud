# M4 观测契约格式样例（全部为 mock）

由 scripts/export_observability_contract.py 从正式 CPU 类型生成，不手工修改。index.json 标注每个文件的模型和用途；数值、UUID、时间、文件版本/哈希及内部完成快照均为格式占位，不是训练/HTTP/GPU 验收。

metrics-first-page 与 metrics-next-page 是同一虚构 UTF-8 JSONL 流的两页，演示查询显式 limit=2（协议默认仍为 200）；offset/next_cursor 根据原 TrainingProgress 紧凑 JSON 加换行的字节数实际计算，同一步 train/eval 都保留。terminal-drained 展示已消费完的终态空页；empty 是存在的空文件，not-created 是尚未产出；incomplete-tail 不把半行当点。zero-loss 的 0 是有效值。其他文件是不同边界场景，不代表同一运行的连续历史；内部完成快照/下载头使用另一个 UUID，避免把含 eval 的格式流误当作当前服务已配置验证集。

logs-* 是安全投影后的格式示例，不表示 M4-02 已实现日志读取/过滤。adapter-headers 和 download-busy-headers 描述 HTTP 头（前者的 task_id 只是上下文），下载成功的真实 body 是 ZIP，不是这些 JSON。completed-artifact-spec 是内部脱离 SQL 的占位 DTO，不包含真实权重，也不能证明数据库完成或产物有效。

本导出器只提供类型，不声明运行时 metrics/logs/adapter 路由是否实现，前端须按真实 OpenAPI 能力探测。正式字段/约束与消费者核对清单见 [观测契约](../../api/task-observability.md)。重新生成使用 uv run --locked python scripts/export_observability_contract.py；加 --check 只读检查 Schema、全部样例及多余 JSON 的漂移。
