# M3 任务格式样例（mock）

此目录由 scripts/export_task_contract.py 从 [共享类型 1.0.0](../../contracts/tasks.md) 生成 JSON，README 手工维护。ID、时间、数据摘要、步数、错误和成功状态均是测试占位，不对应数据库任务、真实训练、有效产物或评测结论；revision 使用项目固定值不代表执行过该样例。

- create-request / submission-headers / list-query：请求体、提取后的去重头、查询参数；ALL 不发送 status。
- detail-pending/queued/running/completed/failed：五状态；running 无已知总步数，failed 是开始后、训练前失败。
- detail-running-progress / running-saving / failed-training：部分进度、步数 100% 但仍保存、失败保留真实已发生步数的格式。
- list-response / empty-page / beyond-last-page：分页形状，列表不包含 config。
- submission-error：已持久化任务的派发确认未知，error.task_id 可查询；database-error 没有任务 ID。
- execution-spec：Worker 领取快照，不含绝对路径；摘要/字节数/行数为占位，不得用于真实执行。

网络替身只用于 frontend/tests 或 Worker 独立检查，不能出现在生产页面或 API 失败兜底中。本目录没有 OpenAPI；真实路由属 M3-03。

生成：uv run --locked python scripts/export_task_contract.py；只读检查加 --check。禁止单独手改生成 JSON。
