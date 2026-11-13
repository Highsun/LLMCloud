# RTX 3060 Laptop 本地复现测试记录

> Git交付入口：[队友阅读总览](laptop-3060-handoff-2026-11-13.md)。本页保留逐步本机历史；data/acceptance及E盘链接不随Git上传，已核对的公开摘要见总览。2026-11-13用户已授权提交/推送本轮自有文档与包装入口，早期“尚未授权”描述保留为当时事实。

建立日期：2026-11-12（Asia/Shanghai）。状态：L0～L3与40步基础端到端通过，随后200步人工补测已核对活曲线、多轮刷新、训练中下载、取消/切换/重下、窄屏与正常关闭；另已编写120条未审核语料草稿。专用自动报告、完整严格交互证据及M3/M4双方联合验收仍未收口，见文末接续。

## 目标和授权

用户明确要求在本机逐步测试，每一步提醒回传结果，并把对应记录写入 D 盘项目供队友核对。本轮允许本机 WSL2/GPU 测试，作为仓库 2026-11-06 仅云端运行约定的本次例外。已有 M3/M4 联合验收、云端部署和效果实验的完成条件不变。

仅新增本轮测试文档和执行现有检查的日志脚本，不修改队友业务实现、共享类型、依赖/锁文件、迁移或历史验收记录。提交/推送尚未授权。

## 工作目录与代码基线

| 用途 | 位置或状态 |
| --- | --- |
| D 盘开发/文档副本 | `D:\sw1mming\北京大学软件与微电子学院研一作业\云计算\大作业\LLMCloud` |
| E 盘 Windows 克隆 | `E:\LLMCloud`，从 GitHub 的 main 克隆 |
| Linux 测试副本 | Ubuntu-22.04 内 `/home/l7/LLMCloud`；从 E 盘克隆，origin 已设回 GitHub |
| Ubuntu 存储位置 | `E:\WSL\LLMCloudUbuntu`；已从当前 Windows 账号的 WSL 注册信息核对 |
| 已核对基线 | `9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca` |
| D 盘分支 | `feature/m4-observability-ui`；开始时干净，HEAD 与此次 fetch 的 origin/main 相同；领先自身远端分支 3 次提交 |

每轮执行时另采集 Linux 副本的实际 commit、dirty 状态、锁文件摘要和依赖版本，不能只沿用本表。运行期间不 merge 或修改代码。

用户明确的存储分工：**E 盘放运行环境、模型、数据、缓存、数据库和训练产物；D 盘项目放测试说明、结果摘要和用于核对的小型证据日志。** `/home/l7/LLMCloud` 与 Ubuntu 的 `/tmp` 均属于安装于 E 盘的 Linux 环境。调用 D 盘的脚本不会把测试工作目录改成 D 盘。

第一轮脚本先在 E 盘保存原始结果，助手已复制其中 10 个小型结果文件到 D 盘，原文件共 81,603 字节，SHA-256 与原始清单逐项一致；另保存与 metadata 中哈希一致的 `runner-used.sh` 快照。没有复制模型、数据集、数据库或 Adapter。后续脚本已改为直接把结果写到 D 盘，临时测试数据明确使用 Ubuntu `/tmp`。

## 已完成的环境准备（用户回传）

| 项目 | 结果与证据来源 |
| --- | --- |
| Ubuntu | Ubuntu-22.04 / WSL2 安装成功，创建用户 l7；来自用户终端回传 |
| 工具 | curl、ca-certificates、git 安装完成；uv 0.13.7；Python 3.12.16 |
| 基础依赖 | `uv sync --locked`：安装 44 包，准备耗时 3m 29s |
| 镜像安装 | 从锁文件导出暂不包含 torch 的精确版本/哈希清单，在清华镜像按 `--no-deps --require-hashes` 安装；安装 52 包，准备耗时 80m 43s |
| 最终补齐 | `uv sync --locked --extra training`：安装 torch 2.9.1+cu128，耗时 633ms |
| GPU 检查 | 用户运行 `uv run --locked --extra training python scripts/check_gpu.py` 并回传完整成功输出 |
| 真实 GPU 信息 | RTX 3060 Laptop GPU，6144 MiB；计算能力 (8, 6)；PyTorch 2.9.1+cu128 / CUDA runtime 12.8；前向/反向计算通过 |

上述 GPU 检查只执行小型张量运算，不是 Qwen 模型加载、BF16 模型训练、产物保存或完整平台验收。没有证据的测试开始时间、退出码和峰值显存不补填。

WSL 初始出现 localhost 代理/NAT 警告，尚未修改网络模式。清华镜像的约 0.91 MiB 单文件测速约 1.1 秒，不能据此承诺数 GiB 依赖的整体速度；实际完整安装耗时以上述用户输出为准。

## 分阶段清单

| 编号 | 检查及门槛 | 回传/保存证据 | 当前状态 |
| --- | --- | --- | --- |
| L0 | 环境安装、GPU 小型前向/反向 | 工具和 PyTorch/CUDA 版本、GPU 名称、终端输出 | 用户回传通过；尚无当时原始日志文件 |
| L1 | 现有 CPU 自动测试 + 五项契约漂移检查 | 基线/环境 metadata、六项退出码、完整日志、实际数量/跳过原因、SHA256SUMS | 412 项运行：411 通过、1 跳过；五项契约通过；已核验原始日志并归档 D 盘 |
| L2 | 固定 revision 模型缓存完整性和 BF16 GPU 前向 | 缓存报告/哈希、实际 GPU 报告、运行参数/时间/显存 | 全部通过；BF16 前向 1.899 秒、峰值分配 1042360320 字节、logits 有限 |
| L3 | 短样例两步 LoRA、产物审计、新进程重载 | task_id、配置、真实指标/日志、manifest、审计/重载 JSON、耗时/显存 | 全部通过；重载实际权重匹配、32 token、原清单不变；无正式效果结论 |
| L4 | 前端回归/构建、页面上传/异步状态/两任务串行/曲线日志/下载 | Redis/API/Worker/前端版本与日志，任务/请求 ID、截图、ZIP 哈希/审计和未测项 | 基础端到端通过并归档；用户上传/两任务各40步串行/终态曲线日志/实际下载包审计/正常关闭通过；完整交互与双方验收仍待完成 |

L1 中使用测试替身的训练、派发和产物只能记 CPU 测试。可选 M4 浏览器工具测试默认跳过，跳过必须保留名称/原因；没有外部浏览器验证时不能记浏览器通过。正式效果实验、M5 在线推理、云部署及双方共同操作不在 L1 的通过范围内。

