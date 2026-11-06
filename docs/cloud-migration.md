# WSL 清点、迁移材料与 macOS／云端接续

日期：2026-11-06（Asia/Shanghai）。这是**已清点/打包、Windows 下载中转、Mac/云端待接收**的交接记录，不是云部署成功报告。主提示在根目录 [continue.md](../continue.md)，不再依赖旧聊天。

## 当前状态与清点范围

原机：Ubuntu 26.04.1 / WSL2，x86_64，Python 3.12.15。代码清点起点 `7d5239c2a9a5345dcc754c8bfc8f2874e29d203c`，main 与 origin/main 一致；该提交包括队友 M4 人工清单。迁移工具/提示文档的最终提交另由 Git 及私有 handoff.json 标识。

清点覆盖仓库 tracked/untracked/ignored 数据布局、实际运行进程、项目 `.env`、Python/Node/Redis/Docker 版本、HF 缓存（项目内与 home 重复缓存）、用户 Redis unit、数据库和历史训练/验收产物。未读取/复制 SSH 私钥、AWS/AI agent 凭据，不把主机个人环境当项目依赖。

补查结果：Git stash 为空，另一个 M3 审查 worktree 仅有可清理的失效登记，原临时目录已不存在，没有额外未提交代码可搬。实际 Docker 查询确认 `com.docker.compose.project=llmcloud` 的容器与卷均为 0，没有遗漏的项目 Docker 持久卷；Python 基础解释器路径和这些检查另记入私有 host-inventory.json。

| 组件/内容 | 原机观测 | 处理与云端意义 |
| --- | --- | --- |
| Git 历史/代码/文档/锁文件 | `.git` 约 16 MiB；新文档/工具收尾提交 | GitHub clone；另制完整 code.bundle，排除机器专属 .git/config |
| Python `.venv` | 约 7.1 GiB，3.12.15，training extra | 不复制，云端 `uv sync --locked --extra training`；Mac 只 `uv sync --locked` |
| 基础服务 | FastAPI 0.143.2、uvicorn 0.54.0、SQLAlchemy 2.0.54、Celery 5.6.3、redis Python 6.4.0、Pydantic 2.14.1/settings 2.16.0、safetensors 0.8.0 | 以 uv.lock 重建；CPU 模块不加载训练库 |
| 训练库 | torch 2.9.1+cu128、Transformers 4.57.6、Datasets 4.8.5、PEFT 0.18.1、TRL 0.25.1、Accelerate 1.15.0、HF Hub 0.36.2 | CUDA 包只在 Ubuntu 云运行环境安装；Mac 不装 training extra |
| 本机 GPU/驱动 | RTX 5070，12227 MiB，驱动 621.14；历史 BF16/CUDA 实测 | 不搬硬件/驱动；未来云机需重新核对驱动、CUDA、BF16和显存，不能直接套 WSL 显示驱动流程 |
| Node/npm | 22.23.3/10.9.9，工具在 `~/.local/share/llmcloud-tools` | 每个系统原生安装；frontend/package-lock.json + npm ci 重建，node_modules 约 61 MiB 不复制 |
| Redis 服务 | 7.4.11；项目用户 unit；数据约 28 KiB | 已停用；云端新 broker。原 data/redis 冷备归档，仅取证，不回放队列 |
| Docker/Compose | 29.9.1 / 5.6.0 | 原机已安装不代表应用 Docker 化；compose 只有 Redis，无完整 GPU/API 镜像，未发现 nvidia-ctk |
| 项目内模型缓存 | 999,605,744 普通文件字节，22 文件/9 链接/16 目录，约 954 MiB | 完整 models.tar.gz；9 个固定快照文件离线校验通过，HF_HOME/Hub 层级保持 |
| home HF 缓存 | `~/.cache/huggingface` 约 957 MiB，含同一模型重复权重 | 对照快照 9 文件尺寸、实际权重 SHA 相同；不重复迁移；其他下载中间缓存可重建 |
| uv 下载缓存 | `~/.cache/uv` 约 6.8 GiB | 可重建，不迁移，不与代码环境混为一谈 |
| Node/Redis 安装目录 | `~/.local/share/llmcloud-tools` 约 282 MiB | Linux 二进制不可搬 Mac；云端重装，不打包 |
| Playwright/字体/共享库 | 旧 `/tmp/llmcloud-*` 浏览器目录已不在，home 无浏览器缓存 | 无需保留临时二进制；Mac 不要求浏览器 E2E，云端按锁定 Playwright 和实际系统依赖安装 |
| `.env` 与前端 `.env` | 项目原配置存在；未发现这两份文件含令牌键 | 仅私有归档到 private-config，不自动启用；以示例重建云端值 |
| 项目 Redis 用户 unit | `~/.config/systemd/user/llmcloud-redis.service` | 私有参考备份；原 WorkingDirectory/ExecStart/PATH 是 WSL 路径，云端重建 |
| shell/Docker/Git 网络代理 | 历史代理 `172.24.224.1:7897`，Git 使用 WSL SSH agent/代理的本地配置 | 不迁移代理/agent；新机器按自身网络认证。没有复制私钥/密码/token |
| `.aws/.codex/.agents` | 原仓库存在本机私有配置入口（工具保护目录） | 不属于应用运行所需，不读取/打包；Mac 新 Codex 由自身应用认证 |

