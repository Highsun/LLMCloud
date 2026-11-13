# RTX 3060 Laptop 本地测试准备与持续交接

> 2026-11-13发布接续：[队友阅读总览](../testing/laptop-3060-handoff-2026-11-13.md)。用户已授权本次提交/推送；历史日志的“未授权/未提交”对应当时阶段，不改写原测试记录。

日期：2026-11-12（Asia/Shanghai）。状态：L0～L3、40步基础流程及200步人工补测已核对归档；120条/30族语料草稿已编写并通过原生数据/tokenizer检查，待人工审核。专用自动报告/严格剩余交互证据与双方联合验收仍pending。说明/小型证据在D，运行产物及语料留E。

## 用户要求和边界

用户要求按基础自动检查、模型检查、小训练、平台端到端逐步推进，每步提醒发送对应测试结果，在 D 盘项目中写测试说明和结果，供后续与队友核对。本轮本机测试是最新明确授权，不沿用仅云端运行的历史限制来阻止这项工作。

只新增本轮自有说明/日志/执行现有检查的脚本；未改业务代码、共享 Schema/契约/依赖、测试实现、迁移、部署或历史验收。M3/M4 共同验收与云部署不据此收口。没有提交/推送授权。

## 起点与同步

D 盘工作区起点干净，分支 feature/m4-observability-ui，HEAD=9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca，领先自身远端功能分支 3 次提交。本轮 git fetch origin 成功，HEAD...origin/main=0/0，没有需要合并的新主线提交。

已读本机/仓库 AGENTS、总计划、工作日志索引、B 人工准备记录和现有测试入口。E 盘已有同一 main 的 Windows 克隆；用户在安装于 E 盘的 Ubuntu-22.04 内完成 /home/l7/LLMCloud 克隆，origin 已改回 GitHub。运行副本的实际基线由每次测试 metadata 再采集。

## 已有用户回传与本轮交付

用户回传 uv 0.13.7、Python 3.12.16、基础 44 包安装和训练 52 包镜像安装（后者准备耗时 80m 43s），最终按锁文件补齐 torch 2.9.1+cu128。check_gpu.py 回传 RTX 3060 Laptop GPU、CUDA runtime 12.8、计算能力 (8, 6)、前向/反向通过。这些是用户提供的结果，不冒充助手已重跑，也不记为 Qwen/真实训练/平台通过；当时完整原始日志文件未留存。

新增：

- [本地测试说明/结果表](../testing/laptop-3060-local-validation.md)：基线、证据来源、L0～L4 门槛、用户回传清单及待测状态。
- [CPU 日志脚本](../testing/laptop-3060-cpu.sh)：运行既有 unittest 和五项契约检查，离线保留 training extra，限制 GPU/模型联网/可选浏览器，记录环境、实际退出码、skip 和摘要/哈希。原始证据留在忽略目录。
- 仓库外 AGENTS 追加本次用户本机测试及 D 盘记录授权，以便后续上下文接续，不改仓库共享入口的历史状态。

## 工具验证与尚未执行

助手在用户当前 Ubuntu-22.04 中实际执行 `bash -n` 与脚本 `--check`，均退出 0；就绪输出确认 `/home/l7/LLMCloud`、uv 0.13.7、Python 3.12.16。两段内嵌 Python AST 解析、两份新增 Markdown 的 4 处相对链接及行尾空白检查通过，git diff --check 通过。以上只是收集脚本准备验证，没有运行 L1 测试或加载 GPU/模型。WSL 启动仍提示原 localhost/NAT 代理警告，不影响这两项本地检查。

### L1 用户执行与证据归档

用户已在 Ubuntu 执行首版脚本，run_id=`20261112T092752Z-cpu-1FmnN5`，回传完整终端输出。助手读取原始 metadata、summary、六项日志和 results.tsv，核对原 SHA256SUMS 全部通过；没有重跑并冒称用户这次执行。

实际基线 9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca、clean；2026-11-12 09:27:52～09:28:41 UTC（北京时间 17:27:52～17:28:41）。unittest 运行 412 项，411 通过、1 项显式可选浏览器工具检查跳过，自报耗时 43.792 秒；五项契约检查全通过，所有命令/日志退出码为 0，RUN_EXIT_CODE=0。CPU 测试不构成真实模型/训练/浏览器/云端验收。

用户进一步确认“结果放 D 盘，测试数据放 E 盘”。助手只将首轮 10 个小型结果文件（共 81,603 字节）归档至 D 盘 `data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/`，逐项核对哈希；额外保存首版 runner-used.sh，摘要与原 metadata 的 runner_sha256 一致。WSL 向 NTFS 复制时保留 Unix 文件属性的步骤不受支持，内容已复制并在 Windows 端按原清单验证通过；未复制模型、数据集、数据库或 Adapter，原 E 盘证据保留。