## L1 执行方式

在 Ubuntu 终端运行 D 盘新增的 [CPU 证据脚本](laptop-3060-cpu.sh)：

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-cpu.sh"
```

脚本默认切入 `/home/l7/LLMCloud`。`--check` 仅验证入口/工具存在，不运行测试。正式运行使用已有 `.venv` 与 `uv run --offline --locked --extra training`，不重新下载依赖；禁用 GPU 可见性、HF 联网和可选浏览器入口。执行以下现有检查：

1. `python -m unittest discover -s tests -v`
2. `python scripts/export_dataset_contract.py --check`
3. `python scripts/export_training_contract.py --check`
4. `python scripts/export_task_contract.py --check`
5. `python scripts/export_task_openapi.py --check`
6. `python scripts/export_observability_contract.py --check`

后续每次直接在 **D 盘脚本所属项目**生成独立 `data/acceptance/b-review/laptop-3060/<UTC>-cpu-<随机后缀>/`，不覆盖旧结果。包含 `metadata.json`、六份 `.log`、`results.tsv`、`summary.json`、`SHA256SUMS`。此处 `data/acceptance` 只是沿用项目现有的结果忽略路径，其中仅保存小型证据文件，实际运行数据继续在 E 盘。原始日志不纳入 Git。

**回传提醒：** 执行后把 `RETURN_TO_CODEX_BEGIN` 到 `RETURN_TO_CODEX_END` 的摘要，以及 `EVIDENCE_DIR`、`RUN_EXIT_CODE` 发到当前聊天。失败时同时提供 FAILED/ERROR 段和 traceback；保留完整日志，不只发最后一行，也不先重装/改代码。

收到后由助手读取 D 盘原始日志、核对摘要和 SHA-256，再更新本文与独立交接日志。第一轮的 E 盘暂存结果已完成复制/校验，后续无需再复制运行数据。D 盘新增文档尚未进入 Linux 副本的提交，metadata 会另外记录实际 runner 路径/摘要供审查。

## 结果登记

### L1：20261112T092752Z-cpu-1FmnN5

- 执行人：用户在 Ubuntu 运行；证据来自用户粘贴的完整终端输出与助手随后读取的原始文件，不是助手重跑。
- 时间：2026-11-12 09:27:52～09:28:41 UTC（北京时间 17:27:52～17:28:41）；unittest 自报耗时 43.792 秒。
- 实测代码：`9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca`，工作区 clean；Python 3.12.16，uv 0.13.7。
- unittest：运行 412 项，411 项通过，1 项跳过，退出 0。跳过项为 `test_m4_acceptance.M4AcceptanceTests.test_browser_workflow_against_real_api_and_synthetic_cpu_inputs`；此项需要显式开启真实浏览器/CPU 替身工具检查，不计为本轮浏览器通过。
- 数据集、训练、任务、任务 OpenAPI、观测共五项契约检查均 PASS；六个执行退出码和六个 tee 日志退出码均为 0，`RUN_EXIT_CODE=0`。
- 日志包含 Starlette/TestClient 弃用提示，以及测试主动注入的错误日志；unittest 结论为 `OK (skipped=1)`，没有失败或错误项。未修改实现来消除这些日志。
- D 盘结果：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/summary.json)、[完整 CPU 日志](../../data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/cpu-tests.log)、[环境/基线](../../data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/metadata.json)、[校验清单](../../data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/SHA256SUMS)、[本次脚本快照](../../data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5/runner-used.sh)。
- E 盘原始位置仍为 `/home/l7/LLMCloud/data/acceptance/b-review/laptop-3060/20261112T092752Z-cpu-1FmnN5`；原 `summary.json` 中的 evidence_dir 保留真实原路径，没有改写历史结果。

### L2：模型缓存准备/独立离线 check/真实前向全部通过

助手已只读检查 Linux 项目默认模型目录、E 盘 Windows 克隆默认模型目录、当前 Linux 用户 Hugging Face 默认缓存，均不存在；E 盘根目录/克隆目录和当前 Windows 用户下载目录的已知名称检查未找到迁移包。这不是全盘搜索，也不排除用户将包另存在其他位置。

在同一 WSL 环境对固定 revision 的元数据入口限时探测：huggingface.co 返回 curl 28 / HTTP 000，无数据；hf-mirror.com 返回 HTTP 200，约 0.923 秒、8224 字节。仅证明元数据连通，不代表约 1GB 权重已下载或保证其速度。

新增 [模型阶段日志脚本](laptop-3060-model.sh)，分为 `prepare`、`check`、`gpu` 三个独立模式，每次只运行一个阶段：

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-model.sh" prepare
```

prepare 已由用户执行通过。复用现有 `scripts/prepare_model.py`，固定 Qwen/Qwen2.5-0.5B-Instruct 与 revision `7ae557604adf67be50417f59c2c2f167def9a775`；以单次进程环境指定 HF 镜像入口、关闭 Xet 传输，仍由原工具核对固定 revision、文件大小/摘要、模板并生成原格式清单。不改依赖、共享实现或模型白名单。传输来源明确记为镜像，不描述为直连官方源。

模型及下载缓存明确在 E 盘 Ubuntu 的 `/home/l7/LLMCloud/data/models/huggingface/`；日志/metadata/result/summary/SHA256SUMS 直接保存在 D 盘 `data/acceptance/b-review/laptop-3060/<UTC>-model-prepare-<随机后缀>/`。本次已下载约 1GB 权重/配套文件，没有更新模型参数或自动进入 GPU 前向/训练。

#### prepare：20261112T094633Z-model-prepare-ioAxAt

- 来源：用户回传终端摘要，助手核对 D 盘 metadata、result、summary、command.log 和 SHA256SUMS；原文件哈希全通过，另保存与 metadata 中摘要一致的 runner-used.sh。
- 时间：2026-11-12 09:46:33～09:47:22 UTC（北京时间 17:46:33～17:47:22）；下载进度显示约 45 秒，整轮约 49 秒。
- 基线：9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca，clean；锁文件摘要与 L1 相同。
- 结果：`cache_verified`，9 个文件，共 999602607 字节；model/tokenizer revision 均为既定完整 SHA；chat_template_sha256=`cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f`。
- 阶段/命令/日志均成功，`RUN_EXIT_CODE=0`，`real_training=false`；不据此填写 GPU 加载或训练通过。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T094633Z-model-prepare-ioAxAt/summary.json)、[完整日志](../../data/acceptance/b-review/laptop-3060/20261112T094633Z-model-prepare-ioAxAt/command.log)、[metadata](../../data/acceptance/b-review/laptop-3060/20261112T094633Z-model-prepare-ioAxAt/metadata.json)。