### 数据、数据库与实验

- 模型之外的 runtime 快照：399 个普通文件、134 目录、234,288,756 文件字节，含数据/日志与 3 份私有配置。所有选定资产共 580 个条目；逐文件清单在私有 manifest.json，不把原始数据/日志放进公共文档。
- 7 份 SQLite 经 SQLite backup API 快照并逐一 integrity_check=ok：根业务库；M3 原验收/独立审查/解压交接各 1；M4 空会话库；datasets/tasks 迁移前备份各 1。SQLite WAL/SHM 不作为独立恢复输入。
- 根 `data/llmcloud.db`：users=0、datasets=0、training_tasks=0。M3 原验收库：datasets=2、任务=9（4 COMPLETED/5 FAILED）；两份复制审查库相同。**不能把这三份历史快照相加为 27 个新任务，也不合并到业务库。** M4 空会话库同样 0/0/0。
- `data/prepared/format-smoke-v1`：train/validation/test 各 1 条工程格式草稿，以及 provenance/manifest。正式语料尚未人工审核；冻结评测规范继续保留在 docs/data，不能把测试正文拿来微调。
- `data/outputs` 有 10 个任务目录：6 份有成功清单并通过原 CPU 审计，另 4 份失败诊断目录一并保留。6 份成功分别为 `4b455de5…`（3 步）、`5c7d2287…`（1 步）、`82fbb46e…`（2 步）、`95ed33a1…`（1 步）、`992aa53a…`（1 步）、`e54e247f…`（2 步）；不得据此宣称正式效果改善。
- M2-06 重载记录在 data/experiments；M3 原完整 run、A 审查副本、交接目录/ZIP，M4 CPU 证据和空人工会话，全部保存在 runtime 归档。M3 原成功 4 份产物本轮再审计通过。独立 CPU 审计只给 artifacts_verified，不替代原 M2 新进程重载证据。
- `.gitignore` 只保留用户曾明确授权的 M3 固定 review.zip 与 .sha256 特例；本次迁移包/权重/DB/日志不新增 Git 特例。

## 空人工会话关闭与已知缺陷

2026-11-06T09:29:31Z（北京时间 17:29）迁移前检查：人工 run=`84966247-b8e9-4b04-9941-0e412d8c6770`，0 任务、0 数据集，无 PENDING/QUEUED/RUNNING。对该自有会话主进程发 SIGINT 后，原 Worker/Redis/Vite/API 均退出；项目 Redis 用户服务已 `disable --now`，确认 inactive/disabled。没有删除数据，未停止其他项目或主机 Docker。

空会话退出暴露已知缺陷：Uvicorn 先关闭，manual finally 取任务列表失败，report 记录 `failed/ConnectError`，cleanup_errors=[]。保留原报告与独立 migration-stop.json，不改成“人工通过”。修复关闭顺序属于迁移后 M4-07 接续事项；本次只备份和说明，没有混入未验证的训练/Worker 改动。

M3 人工剩余项、M4 自动 GPU/双方人工均待在云端重新组织，旧 localhost:51687 与旧 Unix socket 已失效。M4 01～06/原 M3 GPU 历史结果不受此空会话退出问题推翻，但也不能代替未做的验收。

## 实际交付目录与校验

