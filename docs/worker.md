# M3-04 Worker 执行与独立检查

本模块按任务共享契约 1.0.0 编排现有 Trainer，不实现 SQL、HTTP、模型下载或第二套指标写入。入口为 `worker.execution.execute_training(task_id, repository, settings, train_fn)`；只依赖可注入的仓储/设置/训练函数。生产 Celery 任务名仍为 `worker.train`，消息 args 仅包含规范 UUIDv4 的 task_id。

2026-11-03 接续：146d60b 已经 A 正式审查、本机 328 项回归后快进合入。实际 Redis/生产 Worker 的缺缓存 CPU 消费、重复消息跳过和对账锁互斥也已通过；后续 [M3-07 A 真实运行](worklogs/2026-11-04-m3-07-a.md) 已通过 GPU/浏览器自动验收，B 异步复核已通过，待同步人工联调。记录见 [审查日志](worklogs/2026-11-03-m3-04-a-review.md)。

## 执行和状态

1. 生成每次领取独立的 claim_token 和 worker_id，调用 repository.claim。未领取即 skipped，不访问数据/模型/GPU，不创建或清理旧任务目录。存储异常为 reconciliation_required，不冒充重复消息。
2. 重新验证领取快照；复用 resolve_dataset_path/DatasetScanner 校验受控数据路径、原始哈希、大小和行数，核对独占输出/日志路径。
3. 用 resolve_model_paths 取得当前主机的 Hub cache，执行只读离线 verify_model_cache；使用领取时的固定 revision、config/runtime 构造原 TrainRequest。缺缓存直接失败，不自动联网下载。
4. 调用原 train(request, on_progress)。Trainer 唯一写入并 flush metrics；Worker 只传递原 TrainingProgress 给仓储。False 表示失去归属，立即停止后续状态写入；即使 Trainer 将回调异常包装为 TrainingError，也保留该判定。
5. Trainer 返回后调用真实 CPU 产物审计器，比对任务 ID、revision、模型/参数/runtime、数据摘要/统计和输出布局；核对清单审计前后摘要，再条件 complete。Worker 不预建 outputs/{task_id} 或 logs/tasks/{task_id}.log，这些由 Trainer 独占创建。
6. Trainer/数据/缓存/产物失败记录安全 TrainingFailure。有效产物完成写入确认丢失时改走 get_status：实际 COMPLETED 返回 completed；否则保留产物与真实状态，返回 reconciliation_required，不继续 fail、不删除产物、不自动重发。

执行结果区分 completed、failed、skipped、ownership_lost、reconciliation_required。Celery 返回 `{task_id, outcome}` 仅用于执行诊断，业务状态仍以数据库为准；Celery SUCCESS 不等于训练业务完成。KeyboardInterrupt/SystemExit 不被当作普通训练失败，遗留状态交 M3-06 对账。

## 单实例保护和生产装配

锁文件是 `LOG_DIR/worker.lock`。Linux Worker 复用 `backend.app.core.worker_lock.WorkerInstanceLock` 公共 flock 原语，与 M3-06 对账工具互斥；Windows msvcrt 仅用于本机 CPU 检查。进程整个生命周期持锁，退出或被杀死后由 OS 释放，文件保留，不能手动删除活动锁文件来绕开保护。应用离线对账前仍须先停 API/Worker，并使用相同 LOG_DIR。

标准 `python -m worker` 在调用 Celery 前持锁；直接 Celery CLI 的 worker_init 钩子也取得同一锁并核对 solo/concurrency=1/prefetch=1。钩子使用 SystemExit 拒绝启动，因为普通异常会被 Celery 的信号分发记录后吞掉。wrapper 和信号钩子在同一进程幂等复用锁；任务函数的可信直接/eager 调用同样保护。

生产任务函数延迟导入 SqlTaskRepository(SessionLocal) 和原 Trainer，不向 Trainer 传递 Session/ORM；不在执行函数内部写 SQL。早确认、无任务自动重试；Worker 崩溃后不承诺自动重训或 exactly-once。