#### check：20261112T095244Z-model-check-LlaT2g

- 来源：用户执行并回传摘要，助手核对 D 盘原始 metadata/summary/result/日志和 SHA256SUMS 全部通过；保留与 metadata 摘要一致的 runner-used.sh。
- 时间：2026-11-12 09:52:44～09:52:45 UTC（北京时间 17:52:44～17:52:45）；整轮约 1.4 秒。
- 代码基线 clean、完整 commit 与锁文件摘要均与 L1/prepare 一致。独立进程离线复核缓存清单、9 个实际文件和模板，结果 `cache_verified`、999602607 字节，model/tokenizer revision 与模板哈希均与 prepare 相同。
- 阶段、命令和日志退出码均成功，`RUN_EXIT_CODE=0`，`real_training=false`；没有 GPU 模型加载或训练。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T095244Z-model-check-LlaT2g/summary.json)、[完整日志](../../data/acceptance/b-review/laptop-3060/20261112T095244Z-model-check-LlaT2g/command.log)、[metadata](../../data/acceptance/b-review/laptop-3060/20261112T095244Z-model-check-LlaT2g/metadata.json)。

#### gpu：20261112T095520Z-model-gpu-qgpDgq

- 来源：用户运行 GPU 模型脚本并回传完整结果；助手核对 D 盘原始 metadata/summary/result/日志与 SHA256SUMS，全部通过，保存对应 runner-used.sh。
- 时间：2026-11-12 09:55:20～09:55:31 UTC（北京时间 17:55:20～17:55:31）；整轮约 11.6 秒。探针报告 elapsed_seconds=1.899080589，该计时不包含依赖导入和缓存哈希复核，不作为整个平台性能结果。
- 实测代码 clean、完整 commit 与锁文件摘要均与前序相同；RTX 3060 Laptop、torch 2.9.1+cu128、CUDA 12.8、Transformers 4.57.6、huggingface-hub 0.36.2。
- GPU 以 BF16 加载 494032768 参数；34 输入 token，logits_shape=[1,34,151936]，logits_dtype=torch.bfloat16，logits_finite=true。
- status=gpu_forward_verified；peak_memory_allocated_bytes=1042360320（约 994 MiB，是 PyTorch 分配峰值，不是整卡占用）；命令/日志/整轮退出均为 0，real_training=false。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T095520Z-model-gpu-qgpDgq/summary.json)、[完整日志](../../data/acceptance/b-review/laptop-3060/20261112T095520Z-model-gpu-qgpDgq/command.log)、[metadata](../../data/acceptance/b-review/laptop-3060/20261112T095520Z-model-gpu-qgpDgq/metadata.json)。

### L3：两步真实 LoRA/独立审计/新进程重载全部通过

本阶段先验证训练/保存工程链路，之后再分别做独立 CPU 产物审计和新进程重载。使用现有 `docs/examples/train.jsonl` 的 3 条公开格式样例，review_status 仍按原工具记为 unknown，不作为人工审核语料或正式效果实验，也不使用冻结评测题调参。

| 参数 | 本次约定 |
| --- | --- |
| 模型/revision | 沿用已验证的固定 Qwen 0.5B 与完整 SHA |
| 精度/优化器步数 | BF16 / max_steps=2 |
| batch/梯度累积 | per_device_train_batch_size=1 / gradient_accumulation_steps=1 |
| 最大长度 | max_seq_length=128 |
| LoRA | r=4、alpha=8、q_proj/v_proj、dropout=0.05 |
| 其他 | 原 TrainingConfig 默认学习率 2e-4、seed=42、每步日志；无验证集，不伪造 eval |

新增 [两步训练日志入口](laptop-3060-train.sh)。`--check` 只读验证路径和配置类型；正式运行先调用现有 check_training_data.py 检查真实 tokenizer、监督标签、截断和 batch，再调用原 `python -m trainer.train`。前置失败则不启动训练。每次新 UUID，不覆盖旧输出、不自动重试/降配，也不修改 Trainer/共享类型。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-train.sh"
```

输入样例在 E 盘 Linux 副本，运行配置与 Adapter/tokenizer 等在 E 盘 `/home/l7/LLMCloud/data/local-validation/laptop-3060/<task_id>/`。D 盘只保存 metadata、前置/训练终端日志、结果摘要、训练 manifest/配置快照/metrics/任务日志等最多 1MiB/文件的小型证据，绝不复制 Adapter、tokenizer 或数据集。复用已下载模型，HF/uv 均离线运行。

**回传提醒：** 完成后发送 `RETURN_TO_CODEX_BEGIN` 与 `RETURN_TO_CODEX_END` 之间摘要，以及 EVIDENCE_DIR、TASK_ID、RUNTIME_DIR、RUN_EXIT_CODE。记录真实 Loss、步数、可训练参数、耗时和训练峰值显存，不要求 Loss 必须下降。前向通过不能预先保证训练也不会 OOM；失败保留原报告、failure.json/日志，不覆盖或自动重训。助手核对本轮结果后再安排独立审计与新进程重载。

#### 两步训练：20261112T100532Z-train-FeJcO5

- 用户执行 task_id=`166cebf8-456c-4828-8fc5-df7db44585fc`；运行目录为 E 盘 Ubuntu 的 `/home/l7/LLMCloud/data/local-validation/laptop-3060/166cebf8-456c-4828-8fc5-df7db44585fc`。
- 时间：2026-11-12 10:05:32～10:05:51 UTC（北京时间 18:05:32～18:05:51）；整轮约 18.8 秒；训练清单报告 elapsed_seconds=14.100822286。
- 用户回传后助手核对 D 盘全部结果文件的 SHA256SUMS、metadata/清单/指标/任务日志，均通过；保存与 metadata 摘要一致的 runner-used.sh。代码仍为既定 9b1165e、clean，锁文件摘要不变。
- 前置数据检查：3 条、625 字节，token 长度 56/73/73，均未截断；有效回答监督 token 22/29/34，EOS 监督存在；review_status=unknown，无验证集。预处理的“不加载 PyTorch”提示来自该 CPU 工具的 USE_TORCH=0 隔离设置，不代表训练依赖缺失。
- 训练完成 2/2 步，可训练参数 270336，总参数 494303104；96/96 个 LoRA 张量变化，基础权重前后 SHA-256 同为 `e0d7e651e5b6b9da6b4c53f5013797d72ffcf4d8ecf42361df6aee925969e079`，base_unchanged=true。
- 第 1/2 步真实 train Loss 为 2.7157 / 3.8602；末步学习率 0，eval_loss=null。不以两步不同样本的 Loss 波动判断效果提升或退化。
- peak_memory_allocated_bytes=1231694336（约 1.15GiB；PyTorch 分配峰值），不是整卡显存。Adapter 权重清单大小 1093728 字节；完整 manifest SHA-256=`585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b`。
- preflight、training 及对应日志退出码均为 0，RUN_EXIT_CODE=0；训练/保存通过，但独立审计和新进程重载仍 pending。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T100532Z-train-FeJcO5/summary.json)、[训练日志](../../data/acceptance/b-review/laptop-3060/20261112T100532Z-train-FeJcO5/training.log)、[训练清单副本](../../data/acceptance/b-review/laptop-3060/20261112T100532Z-train-FeJcO5/training-manifest.json)、[参数核验/任务日志](../../data/acceptance/b-review/laptop-3060/20261112T100532Z-train-FeJcO5/task.log)。

#### 独立产物审计：20261112T101155Z-audit-CoTNrY

使用 [产物审计/重载日志入口](laptop-3060-artifacts.sh) 的 audit 模式，调用原 `scripts/check_training_artifacts.py`，在独立 CPU 进程读取 E 盘现有产物并检查清单/文件哈希、配置、Adapter 张量、tokenizer 和指标；不重新训练，也不加载 GPU 模型。结果仍写 D 盘，记录审计前后 manifest 哈希一致性。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-artifacts.sh" audit 166cebf8-456c-4828-8fc5-df7db44585fc
```

