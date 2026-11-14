# M5 本机真实推理验收（B，进行中）

日期：2026-11-14（Asia/Shanghai）。按用户既有授权在 E 盘 WSL2 Ubuntu / RTX 3060 Laptop 6GB 分步验收，用户执行并回传结果，助手逐步核对。运行数据、模型、DB、Adapter 和完整浏览器证据保留 E 盘；D 盘只保留说明、摘要和小型检查日志。不修改 A 的实现，不自动提交/推送，不提前完成双方联合验收或云端部署。

最新状态：用户随后明确授权本侧修复这一项过时契约测试；已完成单文件修正并由助手在 WSL 复跑，CPU 411 通过/1 可选跳过、五项契约全通过。以下保留修复前各步的事实，具体修复与新证据见末节。

## 代码同步：已确认

- D 盘 B 分支已从 e5be9fb 快进到队友 0041b8b（feat: serve M5 inference through the GPU worker）。
- 用户已在 Ubuntu-22.04 的 ~/LLMCloud 从 D 盘本地 Git 获取代码，新建 test/m5-inference-3060-20261114。
- 用户回传 git status 只有分支头，无未提交文件；git log -1 为 0041b8b。
- 队友提交包含推理 HTTP、SQLite 短期请求、Worker 调度、产物快照与真实模型生成；这次提交没有新增测试或专用运行交接记录，代码存在不作为验收通过证据。

## 基础检查初轮：存在一项过时断言，未通过

复用 docs/testing/laptop-3060-cpu.sh，LLMCLOUD_TEST_REPO 指向 ~/LLMCloud，LLMCLOUD_REPORT_REPO 指向 D 盘仓库。脚本禁用 CUDA 可见设备、模型联网和可选浏览器检查，运行现有 unittest 及五项契约漂移检查。CPU/HTTP 测试使用隔离临时资源，不启动生产 Worker，不使用实际模型生成，不改既有业务数据库。

用户回传本轮结果，助手已读取原 metadata/results.tsv/cpu-tests.log/summary：基线 0041b8b、工作区 clean；2026-11-14 15:18:53～15:19:27（Asia/Shanghai），unittest 412 项，410 通过、1 失败、1 可选浏览器跳过，耗时 30.617 秒；五项契约检查全部退出 0，整体 RUN_EXIT_CODE=1，不标为通过。

证据目录：data/acceptance/b-review/laptop-3060/20261114T071853Z-cpu-lnJ1Ns。SHA256SUMS 所列 9 文件逐项核验全部一致，原证据不改写。

唯一失败为 tests/test_task_contract.py:305，test_runtime_app_exposes_tasks_observation_and_download_without_inference 仍断言运行时路径不能包含 /inference。0041b8b 按 M5 任务新增该接口，旧断言与新阶段需求冲突；本轮不是 CUDA、缓存或依赖加载错误。前面的 tasks/详情/metrics/logs/adapter 路径断言已通过。

该测试属于 A 的契约测试范围，初次定位时只记录并交接 A，不删除、跳过或改写。建议更新测试名称和阶段预期，明确核对 POST /api/v1/inference，并保留现有任务端点断言；建议补齐推理请求/响应、两种 409、调度取消/超时的独立 CPU 检查。后续用户授权的本侧修复见末节；不会把其余旧测试成功当作新增推理完整覆盖。

CPU 旧断言仍待 A 修复、复跑。独立缓存和显卡前向探测不依赖该 HTTP 路径断言，可先核验模型环境，不视为 CPU 失败项已经解决；平台网页会话在基础问题收口后进行。

## 离线缓存：已通过

用户已回传 2026-11-14 15:22:30（Asia/Shanghai）的 check 结果，助手核对原 summary/metadata：0041b8b、clean；status=cache_verified，model/tokenizer revision 同为 7ae557604adf67be50417f59c2c2f167def9a775，chat_template_sha256=cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f；9 个模型缓存文件，总计 999602607 字节。命令和日志退出码均为 0。

证据目录 data/acceptance/b-review/laptop-3060/20261114T072229Z-model-check-g2s0HR，SHA256SUMS 所列 4 个证据文件全部一致。本步未下载、未加载 GPU、未训练或生成。远端复查成功，队友暂未推送新修复。

## GPU 前向：已通过

用户回传 2026-11-14 15:24:37（Asia/Shanghai）的 gpu 结果；助手核对原 summary/metadata 和 SHA256SUMS 所列 4 文件，均一致。基线 0041b8b、clean；RTX 3060 Laptop、CUDA runtime 12.8、torch 2.9.1+cu128、transformers 4.57.6，BF16；494032768 参数、34 输入 token、logits shape=[1,34,151936]，有限值检查通过。

PyTorch 峰值分配 1042360320 字节，前向探测耗时 1.7445603799999958 秒；该数值不是整卡显存占用。证据目录 data/acceptance/b-review/laptop-3060/20261114T072427Z-model-gpu-TgJccp；命令/日志均退出 0。此步没有 Adapter 加载、自回归生成、训练或网页推理。