主交付按用户新指定放在 **`C:\Users\PC\Downloads\LLMCloud-migration-2026-11-06\`**，WSL 访问路径 `/mnt/c/Users/PC/Downloads/LLMCloud-migration-2026-11-06/`。原仓库制备目录 `data/migration/2026-11-06-wsl-to-cloud/` 和仓库外 `/home/highsun/LLMCloud-migration/2026-11-06-wsl-to-cloud/` 也保留。Windows 副本在 WSL 之外；但在 Mac/独立目标接收并校验前，不要清空 Windows 主机。

| 文件 | 字节数（当前数据归档） | SHA-256 |
| --- | ---: | --- |
| runtime.tar.gz | 101653472 | `46ec890f7116013c15a407e40eb89e60d939d32075ebf5febc94d9398a487e2f` |
| models.tar.gz | 796430805 | `a45ca30e258fbfa7317788f00f8673c6791cf74322271bc8b420115120e3ba77` |

同目录还含 manifest.json、restore-verification.json、host-inventory.json、最终 code.bundle、handoff.json、continue.md、RESTORE.md、SHA256SUMS，共 10 个文件。后几项在收尾生成，不循环把代码 bundle 的摘要写回它所包含的 continue.md；以整个目录的最终 SHA256SUMS 校验。文件权限及目录为私有，内含原 `.env` 参考，不公开发布。

已实际完成：普通文件逐项摘要校验、精确目录/链接清单校验、新目录完整解压、固定模型缓存离线检查、7 份还原 DB integrity_check、还原后的 6+4 份成功产物原 CPU 审计。未使用 GPU，未实际上传云端，也未在 macOS 运行。

## 使用迁移工具

`scripts/migration_bundle.py` 仅用 Python 标准库；Python 3.12 可直接运行。build 要求显式 --services-stopped，只支持新的 data/migration 子目录；不自动停止服务，不循环包含自己的包，不备份虚拟环境/个人凭据。DB 通过备份 API 读取，锁 inode/SQLite sidecar 不移植。普通文件读入 tar 时核对源身份/尺寸/mtime，检测期间变化即失败。HF 内部相对链接保留，外部/绝对逃逸链接和特殊文件拒绝。

verify 核对 SHA256SUMS、所有归档成员名称/类型/大小/SHA-256/链接，拒绝重复、缺失和额外成员；restore 先 verify，再以 data filter 解压到不存在的新目录，不覆盖业务库。此校验用于传输完整性，不认证不可信来源，原始摘要应与本仓库记录交叉核对。

```bash
# 以下是模板，先替换实际绝对路径；Mac 不必展开模型。
python3 scripts/migration_bundle.py verify --bundle /ABS/PATH/2026-11-06-wsl-to-cloud
python3 scripts/migration_bundle.py restore --bundle /ABS/PATH/2026-11-06-wsl-to-cloud --target /ABS/PATH/new-empty-restore
```

接收方还需 `git bundle verify /ABS/PATH/code.bundle`；GitHub 不可达时可 `git clone -b main /ABS/PATH/code.bundle LLMCloud`，再将 origin 改回 HTTPS 仓库地址。不是把原 `.git` 直接拷到新系统。

## 实际跨机传输还缺什么

用户已确认云服务器暂未准备；先交 Windows 下载目录，再由用户传到 Mac。完整分步命令见 [Windows→Mac→Ubuntu 恢复](migration-restore.md)，包内 RESTORE.md 是同文离线副本。**当前没有上传云端**。待用户提供目标后，先创建私有持久接收目录，再从持有归档的一端发送完整文件夹。Mac `shasum -a 256 -c SHA256SUMS`、Ubuntu `sha256sum -c SHA256SUMS`，继续运行逐项 verify。不要通过 Git 上传，也不要删本机唯一副本后再想办法找数据。

模板（仅示意，不代表目标已经存在）：

```bash
# WSL → 已确认的云机，cloud-alias 必须由用户配置/提供。
scp -r /home/highsun/LLMCloud-migration/2026-11-06-wsl-to-cloud cloud-alias:~/private-migrations/
# 在实际接收的云机目录内执行：
sha256sum -c SHA256SUMS
```

若先交 Mac，可以用已有的远程文件传输/VS Code 下载/SCP 取走整个目录，放在仓库外的私有备份位置。只需写代码时无需在 Mac 解包约 1 GB 的数据和模型；将包转存云端后保留验证过的备份。

## 云端运行恢复边界

1. 用户确认服务器：Ubuntu/CPU 架构、GPU/显存/驱动、持久盘、目录、SSH/访问方式。现有验证是 WSL RTX 5070 12 GB + torch cu128，不等于新 GPU 已兼容。
2. clone 新 main，校验包、新目录恢复。复制 data/logs 到新的持久根；**排除 data/redis**，Redis 冷备只留历史。根业务库原本为空，历史验收库留原相对位置，不混入业务任务。
3. `.env` 从示例重建，持久 DATA_DIR/LOG_DIR/HF_HOME/HF_HUB_CACHE 和 SQLite URL 指向目标；清除 WSL 代理/agent/目录和旧 URL；原 private-config 仅作参考。
4. Ubuntu `uv sync --locked --extra training`、npm ci/build、重建 Redis 和进程服务。GPU 运行命令保留 training extra，API 不因安装了训练依赖就加载模型。Mac 不执行这些全栈步骤。
5. 模型离线 check（明确 HF_HOME/Hub 路径）→ 数据库显式 --check → 用户在云端运行 Linux CPU/HTTP 检查 → 独占 GPU 验证。根据用户反馈修复，保留真实命令/版本/日志/证据。
6. 先解决 M4 人工入口关闭问题，再执行独立新 GPU/人工验收；推理、正式实验、完整容器化和课程交付继续按未完成范围推进。运行位置提前迁移不冒充这些工作已经交付。

完整可复制给新 Codex 的操作约束、模块契约、Mac 小测和反馈格式均在 [continue.md](../continue.md)。