用户已执行上述 audit。时间为 2026-11-12 10:11:55～10:11:56 UTC（北京时间 18:11:55～18:11:56），整轮约 0.81 秒。助手核对 D 盘原始 metadata/summary/result/日志及 SHA256SUMS 全部通过，并保留 runner-used.sh；代码基线仍为既定 9b1165e、clean，锁文件摘要与训练一致。

结果 status=artifacts_verified，task_id 与原训练一致，file_count=12、metric_count=2、tensor_count=96、completed_steps=2、review_status=unknown；命令/日志/整轮退出均为 0。manifest_unchanged=true，SHA-256 仍为 `585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b`。reload_verified=false 表示本轮 CPU 审计没有验证重载，不是训练失败；旧报告保留该值，不在后续重载通过后改写。

D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T101155Z-audit-CoTNrY/summary.json)、[完整日志](../../data/acceptance/b-review/laptop-3060/20261112T101155Z-audit-CoTNrY/command.log)、[metadata](../../data/acceptance/b-review/laptop-3060/20261112T101155Z-audit-CoTNrY/metadata.json)。

#### 新进程重载：20261112T101527Z-reload-ub3D64

同一日志入口的 reload 模式调用原 `scripts/reload_adapter.py`；训练进程已结束，再以新的 CLI 进程从 E 盘读取固定基础模型与本次 Adapter/tokenizer，核对实际加载权重、激活与冻结状态，再按 BF16/greedy 生成最多 32 个 token。使用“请给出一个整理书桌的小建议。”作为工程开发提示词，不使用冻结评测题，不做质量评分或效果提升结论。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-artifacts.sh" reload 166cebf8-456c-4828-8fc5-df7db44585fc
```

用户已执行上述 reload，并回传 EVIDENCE_DIR/TASK_ID/RUN_EXIT_CODE=0。助手随后读取 D 盘完整 metadata/result/summary/日志，验证 SHA256SUMS 全部通过、保存 runner-used.sh；不只凭退出码判断，也未重新运行重载。

- 时间：2026-11-12 10:15:27～10:15:39 UTC（北京时间 18:15:27～18:15:39），整轮约 11.7 秒；重载/生成函数自报 3.976255552 秒。
- 实际 PID=7354；训练进程已退出后另起 CLI 进程，代码仍为既定 9b1165e、clean、同一锁文件。没有记录原训练 PID，不补造两个 PID 数值的对比。
- reload_verified，BF16，38 输入 token，生成 32 token（达到本次上限）、do_sample=false；96 个 Adapter 张量，adapter_weights_matched=true。实际响应保留在 result/summary，文本因 32 token 上限未完整结束，不作为效果评价。
- PyTorch 分配峰值 1010424320 字节（约 964MiB），manifest_unchanged=true；原 manifest SHA-256 仍为 `585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b`，Adapter SHA-256=`d3e1994247faf4bb21bea2f875c0196f68e498493eb52e5e97b2f37e249083a2`。
- 命令/日志/整轮退出均 0；本步 real_training=false，不重新训练；review_status=unknown，不把本次工程生成写成正式语料评测或 M5 在线推理。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T101527Z-reload-ub3D64/summary.json)、[完整日志](../../data/acceptance/b-review/laptop-3060/20261112T101527Z-reload-ub3D64/command.log)、[metadata](../../data/acceptance/b-review/laptop-3060/20261112T101527Z-reload-ub3D64/metadata.json)。

L3 的训练、保存、独立 CPU 审计和新进程重载闭环至此完成。旧 audit 报告的 reload_verified=false 保留为当时范围，新报告另行证明 reload_verified。

### L4 工具准备（尚未运行平台）

初次只读检查时 Ubuntu 没有 redis-server、redis-cli、Linux node，npm 仅找到 Windows 路径 `/mnt/d/New Folder/npm`，不能作为本轮 Linux 前端工具使用；tmux 存在。前端要求 Node `^22.18.0 || >=24.12.0`，仓库 `.node-version` 为 22.23.3。

用户随后安装 Redis 并回传：`redis-server 6.0.16`、`redis-cli 6.0.16`（jemalloc-5.2.1、64bit）。这是本次 Ubuntu apt 的实际版本，不是历史环境的 7.4.11；版本命令成功不等于 Celery 业务链路通过，后续在隔离队列/目录实测。

Node 准备：助手在同一 WSL 限时读取官方与 npm 镜像的 v22.23.3 SHASUMS256.txt，均 HTTP 200；Linux x64 tar.xz 的 SHA-256 相同，为 `df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de`。来源：[官方校验清单](https://nodejs.org/dist/v22.23.3/SHASUMS256.txt)。

新增 [Linux Node 安装日志入口](laptop-3060-node.sh)，从已探测的镜像下载官方归档，按上述固定官方摘要验证后解压到 E 盘 Ubuntu 的 `~/.local/share/llmcloud-tools/node-v22.23.3-linux-x64`，下载缓存也在 Ubuntu；只在用户 `~/.local/bin` 添加 node/npm/npx 链接，遇到其他已有工具则停止，不覆盖。结果日志/摘要直接写 D。`--check` 只读验证参数和路径。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-node.sh"
```

