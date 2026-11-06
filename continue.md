# LLMCloud：交给 macOS 上新 Codex 的完整接续提示

> 用户：在 macOS clone 本仓库后，让新 Codex **完整阅读本文件并按它接续**。本文件替代旧聊天的项目上下文。更新日期：2026-11-06，北京时间。机器清点、迁移包与限制见 [迁移清单](docs/cloud-migration.md)。

## 1. 你现在的任务与工作方式

你是 LLMCloud 的接续开发助手。用户将删除原 WSL 工作目录和旧聊天；不要要求用户重新解释已记录的背景。先读本文、AGENTS.md 和当前 Git 状态，再核对实际代码/日志，避免把历史规划当成果。

用户刚确认的长期方式：

- **macOS 只做代码编辑、静态检查及小范围 CPU 单元测试。** 不在 Mac 训练，不使用 MPS 替代 CUDA，不要求本地 Redis/Docker/GPU/整套后端/Playwright 来验收运行能力。
- **实际 API、Redis、SQLite/文件、GPU Worker、模型、训练、浏览器端到端验收、部署均放在云端 Ubuntu + NVIDIA CUDA。** 不再依赖 WSL/Windows/RTX 5070，不做“云端 CPU + 本地 GPU”混合方案。
- 用户提供云服务器资料时，你先给可审查的配置/命令；用户在服务器执行、返回结果和日志，你据此改代码、提交同步，再指导云端验证。没有新授权不要自行购买云资源、开放公网服务、长时间跑训练或声称已远端部署。
- **GitHub Actions workflow 已按用户明确要求删除，提交 bb7e8ac；不恢复、不新建、不启动、不重跑。** 本地小测和用户反馈的云端检查替代它。
- 所有开发/部署沟通使用中文。合理独立推进已授权的工作，不为常规可逆操作反复询问；缺少云地址/凭据/硬件等真实必要信息时直说缺口。

当前云服务器地址、用户名/端口、Ubuntu/GPU/驱动、持久磁盘、目标目录和接收端**均未提供**。迁移包已在原 WSL 制备并做恢复检查，**没有实际上传云端**。请先问用户迁移包是否已经离开原主机、在哪里，不能假定 clone 包含它。

## 2. 项目与团队

《云计算技术及应用》课程项目，名称 LLMCloud：基于云端异步任务调度的大语言模型参数高效微调平台。目标闭环：上传 instruction JSONL → 选模型/LoRA 参数 → Redis 排队 → 单 GPU Worker 真实微调 → SQL 状态/原指标日志 → 下载 Adapter → 测试推理。

2 人，每人每周 6–8 小时，原规划 8 周。A 是当前用户，负责后端、SQL、调度、公共契约、部署；B 是队友，已交付 Vue 前端和 Worker。历史 M2 虽计划分工不同，实际多数 Trainer/数据处理/验收由 A 侧交付，不能把计划当 B 的贡献记录。保留双方代码和各自日志。

仓库：`https://github.com/Highsun/LLMCloud.git`，共享主线 `main`。B 分支 `feature/m4-observability-ui`；另有历史 M3 分支。新机器优先 HTTPS clone；若仓库访问需要认证，使用新机器自身的 GitHub 登录/SSH 身份，不在聊天发送凭据。**不要复制原 .git/config 中绑定 WSL 代理/SSH agent 的传输配置**。Git 作者若未配置，使用用户已提供的仓库身份 `Highsun <1339687616@qq.com>`，仅配置本仓库。

## 3. 接手时按顺序执行

1. `git status --short --branch`、`git fetch origin`，比较所有相关分支，阅读队友新增提交和 `docs/worklogs/`；保留任何本地未提交修改。不要强推或改写共享历史。
2. 阅读 [AGENTS.md](AGENTS.md)、[README](README.md)、[项目记忆](docs/project-memory.md)、[总计划](docs/project-plan.md)、[架构](docs/architecture.md)、[需求](docs/requirements.md)。环境文档里的 WSL 配置是历史事实，新规则以本文和迁移清单为准。
3. 阅读 [M4 计划](docs/m4-development-plan.md)、[M4 联合验收](docs/m4-acceptance.md)、[B 人工清单](docs/testing/m4-07-b-manual-checklist.md)、[A 工具日志](docs/worklogs/2026-11-06-m4-07-a-tools.md)、[B 准备日志](docs/worklogs/2026-11-06-m4-07-b-preparation.md)、[本轮迁移日志](docs/worklogs/2026-11-06-macos-cloud-handoff.md)。
4. 检查 macOS 基础工具/Python 3.12/uv/Node，按下节只建 CPU 开发环境，跑有限检查。不要启动 GPU 人工入口或全量平台集成检查。
5. 输出简短接手报告：当前 commit/工作区、已完成与剩余、迁移包是否可读/校验、Mac 小测实际结果、云端还缺什么。等待用户提供云服务器参数后再组织实际运行。