注册表只读核对 Ubuntu-22.04 的 BasePath 确为 E:\WSL\LLMCloudUbuntu。后续脚本改为在 D 盘保存小型结果；执行目录仍为 E 盘 Ubuntu 的 /home/l7/LLMCloud，临时数据使用 Ubuntu /tmp。当前说明/记录更新，不修改原 run 的 metadata、summary 或旧脚本快照。路径调整后 Bash 语法和 --check 均退出 0，实际输出确认 RESULTS_PARENT 位于 D 盘、运行副本为 /home/l7/LLMCloud；两段 Python AST、9 处 Markdown 链接、原始结果/runner 快照哈希及 git diff --check 通过。git check-ignore 确认证据目录继续被忽略；没有为日志路径调整重复执行已经通过的 CPU 回归。

下一步 L2 先检查是否已有模型缓存/迁移包，再安排固定版本缓存验证与 BF16 前向；真实小训练、独立重载及平台检查继续按顺序另行执行和记录。

### L2 下载准备（尚未运行模型操作）

本轮开始及 L1 后的收尾 fetch 均成功，D 盘 HEAD 与 origin/main 仍为 0/0；保留四项本轮自有新增文件，未提交/推送。只读检查几个已知模型目录均无缓存，也未在已知迁移包位置发现包；不据此声称全盘不存在历史资产。

模型官方元数据请求在当前 WSL 返回 curl 28/HTTP 000，镜像元数据请求 HTTP 200（0.923 秒，8224 字节）。新增 [模型阶段日志入口](../testing/laptop-3060-model.sh)，让用户先运行 prepare，显式将模型/缓存放 E、结果放 D；后续 check/gpu 分别由用户执行，不自动训练。沿用原 prepare_model.py、固定 revision 和完整校验，镜像 endpoint/关闭 Xet 仅通过本次进程环境传入，未修改共享代码。

助手在当前 Ubuntu 中实际执行模型脚本 Bash 语法和 --check，均退出 0；就绪输出确认模型缓存位于 /home/l7/LLMCloud/data/models/huggingface/hub、结果目标位于 D 盘、endpoint 为 hf-mirror.com。两段内嵌 Python AST、11 处 Markdown 链接、LF/行尾空白和 git diff --check 通过。这些只是准备验证；没有开始下载约 1GB 权重，未加载真实模型或执行 BF16 前向。

### L2 prepare 用户执行通过

用户随后运行模型脚本 prepare，run_id=20261112T094633Z-model-prepare-ioAxAt，2026-11-12 09:46:33～09:47:22 UTC（北京时间 17:46:33～17:47:22）。进度显示 9 文件约 45 秒完成，整轮约 49 秒。助手读取 D 盘原始 metadata、summary、result、command.log，按 SHA256SUMS 验证全部通过，并保留对应 runner-used.sh 快照；不是助手重跑下载。

实测 code_commit=9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca、clean，锁文件摘要与 L1 一致。模型/分词器 revision 均为 7ae557604adf67be50417f59c2c2f167def9a775，9 文件共 999602607 字节，status=cache_verified，阶段/命令/日志退出均成功，RUN_EXIT_CODE=0。镜像下载、模型/缓存仍在 E 盘；D 盘只保存小型证据。

该结果只证明模型准备及完整性校验，不是 GPU 模型前向或训练。下一步用户运行同脚本 check 独立离线复核，回传摘要/结果目录/退出码后再安排 gpu；L3 两步训练和 L4 平台仍未执行。

### L2 独立离线 check 用户执行通过

run_id=20261112T095244Z-model-check-LlaT2g，2026-11-12 09:52:44～09:52:45 UTC（北京时间 17:52:44～17:52:45），整轮约 1.4 秒。用户回传摘要后，助手读取 D 盘原始结果并验证 SHA256SUMS、code_commit/clean 状态、锁文件摘要和模型缓存位置，与前序一致；另保留 runner-used.sh 快照。

离线重读清单、全部 9 文件和模板，status=cache_verified、999602607 字节，模型/分词器 revision、模板哈希与 prepare 一致。command_exit_code=0、log_exit_code=0、RUN_EXIT_CODE=0、real_training=false。没有重复下载、GPU 模型加载或训练。

下一步由用户运行模型脚本 gpu，进行 BF16 模型加载/一次前向并回传摘要、结果目录、退出码；脚本自动在 D 盘记录耗时/显存和 logits 检查结果，模型继续留在 E 盘。用户尚未执行 GPU 模型检查，不提前收口 L2。

### L2 BF16 GPU 模型前向用户执行通过

run_id=20261112T095520Z-model-gpu-qgpDgq，2026-11-12 09:55:20～09:55:31 UTC（北京时间 17:55:20～17:55:31）。助手在用户回传后核对 D 盘原始结果/日志与清单、脚本快照，全通过；基线 clean、commit/锁文件摘要与前序一致。

Qwen 0.5B 真实 494032768 参数在 RTX 3060 Laptop 上按 BF16 完成一次前向，34 token、logits_shape=[1,34,151936]、有限值检查通过。探针 elapsed_seconds=1.899080589（不含导入/缓存校验），整轮约 11.6 秒，PyTorch 分配峰值 1042360320 字节（约 994MiB）。gpu_forward_verified，命令/日志/整轮退出均 0、real_training=false。至此 L2 三步通过，不宣称训练或在线推理通过。

### L3 两步训练准备，尚未实际训练