Node 安装已由用户执行通过，run_id=20261112T102850Z-node-install-KzmqI7，完成于 2026-11-12 10:28:55 UTC（北京时间 18:28:55）。助手核对 D 盘原始日志/摘要及 SHA256SUMS，全部通过并保存 runner-used.sh。Node=v22.23.3、npm=10.9.9、platform=linux，exec_path 位于上述 E 盘 Ubuntu 安装目录，命令/日志/整轮退出均 0。

用户随后回传当前 shell 的 `command -v node`、`command -v npm` 分别为 `/home/l7/.local/bin/node`、`/home/l7/.local/bin/npm`，确认没有命中 Windows npm。D 盘安装证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T102850Z-node-install-KzmqI7/summary.json)。

#### 前端依赖/回归/构建：20261112T103455Z-frontend-BDRx2c

新增 [前端检查日志入口](laptop-3060-frontend.sh)，在 E 盘 Linux 副本的 frontend 执行 `npm ci --include=dev --registry https://registry.npmmirror.com --no-audit --no-fund --loglevel=info`，按现有 package-lock 保留精确版本和 integrity 校验，然后运行原 `npm test` 与 `npm run build`。镜像仅通过本次命令参数指定，不改 .npmrc、package.json 或锁文件；记录并核对两文件执行前后 SHA-256。安装失败则后两项不运行，测试失败仍收集构建结果，整体结论保留失败。

node_modules、npm 缓存和 dist 均在 E 盘 Ubuntu；D 盘仅保存 metadata、三份日志、测试数量/退出码、构建文件名/大小/哈希和结果摘要，不复制 node_modules 或 dist。此轮跳过浏览器下载，不启动 Redis/API/Worker 或 GPU。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-frontend.sh"
```

用户执行上述检查并回传完整摘要；助手核对 D 盘原始 metadata、install/tests/build 日志、summary、构建文件摘要及 SHA256SUMS 全部通过，并保存 runner-used.sh。代码仍为既定 9b1165e、clean；Node v22.23.3、npm 10.9.9。

- 时间：2026-11-12 10:34:55～10:34:59 UTC（北京时间 18:34:55～18:34:59），整轮约 4 秒。
- npm ci/test/build 与三份日志退出码均 0；前端测试实际 116 项全部通过，无失败、取消、跳过或 todo。
- package.json 与 package-lock.json 执行前后 SHA-256 未变。构建生成 index.html、JS、CSS 共 3 文件，仍在 E 盘 `/home/l7/LLMCloud/frontend/dist`；D 盘只保存文件清单/大小/哈希。
- D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T103455Z-frontend-BDRx2c/summary.json)、[测试日志](../../data/acceptance/b-review/laptop-3060/20261112T103455Z-frontend-BDRx2c/tests.log)、[构建清单](../../data/acceptance/b-review/laptop-3060/20261112T103455Z-frontend-BDRx2c/build-files.json)。

#### 真实 HTTP/私有 Redis 的 CPU 连通性预检（已通过）

下一步用 [HTTP/Redis 日志入口](laptop-3060-http.sh) 执行四个现有脚本：check_dataset_http.py、check_task_observability.py、check_task_download.py、check_worker_dispatch.py。它们分别验证真实 TCP 上传/查询/错误、受控 MetricWriter 指标/日志、合成 CPU 产物的下载/原审计/断连清理，以及当前 Redis 6.0.16 与生产 Worker/SQL 的实际消费、去重和锁互斥。

这轮将 GPU 隐藏，临时数据库/数据/私有 Redis socket 均在 E 盘 Ubuntu `/tmp`，由原脚本管理清理；结果/日志写 D。Worker 场景刻意使用空的独立模型缓存，预期任务进入 MODEL_NOT_CACHED，以验证失败状态与重复消息保护；不会损坏已验证的真实缓存或启动训练。指标和下载产物仍明确为 CPU 测试安排，不算真实 GPU 或浏览器验收。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-http.sh"
```

**回传提醒：** 完成后发送 BEGIN/END 间摘要、EVIDENCE_DIR、RUN_EXIT_CODE。预期四项 result.status=ok，所有命令/日志退出 0。若有失败，保留该项 traceback 与原日志；不因预期 MODEL_NOT_CACHED 而重装/删除真实模型缓存。通过后再组织实际浏览器/真实 GPU 平台会话。

用户执行 run_id=`20261112T104120Z-http-redis-SYB9OA` 并回传 `RUN_EXIT_CODE=0`。时间为北京时间 2026-11-12 18:41:20～18:41:29；metadata 的开始时间带 +08:00，summary 的结束时间为 10:41:29 UTC。助手读取四项原始日志/metadata/summary/results.tsv，核对原 SHA256SUMS 七项全通过；当前脚本摘要与 metadata.runner_sha256 一致，并保存对应 runner-used.sh。运行代码仍为既定 9b1165e、clean，uv.lock 摘要与前序一致。

四项 status=ok，命令及日志退出码均 0：数据集实际 HTTP 上传 201/列表详情 200/非法查询 422/超限 413；受控 CPU 指标追加、终态补拉、日志投影及游标错误通过；合成 CPU 下载包 HTTP 200、独立审计、篡改/忙/未就绪反馈与临时区/断连清理通过；实际私有 Redis + 生产 Worker + SQLite 创建 202、幂等重放 200、空缓存 MODEL_NOT_CACHED、重复消息跳过与对账锁互斥/停止释放通过。没有执行 GPU、页面业务或联合验收。

D 盘证据：[summary.json](../../data/acceptance/b-review/laptop-3060/20261112T104120Z-http-redis-SYB9OA/summary.json)、[Worker 日志](../../data/acceptance/b-review/laptop-3060/20261112T104120Z-http-redis-SYB9OA/redis-worker-cpu.log)。

