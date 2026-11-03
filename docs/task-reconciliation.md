# M3-06 离线任务对账

更新：2026-11-03。A 侧 CLI、SQL 条件更新、CPU 产物审计及公共锁已交付；M3-04 已接入标准/直接 Celery 入口，真实生产 Worker 的锁互斥/停止释放 CPU 冒烟通过。GPU 中断及成功产物遗留恢复仍待 07。依据：[完整计划](m3-development-plan.md)、[共享契约](contracts/tasks.md)、[Worker](worker.md) 和 [审查日志](worklogs/2026-11-03-m3-04-a-review.md)。

## 什么时候使用

早确认的 Worker 异常退出，或训练成功保存后数据库完成提交的确认丢失，可能留下非终态记录。对账读取数据库快照与已有文件，显式结束这些遗留任务，不重新派发、不运行 Trainer、不补写指标、不覆盖或删除部分产物。

这是本机 SQLite 的离线维护命令，不注册 HTTP 路由、不在 API 启动时运行。没有按时间、无 Loss 或 Celery 结果后端判断活跃任务死亡的逻辑。在线执行 --check 只得到候选方案，不能据此认定正在加载模型的任务已经失联。

## 运行顺序

先查看候选方案（默认即 --check）：

```bash
uv run --locked python scripts/reconcile_tasks.py --check
```

确认维护范围后，在对应终端或进程管理器中停止 API 和全部 Worker；本机正在手动运行的训练/重载也必须结束，再重新检查并显式应用：

```bash
uv run --locked python scripts/reconcile_tasks.py --check
uv run --locked python scripts/reconcile_tasks.py --apply --services-stopped
uv run --locked python scripts/reconcile_tasks.py --check
```

--services-stopped 是操作者对实际停机的声明，不会自动停进程，也不是工具检测到全部服务已停止的证明。还必须取得下述实例锁；若有活进程持锁，工具拒绝应用。04 已接入公共锁，实际生产 Worker 持锁时工具已验证拒绝应用；锁空闲仍不能证明 API 或绕过协议的手工 GPU 程序已经停止，应用前必须实际确认。

默认检查全部任务，只修改非终态。可重复指定 --task-id UUIDv4 缩小范围；任一指定 ID 不存在则阻塞该次应用。--database-url、--data-dir、--log-dir 可覆盖 Settings/.env 默认值，路径按项目现有 Settings 规则解析。多份 checkout 必须指向同一业务数据库、数据根和实际共享锁位置，不能用各自默认目录替代。

## 状态规则

| 已有状态与证据 | 方案 | 保留内容 |
| --- | --- | --- |
| RUNNING，完整成功产物通过审计且符合快照 | COMPLETED | 原领取 token、Worker、SQL 开始时间；从清单恢复真实步数、摘要、summary、结束时间和相对产物键 |
| RUNNING，产物缺失、不完整、损坏或快照不符 | FAILED / WORKER_INTERRUPTED | 实际已记录的开始时间、步数/进度、全部部分文件 |
| PENDING/QUEUED，没有可审计的完整成功 bundle | FAILED / TASK_ABANDONED | 任务 ID、配置/数据快照、去重键、消息 ID、已有文件；不重投 |
| PENDING/QUEUED，却出现可审计的完整成功 bundle | blocked | 保守留待人工调查，不补造领取身份/开始时间，也不抹去成功证据 |
| COMPLETED/FAILED | unchanged | 不重新打开、不修改；不重新审计终态文件，后续下载按 M4 再校验 |
| SQL 行不合法、受控输出路径被链接或 Schema 不匹配 | blocked/error | 不猜测修复、不删库或隐式迁移 |

完整成功不仅是 manifest.json 存在。复用 trainer.artifacts.verify_training_artifacts 检查文件清单/大小/哈希、Adapter 张量与配置、tokenizer、指标和快照一致性；再核对任务 ID、模型/revision、完整 config/runtime、训练数据 SHA-256/大小/行数及已有步数/时间。当前服务只有一个训练数据集，不允许额外 validation_dataset 冒充原任务结果。SQL 未知总步数可以由有效清单恢复，缺清单时不伪造进度。只比对已固定的数据快照，不要求为了恢复终态再下载基础模型或重读原始训练正文。

任一预检项被阻塞时，整次应用不开始写任务。检查通过后逐项短事务更新；若中途出现冲突，已提交项保留，停止后续项，报告 partial 或 blocked。输出路径异常/SQL 损坏等需先调查，不能为了通过工具覆盖目录或清除成功标记。

## 锁交接给 B