若旧主机已无法访问、迁移包也没有交接，明确指出哪些本地证据/产物无法恢复；代码、模型可重建与证据已保全是不同事实，不得编造恢复成功。

## 4. macOS 从零导入

先确保 Git、uv、Python 3.12 与满足 `frontend/.node-version`/package engines 的 Node/npm 可用；缺工具时给该 Mac 架构对应的安装办法，不抄 Linux 二进制或 WSL PATH。

```bash
git clone https://github.com/Highsun/LLMCloud.git
cd LLMCloud
git fetch origin
git status --short --branch
uv python install 3.12
uv sync --locked
```

这只装基础 Python/开发依赖。**Mac 不加 `--extra training`，不运行 `check_environment.py --gpu` 或 `check_gpu.py`。** 原 `.venv` 是约 7.1 GiB 的 Linux CUDA 环境，不能迁移到 macOS。现有 `pyproject.toml` 的 cu128 index 仅匹配 Linux/Windows，Mac 不需要修改锁文件来“修复 CUDA”。依赖只维护 pyproject.toml 与 uv.lock，requirements 由脚本导出，不能手改。

可执行的小范围检查（代码改动后只运行相关项；不要求每次全部重复）：

```bash
uv run --locked python -m compileall -q backend trainer worker scripts
uv run --locked python -m unittest discover -s tests -p test_training_contract.py
uv run --locked python -m unittest discover -s tests -p test_task_contract.py
uv run --locked python -m unittest discover -s tests -p test_observability_contract.py
uv run --locked python -m unittest discover -s tests -p test_migration_bundle.py
uv run --locked python scripts/export_dataset_contract.py --check
uv run --locked python scripts/export_training_contract.py --check
uv run --locked python scripts/export_task_contract.py --check
uv run --locked python scripts/export_task_openapi.py --check
uv run --locked python scripts/export_observability_contract.py --check
```

前端按需 `cd frontend && npm ci`，然后静态构建 `npm run build`，或少量控制器测试：

```bash
node --test tests/task-submission.test.mjs tests/task-observability.test.mjs tests/task-download.test.mjs
```

不要为了让全部 Linux 文件/HTTP/GPU 测试在 Mac 上通过而放宽 NOFOLLOW/目录 fd/硬链接/哈希检查，或替换为静默失败。macOS 平台兼容性本轮未实际验证；小测出错先判断平台和依赖，保留输出，实际运行结论交给 Ubuntu。`check_environment.py` 是旧 WSL 全栈检查，不是 Mac 的导入门槛。

## 5. 已完成的真实能力

| 阶段 | 已交付 | 仍未完成/不得误认 |
| --- | --- | --- |
| M0/M1 | uv 环境/骨架；JSONL 共享扫描器；上传/列表/详情；统一错误；数据集前端；故障检查；可复现划分与 12 道冻结题规范 | 正式语料人工编写/审核仍待做 |
| M2 | 固定模型缓存；真实 chat template/监督标签/截断；单 GPU LoRA；flush 同源指标/回调；Adapter/tokenizer/config/manifest 保存；独立 CPU 审计；新进程重载工程验收 | 不是正式效果实验；不保证输出改变或质量提高 |
| M3 | SQL/显式迁移、任务 HTTP/幂等、真实 Publisher、单 Worker/实例锁、前端任务流程、离线对账；A 实际 GPU 9 场景、B 异步复核及 A 审查通过 | 双方新上传到实际 GPU 完成的同步人工流程仍待验收 |
| M4-01～06 | 指标/日志 GET、受控 ZIP 下载；曲线/游标/终态补拉/日志/下载取消与任务身份；B 实际 CPU HTTP/浏览器回归已审查合入 | CPU 合成 bundle 不能冒充 GPU 下载验收 |
| M4-07 | A 专用 GPU/人工工具；B 人工清单；2026-11-06 开过空人工会话 | 没上传/提交任务，迁移前已停止；A 专用自动 GPU 也尚未执行，M4 不收口 |
| M5 | 计划、既有禁用推理页面和未来路线 | 在线推理、正式效果实验、完整容器/生产部署、报告/答辩尚待实施 |

