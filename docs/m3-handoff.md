# M3 两人接续说明

日期：2026-10-24。这里只交付规划；M3 业务代码尚未实现。先读 [完整计划](m3-development-plan.md) 和 [API 草案](api/tasks.md)，再读取实际 Git/队友工作日志。A=你/当前后端侧，B=已有前端的队友。

## 先共同完成一件小事

M3-01 由 A 主笔、双方各投入约 1 小时：共同核对字段、领取/回调/完成接口、派发结果三种语义、SQLite 新列和错误结构；提交 CPU 类型/Protocol、生成 fixture 与检查。B 关注 TaskRepository 是否足以执行 Worker、前端能否消费响应，不等 A 写完业务。

本次文档是 01 的设计输入，不能将 01 标成完成。B 在共享代码提交前可以写前端行为用例/明确标识的 fixture，但不自己猜一份 SQL/状态协议。01 一旦合入，双方从同一提交分支实现。

## 给 A 的任务入口

顺序：M3-02 数据库/迁移与所有权状态 → M3-03 HTTP/Publisher → M3-06 离线对账。

你主改 backend 的 entities、task_repository、task_migration、Task API/业务服务/派发、main/config、迁移/导出/对账脚本。所有数据库状态变更都从仓储完成。HTTP 使用 Publisher 替身检查，不要求 B 的真实 Worker 已完成；生产发送用稳定任务名 worker.train，避免导入 Worker 才能启动 CPU API。

对 B 提供稳定的 claim/record_progress/complete/fail 与 TaskExecutionSpec；不把 SQL Session 或 ORM 实体交给 Trainer。产物审计/哈希、CAS、同键创建和发送未知结果是关键检查。不要为了让页面先显示而虚构任务。

## 给 B 的任务入口

顺序：M3-04 Worker 执行接入 → M3-05 现有前端接通。两项由你顺序做，不计成两个并行人力。

你主改 worker/execution.py、tasks.py、instance_lock.py、celery_app.py、__main__.py/start_worker 和 frontend。Worker 用同 Protocol 的内存仓储与训练替身独立验证，不等 SQL 实现；替身不在生产配置启用。前端按 TaskDetail/config、服务端分页/状态筛选、Idempotency-Key 和 error.task_id 接入，用测试 fixture 不等 HTTP 完成。

不直接修改 ORM、数据库迁移或共享 Settings；缺类型/配置时告诉 A，在共享提交一次改好。不要复制 Trainer、不写 metrics、不把 Celery SUCCESS 当 COMPLETED，不用 step 合并 train/eval 给后续 M4 埋错。

## 真正需要一起做的部分

01 的接口核对；Worker 装配真实 SqlTaskRepository；最后真实 Redis/GPU/浏览器和失败联调。这些都不能仅靠各自替身测试代替。

先让可测试的小部分分批合入，不等两个大分支都做完。可用 feature/m3-api-state、feature/m3-worker-ui；每次 fetch 后核对新增日志和修改，正常 merge，不强推。不同机器或独立 worktree，不能两个 AI 同时编辑同一 checkout。各自临时数据库/队列隔离，GPU 验收预约 B 的一个时段，A 观察 API/SQL。

主线预算 A/B 各 10 人时，另各 2 小时缓冲；按各自每周 6–8 小时安排 1.25–2 周，提前启动不必等原 W3 日期。若工时吃紧，先延长本阶段实际实施窗口，保留正确状态/异常和共同验收，不把 mock 当作快速完成。

每项交付自己的 YYYY-MM-DD-m3-XX-a/b.md，写清基线、协议版本、已测/未测、接口影响和接续调用。共享 README/AGENTS/规划/记忆与日志索引由 A 在合并时汇总，避免两边反复覆盖。默认保留对方未提交改动。

最终演示：浏览器上传数据并提交两项任务 → 观察串行/状态/真实步数 → 只读核验各自产物 → 重复投递不重训 → 一项失败可查询 → 停服务后对账遗留任务。Loss 曲线/日志 HTTP/下载和在线推理分别留给 M4/M5。
