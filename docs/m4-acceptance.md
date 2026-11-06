# M4-07 真实服务联合验收安排

更新：2026-11-06。**A 侧专用工具及非 GPU 检查已交付；尚未执行 M4-07 真实 GPU/双方人工验收。** `ef1fe06` 的 M4-01 B 核对、04a/04/05 和 06 已由 A 审查、在 Linux 本机复跑并快进合入；依据见 [审查日志](worklogs/2026-11-06-m4-b-review.md)。本次工具交付见 [A 日志](worklogs/2026-11-06-m4-07-a-tools.md)，下一步在干净提交上验证真实 Worker/Trainer 的文件生产并共同操作。

入口：[完整计划](m4-development-plan.md)、[正式契约](api/task-observability.md)、[M3 剩余人工项](m3-acceptance.md#当前还差哪一步)。M5 在线推理、部署和正式效果实验仍另行实施。

## 当前事实与交付门槛

M4-06 使用生产 API/SQL/文件读取/ZIP 响应，输入为明确的 CPU 事件与合成 bundle；它证明实际接口和浏览器对齐，不证明 GPU 训练效果。M3 原真实 GPU 证据也不能替代 M4 新页面和下载能力的实际操作。

M4-07 至少交付：一次新上传到真实训练/页面观测/下载的完整记录、两个真实任务的串行证据、下载包解压后原 CPU 审计、双方各自操作/复核日志。M3 同场人工剩余项单独列出，不能只凭 A 自动脚本或 B 异步看图勾选双方同步操作。

## 可以并行准备的工作

| 负责人 | 现在的明确任务 | 交付物/边界 |
| --- | --- | --- |
| A（当前侧） | 专用工具/非 GPU 检查已交付；接下来在干净提交上准备实际服务并执行真实 GPU 运行 | [Python 编排](../scripts/check_m4_acceptance.py)、[浏览器入口](../scripts/check_m4_browser.mjs)、[CPU 证据检查](../scripts/m4_acceptance_support.py)。复用 M3 服务生命周期及生产 API/Worker/Trainer，不执行旧 M3 故障场景、不新增产品测试路由。工具已用明确 CPU 替身检查，真实 GPU 尚未运行。 |
| B（队友） | 将下表转为逐步人工操作清单，检查其浏览器能访问 A 的服务或安排共享屏幕；准备桌面/390px 检查与独立记录 | 同步最新 main，维护自己的人工检查清单/运行后 B 日志；无需重写 04/05、再跑一遍整个 CPU 故障矩阵，或在 Windows 安装 GPU 训练环境。准备过程中发现问题给出操作、task_id/request_id 与差异。 |
| A+B | 约定一个共用 GPU/服务时段，实际完成人工端到端流程 | 此步存在真实合作依赖，不能以互相独立开发代替。尚未约定具体日期/时间；先按原 A 1+B 1 人时预算安排，工具准备若超出则登记并使用缓冲，不削减验收。 |

文件分工沿用：A 主改验收编排/共享记录，B 主改必要前端修复及独立日志。新增接口/字段若有问题先共同核对契约；没有阻塞时不扩大到推理、SSE、量化或新基础设施。

## A 开始真实运行前的条件

- 双方同步已审查的 main；工具/配置先提交，运行时记录完整提交和 working_tree_dirty。不能将带未审查修复的运行记为已冻结基线。
- 固定 Qwen2.5-0.5B-Instruct 和 revision `7ae557604adf67be50417f59c2c2f167def9a775`；按原缓存检查工具校验完整离线快照，不临时换模型或下载回退。
- 为本轮创建全新 DATA_DIR/SQLite/私有 Redis 队列、结果后端及文件目录；证据默认放忽略的 `data/acceptance/m4-07/{run_id}/`。不接触业务 DB/队列，不覆盖 M3 运行或两个已获准入 Git 的证据文件。
- 实际 Worker 与本机其他 GPU 工作共用既有 LOG_DIR/worker.lock；先确认其他手工训练/重载不并发。只启动一台并发 1 的生产 Worker，不通过持 GPU 锁的 API 阻塞读取/下载。
- 内部 max_steps 可从 20～40 步开始，logging_steps=1；公开 API 请求不新增内部字段。至少取得 5 个真实 train 点并跨过两轮实际轮询；太快则增加真实工作量并记录，不延时或补点。服务没有验证集输入，不要求或伪造 eval；双系列由已通过的受控用例覆盖。
- 验收工具必须显式 opt-in GPU，能清理自己启动的进程并保留失败证据；运行命令见下节。原 `check_m3_acceptance.py --gpu` 默认两步及旧页面检查不是本阶段替代入口。

## 已交付入口与运行方式

先在根目录安装前端依赖和 Chromium（Linux 缺浏览器系统库时按既有环境说明安装），再运行 CPU 预检。单独使用 `.venv-cpu`，避免同步基础依赖时裁剪已有训练环境：

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium
cd ..
UV_PROJECT_ENVIRONMENT=.venv-cpu uv run --locked python scripts/check_m4_acceptance.py --check
```

`--check` 实际启动/关闭一个空白 Chromium 页面，检查 node/npm/redis-server 命令是否存在，报告训练包是否可发现；不启动 API/Redis/Worker，不检查缓存或 CUDA，不代表真实验收通过。浏览器安装路径、共享库、字体若由环境提供，沿用 `PLAYWRIGHT_BROWSERS_PATH`、`LD_LIBRARY_PATH`、`FONTCONFIG_FILE`，工具不内置本机临时目录。

工具/配置提交并确认独占 GPU 后，由 A 执行**尚未执行**的自动部分：

```bash
uv run --locked --extra training python scripts/check_m4_acceptance.py --gpu --max-steps 40 --timeout 600
```

默认建立 `data/acceptance/m4-07/{新UUID}`；`--run-dir` 仅允许该目录的全新 UUID 直接子目录，拒绝复用、越界及链接根目录。固定 revision 和 BF16，训练包只检查可发现性，真实执行仍由生产 Worker 导入。预先校验离线模型缓存，API 和 Worker 同时使用 40 步内部上限，公开请求只提交原有 config 字段。两条消息经浏览器真实提交、进入私有 Redis 后才启动唯一生产 Worker；这不是训练中暂停或伪造指标。

自动入口记录提交/锁文件摘要、服务 PID/队列/URL、请求与任务 ID、数据摘要、SQL 快照、原日志、HTTP 指标/日志、截图/trace、浏览器下载及解压审计。自动检查包括两个任务 SQL 区间串行、至少五个真实 train 点、跨两轮活指标请求、终态 UI/HTTP/原指标一致、旧任务下载在另一任务真实优化器事件之间完成、下载工作区清空与下一份下载成功。太快则报告失败，增加真实 `--max-steps`（上限 200）再用新目录运行。成功状态只写 `automated_passed`，M3/M4 的人工验收字段始终 `pending`。

双方已约好时段后，另开一个**新的**实际人工会话，不把自动页面操作算作 B 的操作：

```bash
uv run --locked --extra training python scripts/check_m4_acceptance.py --gpu --manual --max-steps 40 --hold-seconds 1800
```

终端及 report.json 输出本轮 loopback 页面 URL，A 可通过现有远程开发端口转发/共享屏幕与 B 操作；工具不开放公网监听。B 新上传并提交两个任务，明确设置 `logging_steps=1`，建议 `gradient_accumulation_steps=1`、`max_seq_length=256`，按下表操作。原始下载保存在 B 浏览器选择的位置，双方保留 ZIP/SHA-256 并按既有下载产物说明解压、运行 `scripts/check_training_artifacts.py` 原 CPU 审计；A 可调用 `scripts.m4_acceptance_support.audit_download` 与本轮源目录逐文件对比。人工会话到时会保留真实任务状态和已完成产物审计，关闭自己的 Worker/API/Vite/Redis；`manual_session_closed_pending_review` 仅表示会话已关闭，**不表示双方验收通过**。关闭前确认任务完成；若到时或 Ctrl+C 尚有 RUNNING，保留证据，停机后按既有对账流程处理，不自动重投或修状态。

下载取消、下载中切任务、隐藏/恢复、日志历史滚动及双方同步操作仍由人工清单执行；自动脚本没有声称覆盖这些交互。CPU 合成输入的机器人自检见 A 日志，与真正 `--gpu` 的报告分开保存，不生成新的 GPU/人工通过记录。

## 共同操作与通过条件

| 顺序 | B 在页面实际操作 | A 同时核对/留证 |
| --- | --- | --- |
| 1 新上传与提交 | 上传本轮工程样例、配置并连续提交两个不同任务，观察排队 | 真实 HTTP → Redis → 生产 Worker，无 Publisher/执行替身或 `__test__` 控制；保存数据哈希、参数、task_id 与 UTC 时间。草稿标为未审核，冻结题不参与。 |
| 2 活训练观测 | 查看至少 5 个新指标点、阶段日志；隐藏后恢复、切任务、刷新详情 | 对照原 metrics.jsonl 的 kind/step/loss、字节游标和任务日志；加载时无 Loss 不补点，两个任务的 GPU 训练区间不重叠。 |
| 3 终态与下载 | 确认最后 train Loss、最终日志；100% RUNNING 不提前下载，COMPLETED 后下载 | SQL 提交晚于保存/审计，页面终态后补完最后指标/日志；保存实际 ZIP 名称、长度和 SHA-256，与源 manifest/文件摘要比较。 |
| 4 下载复核与取消 | 下载已完成任务时切任务/取消；再主动重新下载；在另一个任务实际训练时读取旧完成任务产物 | 不保存旧任务的迟到文件，不污染新状态；服务清理临时区/槽位，读取/下载不争抢 GPU。先保留一份有效下载，再验证取消；如需延迟注入须明确标记，不能称为自然断连。 |
| 5 原功能与窄屏 | 原任务查询、刷新恢复、筛选/分页、关闭详情；390px 查看曲线/日志/下载提示 | 检查无页面整体横向溢出、日志以文本显示且历史滚动不被强制拉底；原 M1/M3 行为不回退。 |

失败/日志未产出、游标重置、坏完整行、忙/大小/存储错误等已有 M4-06 实际文件 CPU 证据。只有真实联调出现差异才重测对应场景，不为本次安排重跑 M3 的全部九项故障注入，也不将合成故障称为 GPU 故障。

## 证据与收口

A 记录 run_id、完整提交、代码是否干净、revision/配置/数据摘要、实际服务与 Worker/Redis 身份、任务 UTC 区间、原指标/日志和下载审计结果，保留可读桌面/手机截图与 trace。B 另写实际人工操作/观察结论，明确自己操作了哪些步骤，哪些只是异步复核；日志文件名可采用 `YYYY-MM-DD-m4-07-a.md` / `-b.md`，运行前不创建假的通过记录。

可共用一轮服务，但报告分开列 M3 同步人工流程和 M4 新能力通过项。两方确认、无未解释阻塞后才更新 AGENTS/README/计划/记忆及阶段勾选；结果不要求 Loss 下降、回答改变或效果提升。原始数据、权重、DB、日志、ZIP、trace 默认不提交 Git，公开摘要/工作日志可提交；M3 两个固定文件的特例不自动扩大。

M4-07 通过后再进入 M5：先定推理 API/Worker 与 GPU 互斥契约，再并行实现后端执行和前端适配，随后推进效果实验/部署。当前没有实现或启动这些后续内容。