#### Chromium 安装及空白浏览器预检（用户中止，后续不作为门槛）

助手只读核对 E 盘 Ubuntu 的 Linux Node v22.23.3、现有本地 Playwright CLI 存在，默认 ~/.cache/ms-playwright 下未发现已安装浏览器。新增 [浏览器准备日志入口](laptop-3060-browser.sh)，用已锁定的本地 CLI 执行 `install --with-deps chromium`，沿用供应商默认下载来源；可能提示输入 Ubuntu 的 sudo 密码以安装系统共享库。只安装浏览器运行依赖，不重新 npm ci、不修改项目依赖或锁文件。

浏览器缓存明确设为 E 盘 Ubuntu 的 `/home/l7/.cache/ms-playwright`，系统库及下载临时文件也在 E 盘 Ubuntu。D 盘只保存安装/预检日志、metadata、summary 和脚本快照/哈希。安装成功才调用既有 `scripts/check_m4_acceptance.py --check`，启动空白 headless Chromium 并退出；GPU 隐藏，不启动平台 API/Redis/Worker，不训练，也不等于页面业务通过。

```bash
bash "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-browser.sh"
```

原回传约定为 BEGIN/END 间摘要、EVIDENCE_DIR、RUN_EXIT_CODE。用户随后要求直接使用已有 Windows 浏览器；本步骤已中止，不要求重新安装或补做 Playwright 预检。历史入口/日志保留，不记安装或浏览器通过。

本次 `git fetch origin` 因本机代理 127.0.0.1 不可达失败，远端新提交尚未确认；本地 HEAD 与缓存 origin/main 的 0/0 不作为已完成远端同步的证据。未合并、提交或推送。后续真实平台测试仍须确认 GPU 独占使用；人工模式原工具在 Ctrl+C 时的快照生命周期问题已知，当前不修改 A 侧工具，也不依赖该模式启动本轮测试。

#### 使用现有 Windows 浏览器的手动平台入口（待用户启动）

用户已中止浏览器下载。原 run=`20261112T104736Z-browser-sKLKTk` 的 install.log 显示 Ubuntu 系统库已安装，下载 Chromium 时进度显示 0%；助手只读采样临时 ZIP 从 15285084 增至 17214598 字节，说明当时仍在下载。中止后确认相关下载进程已退出；原 metadata/日志/快照继续保留，不将缺失 summary 填成成功。手动网页操作不依赖 Linux Playwright 浏览器，不再继续下载。

新增 [手动平台入口](laptop-3060-manual.py)，作为本轮独立测试包装，导入现有 M4 Acceptance 的生产服务启动/停止及 capture，不修改 A 的原工具或后端。唯一会话流程调整是等待 E 盘本轮 `STOP_REQUESTED` 文件，所有任务进入终态后先在 API 仍可用时 capture，再执行原 cleanup；这样常规结束不触发已知 Ctrl+C 快照顺序问题。请通过 ready.json 中 stop_command 在另一 Ubuntu 终端正常结束，保持启动终端打开，避免 Ctrl+C。若任务卡在非终态则保留现场并排查，不自动停训练/对账或修改状态。

每轮全新 UUID，实际 DB/上传数据/产物/服务日志均留 E 盘 `/home/l7/LLMCloud/data/acceptance/m4-07/<UUID>`，原共享 Worker 锁仍用 `/home/l7/LLMCloud/logs/worker.lock`；私有 Redis socket 位于 Ubuntu /tmp。D 盘实时保存 metadata、ready/report 和 launcher 快照，结束后复制最多 1MiB/文件的顶层日志/JSON 并生成 SHA256SUMS，不复制 DB、数据集、Adapter、ZIP 或完整运行目录。全程离线复用已核验的真实模型；只启动服务不会自动提交训练。实际训练固定 BF16/内部最多 40 步，后续页面配置使用 batch=1、seq=128、LoRA r=4/alpha=8、梯度累积=1、logging_steps=1，再由用户明确提交。

助手已完成只读 `--check`；服务空跑 `--smoke-services`（run=`20261112T105556Z-manual-aa72c8rz`）真实启动/停止 Redis、API、Vite，数据集列表 200、任务为空，没有 Worker/GPU；随后真实 `--start` → ready → 正常结束文件验证（run=`20261112T105640Z-manual-tsbl22qf`）启动唯一生产 Worker并正常关闭。两轮退出 0、cleanup_errors=[]、无任务、real_training=false、gpu_execution_verified=false，不能当作网页或训练通过。Python AST 与本轮证据哈希另行检查；未改 A 代码或项目锁文件。

用户下一步在 Ubuntu 执行：

```bash
cd ~/LLMCloud
.venv/bin/python "/mnt/d/sw1mming/北京大学软件与微电子学院研一作业/云计算/大作业/LLMCloud/docs/testing/laptop-3060-manual.py" --start
```

**回传提醒：** 就绪时终端先输出 BEGIN/END 间的 ready 摘要，包含本轮 browser_url、runtime_dir、evidence_dir 和 stop_command。使用现有 Windows 浏览器打开本轮 browser_url，先回传摘要及页面能否打开，暂不上传/提交训练。服务持续运行，不应此时等待 RUN_EXIT_CODE；结束后才生成最终 report/哈希。

用户已执行 --start 并回传 ready：北京时间 2026-11-12 18:58:27 启动，run_id=`0f5c44ae-a3cb-40ec-8dec-a12763ec7897`，D 盘 evidence=`20261112T105827Z-manual-pr6cllqq`。助手读取原 ready/report，代码基线仍 clean 的 9b1165e、同一 uv.lock；API 45867、前端 49239、Worker PID 9474、max_steps=40，状态 local_manual_session_open。此时 real_training=false，人工/联合验收仍 pending。地址只属于本次存活会话，不作为后续固定端口。

下一步用户用 Windows 浏览器访问 `http://127.0.0.1:49239`，上传现有 E 盘克隆的 `E:\LLMCloud\docs\examples\train.jsonl`，名称建议 `laptop3060-smoke-20261112`；仅上传、刷新确认持久化，暂不提交训练。Windows 克隆样例为 628 字节（与 D 盘公开样例原始 SHA-256 同为 d0f8bbb4b1b99a8f7a125284d22506387eafd9bbd58a8dfaf5af865eea890162），与此前 Linux 625 字节样例不可直接声称原始哈希相同；后续按实际上传数据重新留证。该文件仅为三条工程格式样例，无正式审核/效果结论。回传页面成功消息、记录数和数据集 ID 或可见详情，用户实际页面可用性/上传尚待确认。