A 新增唯一公共原语 backend.app.core.worker_lock.WorkerInstanceLock(log_dir)，固定锁文件 LOG_DIR/worker.lock。B 的 worker/instance_lock.py 已在 Linux 复用它，并接入标准启动及 Celery worker_init/退出钩子。A 正式审查未修改 B 的 Worker 运行代码。

```python
from backend.app.core.worker_lock import WorkerInstanceLock

instance_lock = WorkerInstanceLock(settings.log_dir)
instance_lock.acquire()  # 非阻塞；WorkerLockBusy 必须终止启动，而非只打印日志
# Worker 的整个生命周期持续持有 instance_lock；退出时 release()
```

同一个 handle 的 acquire 可重复调用；同一进程创建第二个 handle 也会竞争。两个启动入口应共用同一 handle，避免自行竞争或只持锁到启动函数返回。禁止删除/替换锁文件；重复进程必须争用同一 inode。原语拒绝链接/硬链接的锁文件，进程退出由 OS 关闭描述符释放锁，锁文件保留。单机/同 LOG_DIR 是前提，锁不探测 API、其他机器、绕过锁的手工训练或全部外部 GPU 程序。

M3-04 已确认路径与原语，本机回归实测标准 python -m worker 和直接 Celery 入口拒绝第二实例；实际消费进程与对账 CLI 互斥也已通过。GPU 训练中断后的恢复仍须另验收。

## 并发、日志和失败语义

--check 使用 SQLite mode=ro，不建表、不迁移、不创建缺失数据库、不主动写输出/日志/锁文件；结构化 JSON 写 stdout，可自行保存。报告 version=1.0.0，包含 mode/state、检查时间、停机声明/取锁事实、items、applied_count 和 audit_log。items 给出 task_id、from_status、to_status、reason、outcome，不输出数据正文、SQL 领取 token 或底层异常文本。未审计到原始正文不表示已完成数据人工审核。

--apply 持锁重新生成方案，不信任旧报告作为写入指令；每项写前再次核验产物，哈希工作在数据库写事务外。BEGIN IMMEDIATE 后重读全行指纹，状态、领取 token、配置、进度等任一变化都会停止该项；UPDATE 继续显式限制原状态/token。该锁配合停机声明防止协作进程写文件，不能防御任意外部进程在核验后恶意改文件。

开始写任务前，先排他创建 0600 的 LOG_DIR/reconciliation-{UUID}.jsonl。依次 flush/fsync plan、每项 intent（含原行 SHA-256）、applied 和最终 result；不更改 Trainer 的日志/metrics.jsonl。日志创建/初始持久化失败时不改任务。数据库提交报错或确认未知时停止，不再把同一任务改为 FAILED；日志在提交后失败也可能返回 uncertain，保留已知计数。应先重新 --check，结合数据库真实状态与审计 intent 判断，不盲目重跑训练。applied_count 是本次确认的更新数，不是所有可能已提交更新的保证。

| state | 含义 / 退出码 |
| --- | --- |
| ready | 仅检查：有候选修改，尚未应用；0 |
| current | 没有需要修改的记录；0 |
| not_initialized | 数据库或任务表尚不存在，未创建；0 |
| applied | 本次全部候选已确认写入；0 |
| blocked | 缺停机声明、锁占用、非法记录/路径、未知 Schema、预检或第一项冲突等；2 |
| partial | 已确认部分更新，遇冲突停止；2 |
| uncertain | 提交/后续日志确认未知；可能已有真实终态，先重新查询；2 |
| error | 读取/权限/审计等异常；保留安全 code，先检查报告和现状；2 |

当前工具不清空 Redis 队列。残留消息之后由 B 的 Worker 通过 claim 拒绝终态，不重复训练。停机声明与取锁不等于消息恰好执行一次，不承诺在线租约、自动恢复或自动重训。

## 验证范围

25 项新增检查、共 283 项 CPU/HTTP 回归通过。覆盖真实 SQLite、共享 CPU 审计器与明确标记的合成 safetensors bundle、状态保护、快照/文件变化、提交回滚/确认丢失、审计写入失败、CLI 和冷导入。真实子进程持锁并领取 SQL 任务时应用被拒绝，受控 os._exit(17) 后可取锁结束遗留任务；该进程没有运行 Celery/Trainer/GPU。

本机业务库只执行 --check，结果 current/items=[]，未应用任何修复。2026-11-03 已补充生产 Celery Worker 的实际锁互斥/停止释放 CPU 检查；GPU 退出/成功产物遗留与重新启动消费仍须在 07 验证。完整记录见 [M3-06 A 侧日志](worklogs/2026-11-02-m3-06-a.md)。