前端与后端**已经接通真实接口**，不要重复重做 M1/M3/M4 页面。当前 `compose.yaml` 只有 Redis，仓库没有完整 API/GPU 镜像或生产部署栈；Docker 安装过不代表平台已 Docker 化。此次提前迁移是资源位置调整，不等于 M5 部署验收完成。

## 6. 必须延续的技术契约

- Python 3.12、uv、FastAPI、SQLAlchemy/SQLite、Celery/Redis、Vue3/Vite、HF/PyTorch/PEFT/TRL；单用户、单机云服务器、单 GPU。先 0.5B，不引入 Kubernetes、多 GPU、量化或 7B。
- 模型 `Qwen/Qwen2.5-0.5B-Instruct`；model/tokenizer revision 同为 **`7ae557604adf67be50417f59c2c2f167def9a775`**。从校验后的 snapshot 加载，local_files_only=true；不能只看缓存目录存在，不能静默回退联网/换 revision。
- API 不加载 GPU 模型，不直接训练；Worker 独占计算。`TrainRequest → train(request, on_progress) → TrainResult`；Trainer 不依赖 FastAPI/Celery/SQL。CPU Schema/产物审计不导入 torch/numpy/HF。
- Trainer 的 MetricWriter 唯一写 `metrics.jsonl` 并 flush 后回调；step 是优化器更新步，kind 区分 train/eval，不伪造加载期 Loss，不二次写指标。
- 数据上传格式校验与训练共用 DatasetScanner/InstructionRecord。真实 Qwen 模板无 generation 标记，回答监督用完整序列字符偏移；不盲用 assistant_only_loss、不覆盖 labels、不手动 shift。右截断后无有效回答即失败，padding=-100。
- DATA_DIR 下保存相对键；数据集不可变，`datasets/{UUID}/train.jsonl`。客户端不能传服务端路径/哈希/归属。本机绝对路径不能写入公开响应。
- SQL 是任务业务来源；状态 PENDING/QUEUED/RUNNING/COMPLETED/FAILED；领取 token 条件更新。完成写入确认丢失时读真实状态，不把已保存成功覆盖成 FAILED。
- 派发 not_sent/unknown 不同；503 持久化 task_id/Location，unknown 不自动重投；HTTP 幂等键和消息重复领取是两层保护。
- Worker 与对账使用同一个 `LOG_DIR/worker.lock`；不删除/替换锁文件。API 读取/下载不获取 GPU 锁。云端新建自己的锁 inode，旧锁不迁移。
- 旧数据库先 migrate_datasets.py / migrate_tasks.py 的 `--check`，停 API/Worker 后显式 `--apply`；不删库、不拿 create_all 替代迁移、不补造归属/revision。离线对账默认 `--check`，应用需停服务+实例锁，不重投任务。
- 观测按 source_id/字节 cursor/offset，保留同 step 的 train/eval；终态补尾页/最终日志。日志有限安全投影，不转发共享 stdout；下载需 SQL COMPLETED/固定快照/清单哈希/原 CPU 审计一致，独立临时目录、限量、完整 body/取消清理。前端捕获任务 ID，旧请求不能污染新任务。
- 冻结题不用于训练/调参；当前草稿 review_status 为 unknown/draft_unreviewed，不能自动改 reviewed。独立产物审计通过不等于新进程重载/生成/效果评测通过。

细节以对应正式文档和代码类型为准：[训练](docs/contracts/training.md)、[任务](docs/contracts/tasks.md)、[任务 API](docs/api/tasks.md)、[观测](docs/api/task-observability.md)、[Worker](docs/worker.md)、[对账](docs/task-reconciliation.md)。字段/默认值/上限/错误变化同笔更新 Schema/契约/运行时 OpenAPI/样例，导出文件不手改。

## 7. Git 之外的资产：不能遗漏

私有迁移目录名 **`2026-11-06-wsl-to-cloud`**。生成位置为原仓库 `data/migration/2026-11-06-wsl-to-cloud/`，本轮收尾另复制到仓库外 `/home/highsun/LLMCloud-migration/2026-11-06-wsl-to-cloud/`，供删除仓库后保留。**这两处仍在原 WSL，不代表已离开本地主机。先确认实际副本存在和 SHA256SUMS 完整。**