用户随后回传实际浏览器截图，数据集列表显示 `train.jsonl`、3 条、628 B，共 1 个。助手只读核对本轮前端代理的生产 HTTP 列表/详情：dataset_id=`86005705-657e-463f-b414-6fc7d1ecc527`，创建时间北京时间 19:01:34，实际 sha256=`d0f8bbb4b1b99a8f7a125284d22506387eafd9bbd58a8dfaf5af865eea890162`，与 E 盘 Windows 样例相同；实际名称保留文件名，不虚写为建议名称。当前任务数 0。截图与 HTTP 共同证明用户页面上传/列表可用；是否已经执行浏览器刷新仍未单独确认。小型观测证据存本轮 D 盘 `manual-upload-observation.json`。

下一步用户在“配置微调”选择本数据集，设置 LoRA Rank=4、Alpha=8、Dropout=0.05、目标 q_proj/v_proj；学习率 0.0002、轮数 1、batch=1、梯度累积=1、seq=128、日志间隔=1、seed=42。此会话内部 max_steps=40；公开配置不新增该字段。提交首个后使用“准备新的训练任务”提交同配置第二个独立任务，再看任务列表/详情的真实状态、Loss 和日志。若有提交错误/结果待确认则停止新增并回传，不把重试当作第二任务。助手不替用户 POST，不预先填写 GPU/排队/串行通过。

#### 用户页面提交两任务，真实 GPU/串行/源产物审计通过

用户实际任务列表截图显示首任务 COMPLETED，第二个 40/40 仍 RUNNING、提示等待产物校验/状态提交；这是当前产品正确保留的保存阶段，不把100%当作提前完成。助手随后只读 HTTP 查得两任务均 COMPLETED、错误为空，并在独立 CPU 进程调用原 verify_training_artifacts 审计 E 盘原始产物，未重复训练或修改任务。

| 项目 | 首任务 | 第二任务 |
| --- | --- | --- |
| task_id | bea69c0c-44bf-435f-892d-46ba5c16f431 | f56625e9-79c3-4004-8ddf-97df8617f7c0 |
| SQL开始（北京时间） | 20:42:18.918939 | 20:42:40.283161 |
| SQL结束（北京时间） | 20:42:40.264177 | 20:42:54.368430 |
| Trainer耗时（秒） | 19.528441828 | 12.638572753 |
| PyTorch峰值分配（字节） | 1235489280 | 1235882496 |
| 完成步数/真实train点 | 40/40点 | 40/40点 |
| 首步/末步Loss | 2.7157 / 2.3527 | 2.7157 / 2.3527 |
| manifest SHA-256 | 206aeb9d8f8f2a4794ae34952c9994687a16a53c3393aecb8204566a36e485e8 | 2bdeec5fe124302f7dd299e20fff56c26b4a59bcf66235cd9da986275884651c |

实际 config 两份均为 LoRA r=8/alpha=16（不是先前建议的4/8），dropout=.05、q_proj/v_proj、lr=.0002、batch=1、梯度累积=1、seq=128、logging=1、seed42、公开轮数1。内部 max_steps40 优先，原指标末步 epoch=13.3333；不是宣称3条数据仅训练一轮。540672可训练参数、总参数494573440。真实设备 RTX3060 Laptop/CUDA12.8/BF16（启动配置），无验证集，eval_loss=null；三条格式样例反复训练不作为效果提升证据。

第二任务创建于20:42:32.913950，处于首任务SQL执行区间内；第二任务实际开始晚于首任务结束0.018984秒。原 check_serial 返回 SQL区间不重叠，证明本轮两任务串行。两份原产物均12文件、96个Adapter张量、40条指标、artifacts_verified，代码clean 9b1165e/锁文件与基线一致、实际GPU分配有证据。每份生产HTTP返回的40个train点与原metrics逐条step/Loss一致；网页实际实时曲线仍须用户详情截图/观察确认，不能用HTTP核验替代。

本轮 D 盘保存 `live-training-observation.json` 与两份 `*-live-detail/metrics/logs.json`，全部为小型证据。原Adapter/数据/DB继续留 E。此轮独立审计 reload_verified=false 仅表示未重载这两份新产物；先前 L3 重载证据仍有效，不据此推断这两份已重载。

下一步用户分别打开两任务详情，确认40步、最终train Loss=2.3527、日志可见，截图留证；下载两个Adapter ZIP到 E 盘 `E:\LLMCloud\data\local-validation\browser-downloads`。通过后再按原 audit_download 安全解压和逐文件对比/独立CPU审计，不把源目录审计冒充下载包审计。当前不新增训练。单人本地操作不满足M3/M4双方联合验收，云部署/M5/正式效果实验仍未完成。

#### 两份浏览器下载 ZIP 的独立解压审计（已通过）

用户回传“下载完成了”；助手在指定 E 盘目录发现两份实际ZIP，下载时间为北京时间20:46:28/20:46:37。北京时间20:48:08～20:48:11，在新的独立CPU进程调用原 `scripts.m4_acceptance_support.audit_download`，对每个包核对严格源文件清单、条目类型/大小边界，安全解压到E盘Ubuntu本轮新UUID目录，再逐文件比较原始字节SHA-256并调用原产物校验器。不通过浏览器重新下载，不重训/不加载GPU，torch未导入；原产物和ZIP执行前后摘要均未变。

| 任务 | ZIP字节数 | ZIP SHA-256 | 解压审计 |
| --- | --- | --- | --- |
| bea69c0c-44bf-435f-892d-46ba5c16f431 | 18074681 | 00daf8631b735c8ec02fde8444cd2d7158c804f55854cdac109d446dc60a9f84 | artifacts_verified、exact_source_bytes=true |
| f56625e9-79c3-4004-8ddf-97df8617f7c0 | 18074681 | cd68b5508f8f9d7eac191cdf393787aedc3595401f2337ab6f0c0aa296ff20f2 | artifacts_verified、exact_source_bytes=true |

每份解压后原审计均为12文件、96个Adapter张量、40条指标、40步、review_status=unknown、reload_verified=false；后者表示本步没有重载，不是失败。本次真实浏览器下载/独立解压审计完成，不复用前面CPU合成ZIP的结论。