新增 [训练日志入口](../testing/laptop-3060-train.sh)。使用现有 3 条公开格式样例，先调用原 CPU 数据诊断，再调用原训练 CLI；BF16、batch=1、梯度累积=1、max_seq_length=128、LoRA r=4/alpha=8、2 步，其他默认值不变。参数均在现有配置允许范围内，不改 Trainer/共享契约或依赖。

UUID 与运行配置/Adapter/tokenizer/原始任务日志留 E；D 盘仅记录小型 metadata/终端日志/manifest/metrics 等结果。训练成功不自动等价独立产物审计或新进程重载，摘要明确标记两者 pending；不做正式效果评价。下一步用户执行脚本并回传 task_id、摘要/运行目录/退出码，之后才安排审计和重载。当前只准备入口，未启动训练。

助手在当前 Ubuntu 对新增训练脚本执行 Bash 语法与 --check，均退出 0；输出确认运行数据/模型位于 E 盘 Linux 副本、结果目标位于 D 盘，现有 TrainingConfig 接受 r=4/alpha=8、batch=1、梯度累积=1、seq=128。三段 Python AST、22 处 Markdown 链接、LF/行尾空白和 git diff --check 通过。没有为此重复 CPU 回归、模型下载或实际训练。

### L3 两步真实训练用户执行通过

用户执行 run_id=20261112T100532Z-train-FeJcO5，task_id=166cebf8-456c-4828-8fc5-df7db44585fc，2026-11-12 10:05:32～10:05:51 UTC（北京时间 18:05:32～18:05:51）。助手随后核对 D 盘全部原始结果哈希、metadata、训练清单/指标/日志并保存 runner 快照，没有重跑训练；代码 clean、commit/锁文件摘要与前序相同。

前置 3 条样例在 seq=128 时均未截断，回答监督有效。实际完成 2/2 更新，训练清单耗时 14.100822286 秒，PyTorch 分配峰值 1231694336 字节，270336 可训练参数；96/96 LoRA 张量变化、基础权重前后哈希一致。train Loss 2.7157、3.8602，无 eval，无正式效果结论。Adapter 权重清单大小 1093728 字节，manifest SHA-256=585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b。前置/训练/日志/整轮退出均 0。

数据、运行配置、Adapter/tokenizer 和原任务日志继续在 E 盘隔离运行目录；D 盘只有结果副本。L3 当前仅训练/保存通过，独立审计、新进程重载仍 pending，不提前完成。

新增 [审计/重载记录入口](../testing/laptop-3060-artifacts.sh)，audit 模式先调用原只读 CPU 审计，用户回传后再安排 reload 原 CLI 的新进程验收。--check 只读检查既有 manifest 和路径，不等同独立审计。助手在当前 Ubuntu 实际执行 Bash 语法和 --check，均退出 0，确认 E 盘原 manifest 的 SHA-256 与 D 盘结果一致；两段 Python AST、28 处 Markdown 链接、LF/行尾空白及 git diff --check 通过。未实际执行审计或重载，也未修改原产物。

### L3 独立 CPU 产物审计用户执行通过

用户执行 run_id=20261112T101155Z-audit-CoTNrY，2026-11-12 10:11:55～10:11:56 UTC（北京时间 18:11:55～18:11:56），整轮约 0.81 秒。助手核对 D 盘原始文件 SHA256SUMS、metadata/summary/result、训练 manifest 摘要与 runner 快照，全部通过；代码 clean、commit/锁文件摘要与前序一致，没有重新运行审计。

artifacts_verified，file_count=12、metric_count=2、tensor_count=96、completed_steps=2，task_id 为同一 166cebf8-456c-4828-8fc5-df7db44585fc，review_status=unknown。命令/日志/整轮退出均 0，manifest_unchanged=true，摘要仍为原 585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b。CPU 报告的 reload_verified=false 保留，不改写为未来重载结论。

下一步用户调用现有脚本 reload 模式，在已退出训练进程之后新启动原重载 CLI，使用独立开发提示词、最多 32 token 的 greedy 生成；记录 pid、实际权重匹配、响应、耗时、显存及 manifest 不变。新进程重载尚未运行，不提前完成 L3；没有新增代码或修改原产物。

### L3 新进程重载用户执行通过，工程闭环完成

用户回传 run_id=20261112T101527Z-reload-ub3D64、原 task_id 和退出 0；助手从 D 盘原始 metadata/result/summary/日志读取完整结果，验证 SHA256SUMS 与 runner 快照全部通过，不只凭退出码作通过结论。

2026-11-12 10:15:27～10:15:39 UTC（北京时间 18:15:27～18:15:39），整轮约 11.7 秒，重载/生成函数自报 3.976255552 秒；实际 PID 7354。BF16、38 输入/32 生成 token、greedy，96 个 Adapter 张量实际匹配，reload_verified。训练进程已结束后另起 CLI；原训练 PID 没有记录，不补造 PID 对比证据。

PyTorch 分配峰值 1010424320 字节（约 964MiB）。manifest 不变、摘要与原训练一致；Adapter SHA-256=d3e1994247faf4bb21bea2f875c0196f68e498493eb52e5e97b2f37e249083a2，与训练产物清单一致。命令/日志/整轮退出均 0。实际生成文本留 D 盘小型结果，达到 32 token 上限未完整结束，不能据此评分或宣称效果提升。