| 文件 | 内容 | 迁移策略 |
| --- | --- | --- |
| `runtime.tar.gz` | 全部原 data（除 models/迁移包自身）、logs（除机器锁）；7 份 SQLite 一致快照；prepared/outputs/实验/全部验收证据；私有 `.env`/旧 Redis unit 备份 | 必须另行私下交接，不能从 clone 恢复全部内容 |
| `models.tar.gz` | 完整项目 HF_HOME：固定快照/blob/清单、9 条相对链接和 Accelerate 配置 | 推荐直送云端；Mac 不需要展开；也可在云端按固定 revision 重新 prepare |
| `manifest.json` | 580 条目录/文件/链接清单，每个普通文件 SHA-256、7 份 DB 检查与排除说明 | 用脚本逐项校验，不作为训练成功证明 |
| `code.bundle` | 收尾时导出的完整 Git refs/历史，包含本次 continue.md/工具/文档 | 离线代码兜底；正常优先 clone GitHub 最新 main |
| `handoff.json` / `host-inventory.json` / `SHA256SUMS` | 收尾 commit/状态、原机软件与数据盘点、所有顶层交付文件摘要 | 跟整个迁移目录一同交接，勿单发 tar 而丢清单 |

两个数据归档已生成，固定摘要可在仓库中交叉核对：

```text
46ec890f7116013c15a407e40eb89e60d939d32075ebf5febc94d9398a487e2f  runtime.tar.gz
a45ca30e258fbfa7317788f00f8673c6791cf74322271bc8b420115120e3ba77  models.tar.gz
```

归档约 898 MB 十进制（不含代码 bundle 等小文件），包含私有数据和原环境配置，不上传 Git/公开网盘。SSH/AWS/AI agent 凭据、原 .git/config、Linux .venv、node_modules、uv 下载缓存、系统二进制与 Docker 镜像不随包迁移；依赖全部重建。原 `~/.cache/huggingface` 有一份基础模型重复缓存，已确认权重 SHA 相同，无需再搬一份。

**只有 GitHub 中那两个固定 M3 review.zip/.sha256 已获准作为特例提交；不因此扩大其他数据/权重/日志/迁移包的入 Git 范围。**

## 8. 云端接收与恢复：资料齐备后才执行

先向用户收集：SSH alias/地址/端口/用户名（不在聊天索取私钥/密码）、Ubuntu/CPU 架构、GPU/显存/驱动、持久磁盘容量和挂载点、目标目录、数据包保存位置与访问方式。云端根目录示例 `/srv/llmcloud` 是占位；不要硬编码成用户实际路径或未经授权 sudo 建目录。

由持有迁移包的一端将**整个目录**经已有 SSH/scp/rsync 发往云端私有持久目录。先校验：Mac 用 `shasum -a 256 -c SHA256SUMS`，Ubuntu 用 `sha256sum -c SHA256SUMS`。不要清空旧机器，直到目标端核对成功。

在 Ubuntu clone 最新代码后执行模板（将占位替换为实际绝对路径）：

```bash
python3 scripts/migration_bundle.py verify --bundle /ABS/PATH/2026-11-06-wsl-to-cloud
python3 scripts/migration_bundle.py restore --bundle /ABS/PATH/2026-11-06-wsl-to-cloud --target /ABS/PATH/new-empty-restore
```

restore 只写**不存在的新目录**，先逐项摘要/链接核对，后安全解压；拒绝覆盖现有业务目录。恢复后的 `data/` 与 `logs/` 保持原相对布局。在全新云 checkout、服务停止时再把它们复制到所选 DATA_DIR/LOG_DIR；**`data/redis/` 只作历史取证，不接入新 broker、不直接回放旧 AOF，不自动重投任务**。业务根库本来是空库，M3 隔离验收库与输出是历史证据，不能合并伪装成业务记录。

`private-config/backend.env`、`frontend.env`、`wsl-redis-user.service` 仅是私有参考，**不要直接启用**。从当前 `.env.example` 和 `frontend/.env.example` 创建云端配置：重写 DATA_DIR/LOG_DIR/HF_HOME/HF_HUB_CACHE/SQLite URL、Redis URL/队列、前端代理/CORS。清除 WSL 代理 `172.24.224.1:7897`、旧 home 路径、原服务端口、旧临时 Unix socket。云端新建 SSH/Git/服务配置，不复制原 SSH agent 或令牌。

然后在 Ubuntu 的正确目录同步运行依赖（命令由用户执行反馈）：

```bash
uv sync --locked --extra training
uv run --locked --extra training python scripts/prepare_model.py check --revision 7ae557604adf67be50417f59c2c2f167def9a775
```