ZIP保留在 `E:\LLMCloud\data\local-validation\browser-downloads`。解压产物位于E盘Ubuntu本轮 `browser-download-audits/a1029cfd-a6ab-4437-966e-a04a61ad2274/<task_id>/<task_id>`，不复制到D。D盘只保存本轮小型 `browser-download-audit.json`，包含原路径/摘要/原清单一致性/审计结果；最终SHA256SUMS随正常结束生成。

下一步用户刷新网页、切换两任务详情，确认终态40/40、最终train Loss2.3527、曲线/日志可见并回传详情截图。尚无证据证明训练进行时实时曲线跨两轮刷新、训练期间下载、下载取消/切换、窄屏与双方共同操作，这些不提前标通过。补充页面观察后通过ready.stop_command正常结束，不按Ctrl+C；助手再核对最终capture/cleanup及证据清单。当前没有授权删除ZIP/运行数据，也不提交或推送。

#### 用户回传终态 Loss 曲线截图

用户提供两张裁剪图，均选中“Loss曲线”，可见训练Loss=2.3527、横轴1～40 Step、已完成说明与下载按钮。助手对照前面原始metrics/HTTP末值一致，确认终态曲线可见。两图裁剪均没有task_id，且没有展开运行日志，不能仅凭两张相同曲线断言每张分别对应某个任务，也不把终态图当作训练时多轮实时轮询证据。

原附件无修改复制为本轮D盘 `user-loss-view-1.png`、`user-loss-view-2.png`（均小于1MiB），复制后原/副本SHA-256一致；观测说明写 `browser-loss-observation.json`，后续随会话最终哈希清单归档。

最后由用户切到“运行日志”并回传一张可见日志/任务身份的截图，然后在另一Ubuntu终端执行本轮ready.stop_command：`touch -- '/home/l7/LLMCloud/data/acceptance/m4-07/0f5c44ae-a3cb-40ec-8dec-a12763ec7897/STOP_REQUESTED'`。启动终端保持打开，正常关闭后回传末尾结果；助手核对两份capture、cleanup_errors、下载临时区与最终哈希，再记本轮收尾结果。没有双方共同操作、实时轮询或未测交互的证据前，对应项仍保留未验收。

#### 最终页面日志证据与正常收尾（本轮基础端到端通过）

用户最终截图包含两任务列表均COMPLETED/40步，以及首任务 bea69c0c-44bf-435f-892d-46ba5c16f431 的明确身份、40/40、Loss2.3527、“运行日志”选中与第33～40步真实日志/参数核验内容，确认日志在实际页面可见。该原始PNG为1279693字节，作为单张截图的小型证据例外原样保存 `user-runtime-log.png`（不做图像压缩或编辑）；复制后哈希与附件一致。此前1MiB/文件限制继续用于脚本自动复制的运行文本，不因截图例外复制整份运行目录。

用户在另一个Ubuntu终端创建STOP_REQUESTED后，启动窗口正常返回 `local_session_closed_pending_review`。原报告最终时间北京时间 **2026-11-12 20:54:28.370932**；两任务均COMPLETED、两份capture/原GPU审计成功，gpu_execution_verified=true、real_training=true、cleanup_errors=[]。该原状态名称仅表示等待独立复核，不是错误；原report不改写为更强的验收结论。

助手独立核对API/Redis/Vite/Worker四个原PID均退出、前端49239/API45867端口无监听、下载临时区为空；短暂取得并释放既有同一Worker锁验证释放（未删除锁文件）。Linux运行副本仍clean。原最终 `SHA256SUMS` 共25项全部核验通过，清单自身SHA-256=`3526e90740523e8dd91f346d1e47e7833079d870d6502f277ccc53dd76afa8f6`。保留原清单与报告不变；后补日志截图/清理复核/本地总结通过独立 `SHA256SUMS.review` 覆盖归档。

本轮结论写入D盘 [local-review-summary.json](../../data/acceptance/b-review/laptop-3060/20261112T105827Z-manual-pr6cllqq/local-review-summary.json)：`local_basic_end_to_end_passed`。它只确认本次单人本地基础流程：环境/CPU契约→模型前向→L3两步训练/重载→用户网页上传→两个真实40步任务串行→终态曲线/日志→实际下载/独立包审计→正常关闭。截图、日志、摘要和清单留D；模型、数据、DB、Adapter、ZIP、解压内容及运行原件继续留E。用户现在可关闭终端，旧网页地址已停止提供服务。

**未覆盖或未收口：** 训练期间至少两轮真实轮询/五点现场可见、另一任务实际优化时下载、浏览器取消/切任务与窄屏交互矩阵、本轮两个40步Adapter的新进程重载、正式效果实验、M5在线推理、云端部署、M3/M4双方同步人工联合验收。L3已有的两步Adapter重载仍有效；不据此声称本轮新两份已重载。仅用3条样例重复训练不能证明模型效果提升。后续若推进完整M4验收，先补上述对应证据并与队友共同核对，不自动扩大到受保护代码修改。

本轮未修改队友业务代码/共享契约/依赖，未提交、推送或删除运行数据。远端fetch此前因当前127.0.0.1代理不可达失败，最新远端变化尚未确认；本地缓存origin/main一致不作为最新远端同步证据。

## 后续200步人工补测与语料交付

用户进一步确认基础功能先本地验收，上线前再租云；新会话run_id=`5421dcac-74c0-4af9-b5a4-d555384a5381`、D盘证据=`20261112T131702Z-manual-po1lbqv7`已于北京时间22:15:24正常结束。两个任务均200步，首任务累积1/第二累积8；17轮活非空请求跨32.593秒、200条原指标匹配、下载被第二任务真实优化器事件包围、显式3G取消/切换后重下、窄屏与日志观察、下载审计及清理均有对应证据。严格未测边界、HAR/截图和最终复核见 [补测记录](laptop-3060-m4-followup.md)，不把这次单人手动检查称为专用自动报告或双方共同验收。

随后按用户授权完成120条/30族中文云计算基础语料草稿与来源/审核侧车，按原工具生成96/12/12草稿划分；原扫描/冻结题精确匹配及保留族/可复现检查、Qwen tokenizer监督标签与256长度无截断检查通过。所有数据/审核正文在E，D仅说明/小结果。当前120条均待人工审核、没有正式训练，见 [语料交接](../data/cloud-basics-draft-2026-11-12-b.md)。

交接入口：[本次工作日志](../worklogs/2026-11-12-laptop-3060-local-validation.md)。