L3 训练/保存/独立审计/新进程重载完成；旧 audit 报告和训练摘要中的 pending/false 为原阶段事实，保留不改写。M5 在线推理、正式效果实验、云部署和双方联合验收仍未完成。

### L4 工具准备，平台未运行

助手只读核对 Ubuntu 缺 redis-server/redis-cli/Linux Node，npm 只发现 Windows 路径 /mnt/d/New Folder/npm；tmux 已存在。下一步先由用户安装 Redis 并回传实际版本，再准备满足 frontend engines 的 Linux Node/npm、前端回归/构建、独立运行目录/队列及真实页面端到端。没有沿用 Windows npm，也没有提前启动平台或真实训练任务。

### L4 Redis 已安装、Linux Node 安装准备

用户回传 redis-server/redis-cli 均为 6.0.16，记录为本轮 apt 实际版本；没有声称与历史 7.4.11 完全相同或已经通过实际 Celery 链路。

助手在 WSL 读取 Node 官方与镜像的 v22.23.3 SHASUMS256.txt，均 HTTP 200，Linux x64 tar.xz 摘要一致。新增 [Linux Node 安装入口](../testing/laptop-3060-node.sh)：按已读取的官方固定摘要校验镜像归档，在 E 盘 Ubuntu 用户目录安装，链接 ~/.local/bin，版本/路径/日志和校验结果写 D。不会修改系统 Node 或覆盖已有用户工具，也不修改前端锁文件；用户实际安装/前端测试仍待执行。助手在 Ubuntu 实测 Bash 语法/--check 均退出 0，确认下载缓存/安装目录在 E 盘 Ubuntu、结果路径在 D；内嵌 Python AST、36 处 Markdown 链接、LF/空白和 git diff --check 通过，未开始下载 Node 归档或安装。

### L4 Linux Node 安装通过，前端检查准备

用户已执行安装入口，run_id=20261112T102850Z-node-install-KzmqI7，完成于 2026-11-12 10:28:55 UTC（北京时间 18:28:55）。助手核对 D 盘原始 SHA256SUMS、摘要和 runner 快照，通过；Node v22.23.3、npm 10.9.9、platform linux，真实二进制与归档缓存位于 E 盘 Ubuntu，命令/日志/整轮退出均 0。用户还回传当前 shell node/npm 均解析到 /home/l7/.local/bin，未使用 Windows npm。

新增 [前端检查入口](../testing/laptop-3060-frontend.sh)，执行原 npm ci/test/build，使用本次镜像参数、锁定依赖/integrity，记录源码/锁文件摘要未变和实际测试数、六项命令/日志退出码、构建文件摘要。依赖/缓存/dist 留 E，D 只存小型结果；没有启动平台/浏览器/GPU，不预填前端通过结论。

助手在 Ubuntu 实测脚本 Bash 语法/--check 退出均 0，确认 Linux Node/npm、E 盘 frontend/npm cache 和 D 盘结果路径；两段 Python AST、39 处 Markdown 链接、LF/空白和 git diff --check 通过。另只读核对 npm replace-registry-host=npmjs，锁定 Vue 3.5.44 的镜像包 HEAD HTTP 200（约 0.273 秒）；不把入口连通写成全量依赖安装通过。尚未运行 npm ci/test/build。

### L4 前端用户执行通过，HTTP/Redis 预检准备

用户执行 run_id=20261112T103455Z-frontend-BDRx2c，2026-11-12 10:34:55～10:34:59 UTC（北京时间 18:34:55～18:34:59），整轮约 4 秒。助手核对原始 metadata/summary/三份日志/构建清单与 SHA256SUMS 全部通过并保留 runner 快照。基线 9b1165e、clean；Node v22.23.3、npm 10.9.9。

npm ci/test/build 和日志退出均 0，116 项全部通过，无失败/取消/跳过/todo；package.json 和 package-lock.json 摘要未变。dist 在 E 盘，有 index.html、JS、CSS 三文件，D 只记录大小/哈希；未做浏览器或真实 API/Worker 集成。

下一步新增 [HTTP/Redis 记录入口](../testing/laptop-3060-http.sh) 运行四个既有 TCP/HTTP/真实私有 Redis + 生产 Worker CPU 脚本，以验证新环境网络边界和 Redis 6.0.16 兼容性。GPU 禁用，所有数据/DB/socket 在 Ubuntu /tmp；CPU 指标、合成下载包和空缓存 MODEL_NOT_CACHED 失败均明确标注，不伪装成 GPU/页面验收。日志/摘要写 D，脚本管理的临时运行数据留 E 并由原工具清理。

助手在 Ubuntu 实测 Bash 语法/--check 退出均 0，确认实际 Redis 6.0.16、E 盘临时运行目录与 D 盘结果路径；两段 Python AST、44 处 Markdown 链接、LF/空白和 git diff --check 通过。没有启动服务或实际运行这四项预检。

遇到失败保留原始日志和具体 traceback；队友实现问题先登记症状与文件，不以测试为由修改受保护代码。原始模型、数据、DB、日志、环境配置继续不入 Git；共享工作日志索引和里程碑状态暂不改。

### L4 HTTP/Redis 用户执行通过，Chromium 准备