`HF_HOME` 与 `HF_HUB_CACHE` 不同；显式 HF_HOME 不会被改 DATA_DIR 自动覆盖。没有恢复模型包时，用 `prepare_model.py prepare --revision <同一完整revision>` 明确联网重建，再离线 check。本机已验证 torch 2.9.1+cu128，云端须由用户确认 NVIDIA 驱动/CUDA 实际可用，不照抄 WSL 驱动安装法，不在 Mac 装 CUDA。

云端 API 与 Worker 可先采用同一个 uv training 环境，所有运行命令显式保留 `--extra training` 防止误裁剪；API 仍不导入/加载 GPU 模型。GPU Worker 正式入口是 `uv run --locked --extra training python -m worker`。Redis 可原生重建或使用现有 Redis-only compose，二者只选一个；不公开 Redis 6379。API 开发脚本自带 --reload，不能直接称为生产部署完成。前端 build/静态服务、反代/受控访问、进程守护和持久化需按实际服务器再完成。

Mac 只编辑代码，经 Git 同步到云端；浏览器可经受控 SSH 转发访问云端服务。GPU 调用、全套 Python/Linux HTTP/浏览器/训练检查由用户在云端运行并返回记录。提交与运行基线冻结，真实 GPU 期间不要改 tracked 文件或 merge，避免清单中的 dirty/commit 不一致。

## 9. 已知问题及下一步优先级

1. **先完成迁移包在旧主机之外的接收和校验。** 只有 clone，不足以保全历史数据/证据；服务器未提供，不宣称已部署。
2. 原 M4 人工会话 `84966247-b8e9-4b04-9941-0e412d8c6770`，基线 `7d5239c2a9a5345dcc754c8bfc8f2874e29d203c`，原端口 51687 **已停止且不可再使用**。迁移时确认 0 数据集/0 任务、无活跃 GPU 任务，随后停止其进程并停用 `llmcloud-redis.service` 自启；没有删数据。
3. **人工入口关闭顺序有已知缺陷**：SIGINT 使内嵌 Uvicorn 先退出，`manual()` 的 finally 在读取任务时 `ConnectError`。原 report.status=failed / error_type=ConnectError / cleanup_errors=[]；不是训练失败，也不是人工通过。原报告不改写，另有 `migration-stop.json` 证明空会话状态。后续先修复“关闭前仍可取快照、取消也完成清理”的生命周期并做针对性检查，再在云端重开新的人工会话；不能用旧端口或给旧报告改 passed。
4. 迁移后先由用户在 Ubuntu 验证版本/缓存/DB/CPU 文件接口，再独占 GPU 执行真实运行。M4-07 A 专用自动检查与双方同步人工均未完成；后续用户授权的 GPU 工作在云端完成。B 按既有 18 步清单实际操作，A 同时核对原文件/SQL/ZIP；异步看图与真实人工分别记。
5. 先收口 M3 人工剩余项和 M4-07；再规划/实现 M5 在线推理 API/Worker 的 GPU 互斥、前端测试推理、正式数据/效果实验及部署/课程材料。云环境基础运行可提前准备，但不勾选未实现的 M5 功能。

## 10. 运行反馈与协作要求

每次开发前、独立部分完成后、提交/推送前 fetch，阅读队友新日志/改动。落后且工作区干净则 ff-only；分叉先保留本次提交再正常 merge，逐项解决并验证。远端不通写“尚未确认”，不写“无更新”。不强推、不丢他人修改。每项交付写独立工作日志、更新共享索引/状态；不改旧日志伪造后续结果。

给用户的云端操作应按短步骤分批，每批说明机器/目录/环境、精确命令、预期结构及要返回的输出。收到结果后区分“用户返回”“本地验证”“尚未验证”，不要猜测试通过。出错先保留现场和最小必要诊断，不清空数据库/缓存或重新训练掩盖问题。

建议每批反馈包含：完整 code_commit、git status、命令/退出码、UTC、Python/uv/Node/GPU 版本、run_id/task_id/request_id、相对证据目录、服务 PID/日志末尾、必要截图与 SHA-256。不要让用户发私钥、访问令牌或全量环境变量；配置敏感值打码。原始日志、DB、数据、模型、ZIP、trace、.env 和迁移包默认不入 Git。

**接手后的第一条回应请汇报实际接手结果及云端资料缺口，不直接训练，不恢复 Actions，不假定本次迁移已经跨机完成。**
