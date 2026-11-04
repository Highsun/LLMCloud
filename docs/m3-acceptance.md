# M3-07 真实服务验收与两人交接

更新：2026-11-04。A 的真实 GPU 自动验收已通过；B 的独立异步证据/既有任务页面复核及前端修复已在 61d8703 交付，经 A 本机回归后合入。双方从新上传到实际 GPU 完成的同步人工联调尚未执行，M3 保持待共同验收；M4 可先规划。依据：[A 原始运行](worklogs/2026-11-04-m3-07-a.md)、[B 独立复核](worklogs/2026-11-04-m3-07-b.md)、[A 正式审查](worklogs/2026-11-04-m3-07-a-review.md)。

## 当前还差哪一步

B 的材料接收、异步复核、真实快照页面检查、手机失败码修复和独立日志已完成，A 已接受该交付。剩余是原计划要求的双方同步人工端到端操作：约定共用服务/GPU 时段，由 B 操作页面、A 配合实际服务（可同机或共享屏幕），完成新上传、参数配置、连续提交两任务、观察排队/完成、原任务查询及刷新/筛选/详情，并记录新任务 ID、UTC 时间和双方实际操作结果。

既有 9 项故障/恢复真实证据已核对，无需仅为同步操作重复整套故障注入；未完成同步操作前，不把既有快照页面或原自动 trace 记为这一步已经通过。该未完成项不阻塞 M4 的接口与分工规划。完成后再共同更新阶段状态。

## A 的执行入口

在 WSL/Linux 仓库根目录，确认同一 GPU 没有其他手工训练/重载，服务端使用共用的 LOG_DIR/worker.lock：

```bash
uv sync --locked --extra training
uv run --locked --extra training python scripts/check_m3_acceptance.py --gpu
```

需 redis-server、Node/npm、frontend/node_modules 和可运行的 Playwright Chromium。初次模型准备沿用 [固定缓存说明](model-cache.md)，本入口只核验既有离线缓存，不自动下载模型。--gpu 是实际训练开关；未指定时拒绝运行。--run-dir 可选，必须是尚不存在的新目录。默认在忽略的 DATA_DIR/acceptance/m3-07/{UUID} 保留所有证据，失败也保留，不能覆盖旧运行。

主入口 scripts/check_m3_acceptance.py 启动私有 Redis Unix socket（含独立结果 DB）、隔离 SQLite/数据/输出、实际 FastAPI、Vite 和原生产 Worker。训练复用原 Trainer/固定 0.5B revision，API 的内部步数上限按场景切换，公开请求仍只含 dataset_id/config。LOG_DIR 沿用当前主机配置，以与其他实际 Worker 竞争同一物理 GPU 的锁；任务日志 UUID 独立。原业务 DB/队列不参与。

scripts/check_m3_browser.mjs 使用实际页面上传数据、配置并连续提交两任务，核对实际状态和桌面/390px 布局，保存截图/trace；没有 route 拦截、Publisher 替身或 /__test__ 控制。现有 npm run test:e2e 继续承担 M1/M3-05 的受控回归，不能替代本入口。

scripts/m3_acceptance_worker.py 仅供受控故障：在指定任务的真实 SQL before_commit/after_commit 或成功清单发布边界注入异常。生产 worker/tasks、启动钩子和 HTTP 应用不增加故障开关/控制路由。此类结果必须写明注入方式，不称为自然故障或真实 OOM。

## 自动验收范围

| 场景 | 必须记录的实际证据 |
| --- | --- |
| 浏览器上传/两任务成功 | 实际 HTTP/Redis/Worker/Qwen LoRA，独立任务/产物；UTC 训练区间不重叠，实际轮询至多一项 RUNNING，真实 GPU 峰值/指标/审计清单 |
| 请求/消息去重 | 原键 200、受控重复消息 skipped；任务时间/状态不变，不再次训练 |
| 完成回复丢失 | 真实 after_commit 注入后 SQL 仍 COMPLETED，产物有效，不被 fail 覆盖 |
| 有效产物与 SQL 回滚 | 真实 before_commit 注入后保留 RUNNING/有效清单；停 API/Worker，check/apply/check 恢复 COMPLETED |
| 保存失败 | 实际 LoRA 后注入清单发布异常，FAILED/ARTIFACT_WRITE_FAILED，有诊断/部分产物而无有效成功清单 |
| GPU 中断和排队遗留 | 实际优化器更新后仅杀本入口的 Worker；保留真实进度/文件，停机对账得 WORKER_INTERRUPTED 和 TASK_ABANDONED |
| 旧队列残留 | 对账后重启实际 Worker，终态消息 skipped，不重训 |
| 非法数据/缺缓存 | 仅篡改隔离数据文件以触发真实哈希校验；独立空缓存触发 MODEL_NOT_CACHED；产品不自动下载 |
| 生产页面失败/恢复 | 原页面查询真实 FAILED/恢复 COMPLETED，错误码/步数/进度正确，M4/M5 操作仍禁用 |