用户回传 run_id=20261112T104120Z-http-redis-SYB9OA、RUN_EXIT_CODE=0。助手核对 D 盘原始 metadata/summary/results.tsv/四项日志及 SHA256SUMS 七项全通过；当前 HTTP runner 摘要与 metadata 一致，另存 runner-used.sh，不改原报告。实际时间为北京时间 2026-11-12 18:41:20～18:41:29，代码 9b1165e、clean，锁文件摘要与前序一致。

数据集 TCP HTTP、受控 CPU 指标/日志、合成 CPU 下载包及独立审计/清理、实际私有 Redis + 生产 Worker/SQLite 消费四项均 status=ok，命令/日志退出均 0。MODEL_NOT_CACHED 为刻意空缓存失败；创建/幂等重放、重复投递跳过、实例锁与对账互斥通过。real_training=false、browser_checks=not_run，不据此完成真实 GPU/页面/联合验收。

只读查看 Ubuntu 的 Linux Node v22.23.3 与现有本地 Playwright 1.64.1，默认浏览器缓存下未发现安装目录。新增 [Chromium 准备日志入口](../testing/laptop-3060-browser.sh)，由用户执行本地锁定 CLI 的 install --with-deps chromium（可能 sudo 提示），成功后运行原 M4 工具 --check。浏览器/系统库/缓存留 E，D 保存小型结果与日志；GPU 隐藏，不启动平台服务。两项 preflight 报告、命令/日志退出码和依赖哈希共同决定通过，不把空白页检查写成业务页面验收。

助手实际执行 WSL Bash 语法与 --check 均退出 0，确认缓存 /home/l7/.cache/ms-playwright、运行副本 /home/l7/LLMCloud 位于 E 盘 Ubuntu，结果目标为 D 盘。两段内嵌 Python AST、文档相对链接及空白检查通过，git diff --check 通过；没有实际安装/启动 Chromium。下一步用户执行入口并回传摘要、EVIDENCE_DIR、RUN_EXIT_CODE 后，再安排真实平台流程。

本轮 git fetch origin 因 127.0.0.1 代理不可达失败，远端最新变化尚未确认；本地与缓存 origin/main 0/0 不代表最新同步成功。未修改队友实现/工具或共享契约，未提交/推送；人工工具已有 SIGINT 快照生命周期问题继续记录，不借本次测试越界修复。

### L4 用户改用已有浏览器；独立手动入口就绪

用户执行 Chromium 准备 run=20261112T104736Z-browser-sKLKTk，系统库安装完成后在浏览器下载阶段中止。助手先前采样证实 ZIP 在增长；目前无下载进程。保留未完成原始报告，不续传或把下载中止记作成功。手动 Windows 浏览器访问不要求 Playwright，原浏览器安装从当前门槛移除。

新增 [本轮独立手动入口](../testing/laptop-3060-manual.py)，复用现有 M4 Acceptance 服务/审计，不修改受保护文件；正常结束通过本轮 E 盘 STOP_REQUESTED 文件，待任务终态后先 capture，再 cleanup，避开原工具 Ctrl+C 时 API 先停止的已知问题。每轮 E 盘新 UUID/私有 Redis/独立 DB/产物，沿用同一 Worker 锁；D 盘仅保留小型 metadata/ready/report/脚本和结束后有界日志/哈希。仅启动不提交任务，实际训练为后续用户页面操作。

助手在 Ubuntu 运行 --check 退出 0；服务空跑 run=20261112T105556Z-manual-aa72c8rz 的 Redis/API/Vite 就绪、空列表及清理通过，无 Worker；正常启动/结束验证 run=20261112T105640Z-manual-tsbl22qf 则启动生产 Worker、获得 ready 后由测试控制器创建 STOP_REQUESTED，最终 local_session_closed_pending_review、tasks=[]、cleanup_errors=[]、退出 0。没有提交任务、GPU 训练或实际用户页面操作，不记为端到端通过。两次原始结果在 D 盘保存，完整空运行目录留 E；共享契约/依赖未改。

下一步用户执行 --start，保持终端打开，用已有 Windows 浏览器访问本轮 browser_url，回传 ready 摘要和页面是否可用；先不上传或提交。--start 会话正常结束命令在 ready.stop_command，中途不要按 Ctrl+C。运行会话默认为 2 小时后请求关闭，若尚有任务仍等待终态；发现卡住则保留现场排查。

本部分再次 fetch 仍被当前 127.0.0.1 代理阻断，远端最新提交尚未确认。保留本地既定 clean Linux 基线；没有合并、提交或推送。

### L4 用户手动会话已启动，待页面上传

用户回传 ready，当前 E 盘 run_id=0f5c44ae-a3cb-40ec-8dec-a12763ec7897，D 盘证据 20261112T105827Z-manual-pr6cllqq；助手读取原 ready/report，启动于北京时间 18:58:27，clean 9b1165e、同一锁文件，前端 49239/API 45867/Worker 9474 就绪，max_steps=40。尚无实际训练或用户页面操作通过结论，不改历史 report 的 pending。