所有共享同一物理 GPU 的 Worker 必须使用相同 LOG_DIR。此锁不限制外部手工 Trainer CLI、其他 GPU 应用或多台主机；真实 GPU 联调时双方应协调运行时段。

在已配置的 WSL/Linux 训练环境：

```bash
# 首次准备训练依赖与固定模型缓存，按现有 training/model-cache 文档执行。
uv sync --locked --extra training
# 新库先正常启动 API 初始化；旧库先执行独立迁移 check，确认后再 apply。
uv run --locked python scripts/migrate_tasks.py --check
bash scripts/start_worker.sh
```

直接启动等价入口，仍受实例锁保护：

```bash
uv run --locked celery -A worker.celery_app:celery_app worker --pool=solo --concurrency=1 --prefetch-multiplier=1 --queues=gpu,celery --loglevel=info
```

training_queue 若配置为其他名称，使用该名称代替 gpu。任务 HTTP/Publisher 已由 M3-03 提供，但服务可用不表示模型/GPU就绪。不要为测试列表而提交真实训练。

## 独立 CPU 检查（无需 GPU、模型或真实 Redis）

在仓库根目录、项目目标 WSL/Linux 环境中使用独立环境，避免同步时移除已有 GPU 环境的额外依赖：

```bash
UV_PROJECT_ENVIRONMENT=.venv-worker-tests uv sync --locked
UV_PROJECT_ENVIRONMENT=.venv-worker-tests uv run --locked python -m unittest discover -s tests -p 'test_worker_*.py' -v
UV_PROJECT_ENVIRONMENT=.venv-worker-tests uv run --locked python -m unittest discover -s tests -q
```

本次 Windows 机器已经创建忽略目录中的 Python 3.12 CPU 环境，可直接运行：

```powershell
# 在 LLMCloud 仓库根目录执行
$env:PYTHONUTF8 = '1'
.\.venv-worker-tests\Scripts\python.exe -m unittest discover -s tests -p 'test_worker_*.py' -v
```

Windows 未开启符号链接权限时，对应两项新检查明确跳过；另两项 Linux 公共锁互操作检查也在 Windows 跳过。完整历史测试依赖 Linux 的链接、权限和文件句柄行为，使用 WSL/Linux/现有 CI 验证；不修改旧测试或重新生成不同哈希的样例来隐藏环境差异。

检查分为：

- 内存仓储与训练替身：领取/重复跳过、真实数据扫描、快照与路径、进度/失去归属、失败、产物审计和完成确认丢失。
- 临时 SQLite + 合成 CPU 产物：真正调用 A 提供的 SqlTaskRepository，核对成功、重复、失败保留步数、提交前回滚/提交后确认丢失和 Celery 任务装配。
- OS 进程与 Celery：锁互斥、进程被杀后释放、标准入口/直接 Celery 拒绝第二实例、真实 Celery 安全配置首次初始化可通过、信号异常不能被吞掉。

测试中的缓存/训练替身和合成 safetensors 不代表真实模型训练或重载成功。所有数据库、数据文件、锁、产物只在临时目录；不触碰业务库。两个 GPU 任务串行、训练中断恢复和生产浏览器已在 M3-07 A 另行真实验收通过；B 异步复核已通过，待同步人工联调，不能与这些替身测试混为同一证据。

## 真实 Redis/生产 Worker 的 CPU 冒烟

```bash
uv run --locked python scripts/check_worker_dispatch.py
```

需 redis-server，自动使用私有 Redis、TCP API、临时 SQLite 和生产 Worker，内存结果后端不连接业务结果存储。空的隔离模型缓存和禁用 CUDA 保证在 MODEL_NOT_CACHED 前置检查结束，验证真实消费、重复消息跳过、活 Worker 拒绝离线对账及服务停止后锁释放。报告明确 gpu_execution_verified=false，不将预期缺缓存失败当作成功训练或 GPU 验收。