输入是显式工程格式草稿，证明服务链路，不是已人工审核的正式语料或效果提升实验；冻结评测题不参与训练/调参。COMPLETED 指训练保存与产物审计，不承诺每项任务已经生成或质量提升。

## 队友复核清单与接续

以下 1/2/4/5 的独立复核部分已由 B 日志及 A 审查确认；第 3 项中从新上传到真实 GPU 完成的同步人工操作仍待安排。

1. 同步 A 推送的最新 main，阅读本文件、当次 A 工作日志及生产 Worker/前端约定；保留自己的未提交改动并正常 merge，不覆盖 A 的脚本/后端。
2. 复核实际运行 report.json 的任务 ID、配置、UTC 起止时间、真实成功/失败和恢复结果；核对截图/trace 是生产服务，而不是 frontend/testing/serve_task_api.py。原数据/权重/DB/原始日志不提交 Git。
3. 在约定时段配合实际页面操作：上传、配置、连续两任务、原任务查询、刷新/筛选/分页、完成和失败详情；桌面及窄屏都检查。若 B 无法直连 A 的 WSL 服务，先异步复核 A 生成的证据，再约定同机/可访问环境的人工操作，不要求 B 在本机重跑 GPU。
4. 发现页面问题后，先反馈实际 task_id、request_id、操作步骤和预期/实际；只改 frontend，新增独立测试及 YYYY-MM-DD-m3-07-b.md 日志，附检查结果和未验收项。涉及共享 HTTP/Worker 语义先与 A 核对，不复制 SQL/Trainer 或扩大 M4/M5 范围。
5. 在独立日志中写明已复核哪些真实证据、人工操作是否完成、剩余问题；共同核对后才将 M3 全阶段完成项收口。GPU/共用服务测试安排一次中途同步，阻塞约 30 分钟时反馈具体问题。

## 本次真实结果与复核入口

原 report/ZIP 固化于 B 复核之前，teammate_evidence_review=pending 是打包时的历史标记；保持原字节和校验值，当前复核进度以 B 日志及 A 审查为准，不回写原证据以伪造新运行。

本机运行目录为 `data/acceptance/m3-07/dbdffce3-e453-46bf-b962-d66a424d7199/`，不随 Git 同步。`report.json` 的 status=passed、gpu_execution_verified=true，teammate_evidence_review=pending。训练代码提交 fe5c87e，四份有效成功清单均记录 working_tree_dirty=false。实际执行为 UTC 09:55:32–09:57:06，两项正常任务分别在 09:55:34.823265–09:55:58.927595、09:55:58.937114–09:56:03.969387 训练，彼此不重叠。

四份有效 Adapter 都完成 2 个优化器更新步，独立 CPU 审计通过；另有一次真实训练后的受控保存失败。实际 GPU 中断发生在第 1/64 步，停机对账后保留该进度和文件，排队任务标记放弃；实际 SQL 完成前回滚留下的完整成功产物已恢复为 COMPLETED。保存/SQL 异常是明确注入的受控故障，不是自然故障或 OOM。

WSL 无头浏览器最初缺少中文字体，原始截图显示方框。已在 /tmp 临时补齐 Noto CJK 字体，并重开实际持久化任务生成可读证据；此操作不重跑 GPU、不改变原训练时间/产物。B 优先查看 `browser-success-cjk/`、`browser-recovered-cjk/`、`browser-saving-failed-cjk/`、`browser-interrupted-cjk/`、`browser-invalid-dataset-cjk/` 中的 desktop.png、mobile.png 和 trace.zip；原 browser-success/result.json 仍保存最初页面上传、连续提交及真实训练轮询证据。上述目录共保留 20 张截图和 10 份 trace，半数为补字体后的只读复查。