下一步先由用户用现有 Windows 浏览器打开本次地址，上传 E 盘公开三条 train.jsonl 工程样例并刷新确认，回传成功消息/行数/数据集 ID。Windows 样例 628 字节、原始哈希与 D 样例一致；此前 Linux 625 字节样例不强行记作同一原始哈希，后续留存本次实际上传哈希。当前仅指导上传，不自动替用户提交训练。

### L4 用户网页上传通过，真实训练待提交

用户截图显示 train.jsonl 已在列表中（1 个、3 条、628 B）。助手生产 HTTP 只读复核列表/详情均可用，dataset_id=86005705-657e-463f-b414-6fc7d1ecc527、北京时间 19:01:34 创建、sha256=d0f8bbb4b1b99a8f7a125284d22506387eafd9bbd58a8dfaf5af865eea890162，与 E 盘源文件一致。截图所示名称为原文件名；不改写成建议名称，也不假设用户已刷新。核对时任务列表为空。观测摘要存本轮 D 盘 manual-upload-observation.json；用户原截图仍用原附件，不复制运行数据。

下一步指导用户按已验证的小资源配置（r=4/alpha=8、batch=1、梯度累积=1、seq=128、logging=1，其他原默认值）提交两个不同任务。内部40步已在启动时冻结，不修改 API/共享配置。用户确认首个提交成功后才准备新的第二任务；提交错误或不确定先回传，不新增。训练/串行/曲线/日志/下载均未先行记为通过。

### L4 两个真实任务完成，串行与源产物审计通过

用户截图显示 bea69c0c 已完成、f56625e9 40/40 RUNNING等待保存；助手随后核对HTTP，两者最终COMPLETED、无错误。首任务 bea69c0c-44bf-435f-892d-46ba5c16f431 的SQL北京时间20:42:18.918939～20:42:40.264177；第二任务 f56625e9-79c3-4004-8ddf-97df8617f7c0 于20:42:32.913950提交，实际20:42:40.283161～20:42:54.368430执行，间隔0.018984秒、无重叠，原check_serial通过。

实际两份config均 r=8/alpha=16，而非建议4/8；其他为batch1/累积1/seq128/logging1/seed42/lr.0002。每份40个真实train点，首/末Loss2.7157/2.3527，无eval；540672可训练参数。Trainer耗时19.5284/12.6386秒，峰值分配1235489280/1235882496字节。独立CPU审计原产物各12文件/96张量/40指标通过，clean9b1165e/锁文件一致、GPU分配证据有效；HTTP40个step/Loss与原文件逐条相同，没有重跑训练。

小型 live-training-observation.json 及每任务HTTP detail/metrics/logs在本轮D盘；原Adapter/DB/数据留E。两份manifest摘要、精确时间与配置已写测试说明。尚未验证本轮新Adapter重载、实际页面实时曲线或浏览器下载，源审计不冒充下载审计。下一步用户详情截图与下载两份ZIP到E盘，再做下载包原CPU审计/逐文件对比。单人本地操作不提前完成双方联合验收。

### L4 浏览器实际下载包独立审计通过

用户确认下载完成；助手在E盘指定目录读到两份实际ZIP（各18074681字节），于北京时间20:48:08～20:48:11在新CPU进程执行原audit_download。严格源清单、条目/大小边界、安全解压、逐文件SHA-256与原产物一致性、解压后原产物审计均通过；两份各12文件/96张量/40指标/40步，exact_source_bytes=true。执行前后原manifest/ZIP摘要未变，torch未导入、不使用GPU、不重新训练。

首ZIP SHA256=00daf8631b735c8ec02fde8444cd2d7158c804f55854cdac109d446dc60a9f84；第二ZIP=cd68b5508f8f9d7eac191cdf393787aedc3595401f2337ab6f0c0aa296ff20f2。压缩包继续在E盘Windows指定目录，解压在E盘Ubuntu本轮browser-download-audits/a1029cfd-a6ab-4437-966e-a04a61ad2274之下。D盘只保存小型browser-download-audit.json，不复制ZIP/Adapter/数据库。

下一步用户刷新/切换两任务详情，补最终40步曲线/日志截图，再用ready.stop_command正常结束并核对最终capture/cleanup/哈希。训练期间实时多轮曲线、训练时下载、取消/窄屏/双方操作等未实测项保留，不以本次离线审计代替；本轮新Adapter也没有重载。未提交/推送或删除运行数据。

### L4 终态曲线截图已收，等待日志截图与正常收尾

用户回传两张终态Loss页截图，可见1～40步、最终Loss2.3527、训练完成/下载控件，与先前原始指标一致。两图均未展示task_id/运行日志，不推断各自任务身份，也不当作训练进行时两轮实时刷新证据。原图未编辑，复制到D盘本轮user-loss-view-1/2.png，逐项核验原/副本哈希相同；browser-loss-observation.json记录观察与证据限制。

下一步用户切“运行日志”截图，之后在另一Ubuntu终端执行本轮STOP_REQUESTED正常结束；收尾时核对capture/cleanup和最终SHA256SUMS，保留全部E盘运行与下载数据。当前仍不记M3/M4双方联合验收完成。

### 本轮基础端到端复现完成并归档