远端复查成功，A 暂无新增修复。只读确认 WSL 工作区 clean，原 L3 任务 166cebf8-456c-4828-8fc5-df7db44585fc 的产物仍位于 data/local-validation/laptop-3060/<task_id>/data/outputs/<task_id>/manifest.json。

## 独立进程 Adapter 重载与生成：已通过

用户执行 laptop-3060-artifacts.sh reload 166cebf8-456c-4828-8fc5-df7db44585fc，2026-11-14 15:27:12（Asia/Shanghai）回传 passed，命令/日志均退出 0。助手核对原 summary/metadata，0041b8b、clean；SHA256SUMS 所列 4 文件全部一致。

证据目录 data/acceptance/b-review/laptop-3060/20261114T072702Z-reload-dhqAps。新进程 PID=5210，任务/固定模型 revision 一致，Adapter 的 96 个张量实际加载匹配。manifest 前后不变，SHA256=585466210d7197e7aa9fb5128dc66a32f2e8cc08dbb22d219d630d59bfd5e72b；adapter SHA256=d3e1994247faf4bb21bea2f875c0196f68e498493eb52e5e97b2f37e249083a2。

BF16、贪心解码，开发提示词“请给出一个整理书桌的小建议。”，38 输入 token，32 生成 token（达到设置上限，输出不要求完整收尾），耗时 3.8606075039999723 秒，PyTorch 峰值分配 1010424320 字节。实际文本保留原小型证据，不把整理建议当作效果评测；review_status=unknown，本次未重训。

此步确认修改后的 Adapter 重载/真实文本生成路径可用，不验证 base/adapter compare 双回答、HTTP/API、GPU 调度、训练忙碌或取消。远端再次 fetch 成功，A 尚未推送旧测试断言修复；CPU 阶段仍未通过，下一步需 A 更新 tests/test_task_contract.py 的阶段预期并复跑基础检查，然后进行独立平台网页会话。

## 用户授权修复旧测试及复跑：已通过

用户明确要求“这部分修复我可以做嘛？你把这部分做了吧，队友今天没空做这个”。据此仅修改 tests/test_task_contract.py 中的运行时接口测试：重命名去掉 without_inference；保留 tasks/详情/metrics/logs/adapter 原断言，改为要求 /api/v1/inference 仅有 POST，并核对请求和 200 响应分别引用 InferenceRequest/InferenceResponse。没有删除或跳过测试，没有修改生产后端、调度、共享 Schema 或其他测试。

仓库外 AGENTS.md 已记录这次单项边界授权。同步 WSL 前核对 test/m5-inference-3060-20261114 为 clean、HEAD=0041b8b、原测试文件与 HEAD 一致，随后只同步该测试文件。当前 D/WSL 均保留未提交修复，不伪装成干净提交基线；不提交或推送。

- 对应 test_task_contract.py 20 项全部通过，耗时 0.537 秒。
- 全量 CPU 回归 412 项：411 通过、1 项原有可选浏览器跳过，无失败；耗时 31.396 秒。五项契约检查及日志退出均为 0，总 RUN_EXIT_CODE=0。
- 新证据目录 data/acceptance/b-review/laptop-3060/20261114T073304Z-cpu-npQ0l4，2026-11-14 15:33:04～15:33:38（Asia/Shanghai）；原 9 项 SHA256SUMS 核验全部一致。metadata 如实记录 0041b8b + working_tree_dirty=true，未提交差异仅 tests/test_task_contract.py；旧失败报告保留不改。
- 没有重新执行 GPU 检查/训练，也没有启动平台会话；此前缓存、GPU 前向和独立重载证据仍归属原 0041b8b clean 基线。

本次消除了基础测试的过时断言阻塞，不代表新增推理完整行为已有 CPU 覆盖或网页验证通过。后续仍需两种模式真实生成、训练忙碌/空闲后重试、取消/切任务及清理证据。平台 launcher 要求运行工作区 clean，开始会话前需按用户对应授权将已测试修复登记为提交基线；不得为绕过该要求删除修复或放宽入口。

后续顺序：准备干净测试基线 → 隔离真实推理网页会话 → 真实生成/对照 → 训练忙碌/空闲后重试 → 取消、切任务与清理。每步结果单独记录，当前尚未执行网页端 GPU 推理或 base/adapter 对照生成。

## 进入网页验收准备

用户随后要求“执行下一步”，按上一步说明将已验证的测试修复和本记录登记为本地提交，正常同步 WSL 测试分支，不丢弃已测差异，不更新远端 main。接下来新增 B 独立 M5 启动入口：从上一轮 200 步会话的数据目录只读备份 DB，按哈希复制 datasets/outputs 到 E 盘新目录，不复制模型；保留两份真实完成记录的原训练提交身份，不将其改写为本轮训练。

服务使用新 Redis Unix socket、新队列和新数据目录，沿用共同 Worker 锁与现有生产服务生命周期。启动入口仅做临时隔离编排，不修改 API、SQL、Worker、共享类型或原 M4 工具。先做不启动 Worker/GPU 的服务冒烟，随后由用户在真实网页提交生成并回传证据。