需要重新查看已通过运行时，可以使用已同步好依赖的 Python 环境执行（--no-sync 避免重整训练环境的 extras）：

```bash
uv run --locked --no-sync python scripts/check_m3_acceptance.py --review-run data/acceptance/m3-07/dbdffce3-e453-46bf-b962-d66a424d7199
```

该入口只启动实际 API/Vite 读取本机既有隔离库，不启动 Redis/Worker/GPU，不能当作新一轮训练验收。仍需 Node/Chromium 和中文字体；如使用临时字体配置，通过 FONTCONFIG_FILE 指定。另一台机器先按下节接收证据包，再复核；B 完成独立日志后再共同更新阶段完成状态。

## 跨机器证据交接

2026-11-04 更新：最初材料只在 A 的本机且被 Git 忽略；用户随后明确要求将下列 ZIP 和校验文件提交 GitHub，方便 B 直接拉取。本次授权仅覆盖这两个固定文件，原完整运行目录及解压内容继续保持忽略。原运行服务已关闭，report.browser_url 是历史临时地址，当前没有在线验收地址。

同步最新 main 后，仓库内文件路径为：

```text
data/acceptance/handoffs/
  m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip
  m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip.sha256
```

ZIP 大小 6,672,377 字节，约 6.4 MiB；SHA-256：

```text
dba657710cbc2f0d92207c6ce8cb2593efe0474815146bd5d51b2de0e6bae62a
```

按本次用户授权，仅对上述两个文件执行精确 git add -f，未扩大 .gitignore 规则。ZIP 保持原字节和原校验值；包内说明保留打包时的交接背景，当前 Git 交付方式以本节为准。拉取材料不等于 B 已完成复核。

包内有 63 个文件：原 report.json、20 张截图、10 份 trace、浏览器 result/submitted、SQLite 一致性快照、原训练清单/指标/配置/失败诊断副本，以及 README/handoff.json/SHA256SUMS。快照有 9 个真实任务（4 成功、5 预期失败），无用户记录。源报告和浏览器/训练元数据逐字节复制；SQLite 使用只读源库 backup 得到快照，打包未修改原验收目录。

包内不含数据集正文、模型缓存、Adapter/tokenizer 权重、checkpoint 或原始服务日志。trace 包含实际公开工程格式样例的请求内容。B 可以用本包核对记录和既有任务页面；若要独立重做权重完整性审计，仍需另行交接原完整成功产物目录，不能把本包的 metadata/outputs 当作完整训练 bundle。

B 保留自己的未提交改动并按协作规则同步；以下适用于工作区干净且可快进的 checkout。从仓库根目录运行：

```bash
git pull --ff-only origin main
(cd data/acceptance/handoffs && sha256sum -c m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip.sha256)
```

再从仓库根目录解压到被忽略的目录：

```bash
mkdir -p data/acceptance/imported
python3 -m zipfile -e data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip data/acceptance/imported
cd data/acceptance/imported/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review
sha256sum -c SHA256SUMS
```

先阅读包内 README、report.json、handoff.json；截图优先看 browser-*-cjk，真实上传/连续提交/轮询过程看原 browser-success 的 result 和 trace。在已有前端依赖的 frontend 目录可以运行 `npx --no-install playwright show-trace <解压目录绝对路径>/browser-success/trace.zip` 查看本地 trace；没有依赖时先按项目入口安装，离线阅读 JSON/截图本身不依赖前端环境。

如要运行 --review-run，请先复制解压目录为工作副本，再按上节入口传入该副本路径。此命令会更新报告/截图并自动关闭服务，不提供持续在线服务。A 已用本包全新解压的副本、CPU 环境和空模型缓存实际跑通五类任务页面复查，未使用 Redis/Worker/GPU、数据集正文或模型权重。原 ZIP 和原验收目录保持不变。

B 已完成代码/CPU 检查、接收校验和异步证据/既有任务页面复核，详见 [B 日志](worklogs/2026-11-04-m3-07-b.md)。从新上传到真实 GPU 完成的同步人工操作仍需双方约定服务/GPU 时段。打包背景见 [交接日志](worklogs/2026-11-04-m3-07-evidence-handoff.md)，当前判断见 [A 审查](worklogs/2026-11-04-m3-07-a-review.md)。