用户补充全页日志图，明确首任务ID、40步/2.3527、真实33～40步日志和参数核验，且列表两任务均已完成。原图1279693字节原样保存D盘user-runtime-log.png并核对附件哈希，作为单张截图例外；自动运行文本仍遵守1MiB单文件复制上限，没有复制大型运行数据。

用户按正常结束命令退出，原报告北京时间20:54:28.370932保存：local_session_closed_pending_review、两任务COMPLETED、两份capture审计成功、real_training/gpu_execution_verified=true、cleanup_errors=[]。助手再核对原四个PID均退出、49239/45867无监听、下载临时区为空、同一Worker锁可取得并释放、Linux副本clean。post-session-cleanup.json记录结果。

原SHA256SUMS25项全通过，清单自身摘要3526e90740523e8dd91f346d1e47e7833079d870d6502f277ccc53dd76afa8f6；原清单/report保留不改。后补截图/清理/复核说明用SHA256SUMS.review单独覆盖。独立local-review-summary.json写local_basic_end_to_end_passed，范围为本次单人本地基础流程，不把原工具pending状态改成M3/M4双方验收完成。

用户可以关闭终端，旧URL已停止；E盘原模型/数据/DB/Adapter/ZIP/解压内容继续保留，D盘仅说明/小型证据。尚未覆盖现场实时轮询矩阵、训练中下载、取消/切换/窄屏、本轮40步Adapter重载、正式效果评估/M5/云部署与双方联合验收。下一轮应按所需范围补证据，不因本次通过直接收口里程碑。未修改队友实现/共享契约/依赖，未提交/推送或删除原数据；远端最新变化因代理失败尚未确认。

### 用户确认本地优先，准备M4补测后编写语料

用户明确希望基础功能在本地验收，上线前再租云机；随后要求助手给操作、用户执行回传、再由助手编写语料。按最新指示推进，不把租云作为当前功能测试前置。新增 [本地补测安排](../testing/laptop-3060-m4-followup.md)，保留专用自动报告/双方共同操作的实际证据边界。

仅在自有laptop-3060-manual.py增加--max-steps参数（5..200，默认40），为活训练观察/真实训练中下载留出工作量，不修改公开API/生产Trainer或制造延时。Ubuntu只读--check --max-steps200退出0，仍clean9b1165e/同uv.lock；Python AST、边界参数与文档检查另行验证。旧run内runner-used.py和已归档哈希不变。用户尚未启动新会话，没有预填本轮通过。

语料安排在用户回传本轮结果并核对后开始，按现有中文云计算领域/来源/问答族/冻结题隔离规则编写约120条候选草稿及侧车，AI草稿reviewed=false，留待双方人工审核；数据在E、说明/摘要在D。没有修改共享语料规范或提前宣称正式语料已完成。此次fetch仍因127.0.0.1代理不可达失败，远端最新状态尚未确认；未提交/推送。

### 200步补测会话已由用户启动

用户回传北京时间21:17:02启动的新ready，run_id=5421dcac-74c0-4af9-b5a4-d555384a5381，D盘证据20261112T131702Z-manual-po1lbqv7，前端34059/API34887/Worker10218，max_steps200。原ready中real_training=false；新会话不得引用旧任务当本轮执行。

下一步用户新上传原公开样例并提交首任务，开启每2秒刷新，在仍RUNNING且至少5个真实点时截一张，隔约4秒再截一张，保留任务身份和当前步数；Network保留请求。首任务提交后先不新增第二任务，回传证据再安排实际优化期间下载/页面交互。没有提前记录训练或实时轮询通过。

### 200步首任务已有活曲线截图，改用HAR补请求时序

用户反馈来不及截第二张，但图中明确task8e5c706b-332e-4922-97bb-54e8d0cf2e68、RUNNING、56/200、Loss.0040与超过5个曲线点、禁用下载。助手HTTP第56步核对完全一致（13:23:02.974953Z、offset9970），后查已COMPLETED/200点；SQL北京时间21:22:40.926858～21:23:28.582094。活图原样保存本轮D盘user-live-step56.png，原/副本哈希通过；live-ui-observation.json明确两轮浏览器活请求待HAR。

不因截图操作速度要求重训。下一步用户导出当前项目标签页Network HAR至E盘browser-evidence/m4-live-200.har，助手提取metrics活请求时序/原响应验证跨轮更新；完整HAR留E，小摘要D。暂不新增第二任务。实际config仍r8/alpha16/batch1/累积1/seq128/logging1，首轮3条工程样例不作效果结论。

### HAR确认真实训练中多轮更新通过

用户HAR为12126672字节/298请求，首任务metrics共24请求，其中17轮RUNNING/非空，13:22:54.938Z～13:23:27.531Z覆盖32.593秒。助手按原metrics字节offset核对200条step/Loss/time全一致，终态COMPLETED空补拉has_more=false、游标等于原文件36513字节。结合用户56步活图，五点可见/至少两轮真实刷新已确认，不再要求抢第二张图。

独立CPU审计原产物12文件/96张量/200指标通过，训练耗时45.9211秒/峰值1235489280字节/末Loss.001，无eval/正式效果结论。完整HAR留E，两个核对摘要写D，不加载GPU或重训。

为下一轮在途操作留足时间，指导用户第二任务仅将梯度累积从1改8，batch1/seq128/200步/logging1等不变，增加真实计算量而非人为延时。第二任务出现实际更新后下载首任务，再测试活日志上翻/回底、隐藏6秒恢复、切任务/刷新，导出m4-download-overlap.har并回传观察。下载/训练是否重叠仍待精确请求时间与原指标核对，尚未预填通过。

### 第二任务完成，实际训练中下载重叠通过

用户确认第二任务8da5af9b、下载完成、日志上翻不跳底、切页面正常。实际完整ID8da5af9b-56ab-4bb3-afd7-fc8d1d56489c，200步/累积8，SQL北京时间21:59:04.921890～22:00:37.779759完成。HAR实际名m4-down-overlap.har（47898559字节/584请求），不是原建议名；直接读取原文件，不要求重导出。

首任务/adapter下载21:59:12.395～12.985180、590.18ms、200 ZIP/18104072字节；第二任务原优化器事件21:59:12.366010/13.294478包围下载，实际计算与下载重叠通过。38轮第二任务活响应，200唯一指标/400次HAR记录按offset全匹配；第二任务原CPU审计12文件/96张量/200指标通过，耗时91.0158秒、峰值1238049792字节、末Loss.0004。首任务实际下载ZIP独立安全解压/原CPU审计及源字节比对通过，摘要59572fd6cb3db29fadde511d125a2498a6b33a6571652741711f7f9c185b2525。所有原ZIP/HAR/解压留E，小结果D。

日志上翻/任务切换与页面恢复记为用户观察通过；隐藏期间无新轮询缺少明确visibility时间证据，保留限制。最后指导显式3G限速取消/切任务下载、恢复无限制重下、390px/筛选/关闭详情，并导出m4-interactions.har后正常收尾；之后开始约120条语料草稿。当前不新增GPU任务，不把人工测试称专用自动报告或双方验收。

### 200步人工补测收尾、取消/重下与窄屏核对完成

用户报告窄屏正常、取消/切换/重下正常并回传原终端正常退出输出。实际HAR名m4-interations.har（102496922字节/730请求）保留原拼写。HAR中3个ERR_ABORTED，随后首/次任务完整ZIP响应均200（18104072/18102328字节），无后台延迟注入，用户明确使用浏览器3G限速后恢复无限制；条件按人工限速记录。现存首任务包与第二任务新下载包在E盘新目录独立安全解压/原CPU审计/源字节比对通过；首任务重新下载响应完整可查，但未另行识别新另存副本，限制单列。

窄屏截图62304字节原样保存D盘user-narrow-screen.png，原/副本哈希一致，可见次任务明确ID、完成200步/末Loss.0004和堆叠布局/图内滚动。目标390×844按用户步骤设置并自报正常，截图没有尺寸工具栏，不虚构实机或精确DPR证据。日志上翻/切换/恢复仍按用户实际观察留证。

会话22:15:24.383533正常关闭，capture两任务审计成功、cleanup_errors=[]；原PID10177/10183/10188/10218已退出，34059/34887端口关闭，下载临时区空，Worker原锁可取得并释放。原report/SHA256SUMS19项保留，校验全通过；后补结果用独立复核清单归档。具体见补测记录与D盘local-followup-review-summary.json。专用自动GPU报告、严格visibility时刻、分页、M3/M4双方同步联合验收和云部署等未执行项不提前勾选。

### 120条候选正式语料草稿完成

按用户“回传结果后编写语料”要求，先核对补测，再编写120条/30族（每族4条）中文问答，覆盖Docker12族、HTTP5族、DNS2族、SQLite5族、对象存储/负载均衡6族。分别打开30个官方文档页面核对事实并原创表述，原共享来源目录的5个ID只在本批独立catalog中保留给冻结协议引用，不作为新增训练来源。未修改共享sources.json、Schema、原准备工具或冻结规范。

原始JSONL、curation（120条均reviewed=false）、独立来源目录、逐条人工审核稿、authoring分组与独立构建入口均在E盘data/curated/cloud-basics-zh-draft-20261112-v1。调用原plan_dataset的sources_path参数/原write_bundle生成E盘data/prepared同名96/12/12草稿划分，build_id54acf9229ff98c04；原DatasetScanner、规范化问句/input去重、冻结题精确/保留族检查和字节级可复现重建通过，output完整重复0。

离线执行原check_training_data.py，固定Qwen revision/chat template，train96/validation12在256长度下截断均0，回答监督与manifest/provenance核对通过；test正文不参与token诊断，没有模型加载/GPU/正式训练。原始/划分/验证目录各自SHA256SUMS通过；source SHA256=d8a00d7bd16354a0577b6aeef88437c30a633c37e02a958d59d649e83d227f1e，34533字节。技术通过不等于事实/语义独立性/来源使用人工审核，仍draft_unreviewed。

D盘只新增 [候选语料交接说明](../data/cloud-basics-draft-2026-11-12-b.md) 与小型验证摘要，完整问答/审核正文/划分留E；没有把120条草稿当作已审核正式训练集。说明提醒原冻结C12含早期项目状态语句，正式评分前由双方复核适用性，本次不改v1。未提交/推送；fetch仍被127.0.0.1代理阻断，远端最新变化未确认。
