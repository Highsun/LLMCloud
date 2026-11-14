# M5 本机真实推理验收（B，本轮已结束）

日期：2026-11-14（Asia/Shanghai）。按用户既有授权在 E 盘 WSL2 Ubuntu / RTX 3060 Laptop 6GB 分步验收，用户执行并回传结果，助手逐步核对。运行数据、模型、DB、Adapter 和完整浏览器证据保留 E 盘；D 盘只保留说明、摘要和小型检查日志。不修改 A 的实现，不自动提交/推送，不提前完成双方联合验收或云端部署。

最新状态：本轮已测本机范围核验通过并正常结束，详见 [结果与交接](../testing/laptop-3060-m5-results-2026-11-14.md)。CPU 411通过/1可选跳过、五项契约通过；真实compare/adapter、两类409、训练空闲后重试、取消/切任务及清理均留证。以下保留每步当时事实；本轮不等同整个M5、A/B联合验收或云部署完成。

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

已将测试修复和本记录提交为 280532a。WSL 原测试差异与提交逐字核对后，先单文件 stash 保全，再正常快进；确认新提交中的测试文件与该 stash 内容完全相同后仅删除本次重复 stash。WSL 已为 280532a clean，不改写历史或丢弃其他工作。

新增 B 独立 docs/testing/laptop-3060-inference.py 和对应 [操作说明](../testing/laptop-3060-m5-inference.md)。AST/只读 --check 通过；原 200 步会话两份 Adapter 再审计通过。--smoke-services 已运行成功：新目录 /home/l7/LLMCloud/data/acceptance/m5-inference/0ff5d1b7-7206-49e2-bb5a-4af2fb4e1a09，D 盘证据 20261114T074302Z-m5-vqaa0ehy，真实 API/Vite/私有 Redis 的 OpenAPI、422、404 和原任务/产物快照核对成功，source_unchanged=true、cleanup_errors=[]。此步未启动 Worker/GPU/生成；入口只做独立编排，不扩展 A 生产文件修改范围。正式人工会话待启动并单独记录。

## 网页推理人工会话：已启动，等待用户首个生成

独立入口和说明已登记为本地 d00349f，WSL 正常快进到同一 clean 基线。2026-11-14 15:46:41（Asia/Shanghai）启动本轮正式会话：run_id=83945e3f-36b1-4093-bb5a-445bed478638；E 盘 runtime 为 ~/LLMCloud/data/acceptance/m5-inference/<run_id>，D 盘证据目录 20261114T074641Z-m5-wklgq0uf，启动器保持 exec session 64114。

API=http://127.0.0.1:45605，网页=http://127.0.0.1:44433/#inference，生产 Worker PID=10698，ready_for_manual_browser。两份历史 Adapter 已在独立副本可查询；本轮尚未提交真实生成或新训练，不把服务 ready 写成推理通过。Windows 端只读检查网页 HTTP=200、已完成任务 total=2，与预期任务 ID 一致。

交给用户第一步仅为选择 8e5c706b-332e-4922-97bb-54e8d0cf2e68、compare、每份最大 64 token、开发提示词“请给出一个整理书桌的小建议。”提交一次，回传双回答/错误及截图；保留 Network 日志供后续 HAR 核验。暂不创建训练任务。正常结束使用 ready.stop_command，不使用旧会话地址或停止命令。

## 首次真实 compare 页面：已观察到双回答，待 HAR 核验

用户回传截图，任务 8e5c706b、compare、输入 38 token、每份最大 64；Adapter 显示“根据使用情况分类存放物品。”、实际 8 token；基础模型显示整理建议、实际 64 token（达到上限，末尾未完成不直接判为错误）。任务/revision 与指定基线一致，生成按钮恢复，无错误提示。截图原样保存本轮 D 盘证据 user-first-compare.png，131778 字节，源/副本 SHA256 一致；观察摘要另存 first-compare-ui-observation.json。

助手只读核对本轮 E 盘 Worker 日志：2026-11-14 15:50:29.047 接收 worker.infer，request_id=ba310e08-cc28-41f1-95ab-2e9dbfea976f；15:50:41.550 inference_finished，任务 ID 一致、执行耗时 12.476 秒，随后 Celery succeeded。检查时 inference_jobs 无保留记录，临时 inference 目录为空，与完成响应后删除短期结果/清理快照的代码行为一致。未重新发起生成或训练。

这确认真实 Worker 执行与用户页面双回答的观察；仍需原始 HTTP 请求/响应核对 task_id/mode/token/文本/request_id、状态和时序，截图不替代 HAR。下一步用户把当前 Network（带响应内容）导出到 E:\LLMCloud\data\local-validation\browser-evidence\m5-20261114\first-compare.har，若没有捕获该请求则先说明，不自动重跑。本轮尚未验证 adapter-only、GPU_BUSY、ARTIFACT_NOT_READY、取消/切任务和空闲后重试，也不宣称正式效果提升或联合验收完成。

## 首次 compare HAR：核验通过

用户保存 first-compare.har，助手只读解析原文件：495895 字节、23 请求，其中恰好 1 个推理 POST，SHA256=d7bcb9b3207173b16f562560e20c03234ac2308ba3b62712fe8de9bb1c01c924。请求四字段与指定任务、提示词、compare、64 token 一致；HTTP=200、application/json、Cache-Control=no-store。

请求时间北京时间 15:50:28.911～15:50:41.600921，HTTP 总耗时 12.689921 秒；X-Request-ID=ba310e08-cc28-41f1-95ab-2e9dbfea976f，与 Worker 的同任务 12.476 秒执行记录一致。响应模型/revision、input_tokens=38、base=64 token、adapter=8 token 及页面文本全部匹配，20 项核验均通过。小型摘要 first-compare-har-review.json 写入本轮 D 盘证据目录，原 HAR 保留 E 盘，不复制到 D 或 Git。

结论：本轮真实 HTTP→私有 Redis→唯一生产 Worker→已审计 Adapter/基础模型顺序生成→网页双回答的首个 compare 成功已有截图、HAR 和 Worker 交叉证据。未要求效果提升；这不是其他模式、资源忙碌或联合验收的替代证据。

下一步用户保持同任务/提示词/64 token，仅切换为 adapter 模式生成一次，确认只出现微调结果、基础模型面板清空并提示不生成；导出新 adapter-only.har，回复页面观察后核对 base=null 和真实 Worker 请求。不重复 compare、不提交训练。

## adapter-only：HAR 与用户页面观察通过

用户报告页面正常并保存 adapter-only.har。原 HAR=504275 字节、24 请求，SHA256=cd50b8ac98ceda1be5ff272624b24377b11cde451b999ea002da56013058cc43；包括原 compare 和恰好 1 个新 adapter POST。新请求 task_id、开发提示词及 64 token 不变，mode=adapter；HTTP=200、JSON、Cache-Control=no-store，响应 base=null，Adapter 8 token，文本与先前 compare 中的 Adapter 相同。

北京时间 15:55:38.563 发起，HTTP 耗时 4.322405 秒；X-Request-ID=1c623990-0ead-4dd9-9cc5-208b32339cab，Worker 同任务 received/finished/succeeded 全匹配，执行 4.094 秒且无 execution_failed。16 项核验通过，用户同时确认没有残留基础回答。小型 adapter-only-har-review.json 在 D 盘，原 HAR 留 E。尚未验证资源忙碌、未完成任务错误及取消。

下一步由用户通过正式训练页面使用已复制的 3 条工程样例提交一次新的真实训练（r8/alpha16、batch1、累积8、seq128、logging1、内部200步），训练期间用旧完成任务发推理，记录 GPU_BUSY；训练完成后手动重试应成功。使用实际新训练/状态与原指标时间核对，不能拿旧任务状态或 mock 代替本轮占卡证据。

只读确认本轮训练数据集为 train.jsonl，3 行/628 字节，dataset_id=63d077a8-0c4b-44b6-acc6-834ce8621cb6。为同一真实训练补核对 ARTIFACT_NOT_READY，助手启动限时 10 分钟的本轮检查（exec session 1538）：只轮询当前隔离任务列表，发现非历史任务且 PENDING/QUEUED/RUNNING、current_step<10 时对该未完成 ID 发一次推理请求，预期 409/ARTIFACT_NOT_READY，结果写 unfinished-task-api-review.json。该检查不提交训练、不改任务状态、不重试 POST；截至交给用户时仍在等待，尚不能记通过。用户自行从网页对旧完成任务检查 GPU_BUSY 和空闲后重试，随后导出 busy-retry.har。

## 真实训练占卡、两类 409 与空闲后重试：通过

用户新任务完整 ID=2083a682-386d-4064-9025-c1af79998ded；HAR 中恰好一次训练 POST=202，配置与 SQL 一致（r8/alpha16、batch1、累积8、seq128、logging1 等），原数据集未改变。SQL 运行时间为北京时间 16:02:29.762309～16:03:59.393032，200/200 完成；Trainer 实测 87.852405996 秒、峰值分配 1237853184 字节、final_loss=.0004、eval=null。新产物原 CPU 审计 12 文件/96 张量/200 原指标通过，训练基线 d00349f clean；不把工程样例 Loss 当正式效果。

用户忙提示截图原样保存 user-gpu-busy.png（11979 字节），原/副本哈希一致，请求编号 9bfd859d-b2e4-4afe-a7f6-77dc7e7d85ba。busy-retry.har=2072329 字节/98 请求，SHA256=a2e6735b9700e5d6f37b438638ead9b9ada73a57ee90166b646f85ab12589adf，原件在 E。实际有两次 GPU_BUSY，不套用最初“一次”的操作预期：16:02:47.364（11.789ms，原优化器26/27步之间）及 16:03:38.445（9.444ms，152/153步之间），均 HTTP409、同一旧完成任务/提示词/adapter/64 token，均无 Worker 推理派发记录。

新训练结束后，用户原样重试于 16:04:16.573 得到 200，HTTP 耗时 3.706097 秒，base=null、Adapter 8 token；request_id=08ee172d-fe03-4844-aaac-d415d1ceb51d，Worker 匹配执行 3.464 秒并成功。当前无保留推理记录、临时 inference 目录为空。摘要 busy-retry-har-review.json 的 10 项整体核验及两次各 5 项核验全部通过；该 HAR 含此前 compare/adapter 成功，不冒充新增重复场景。

助手的限时检查在 16:02:29.789 对新任务（RUNNING、current_step=0）仅发一次真实 HTTP 请求，47.888ms 得到 409/ARTIFACT_NOT_READY，request_id=6fe33c39-5ecd-4798-a742-d53bee295d55，摘要 unfinished-task-api-review.json；检查进程已结束。此项是实际 API 错误码核验，生产页面只列完成任务，未用假任务触发页面；ARTIFACT_NOT_READY 页面渲染沿用先前 mock 测试，不声称本次有其真实页面截图。

后续仅剩本轮真实等待中的停止等待、切任务隔离与再次生成，以及正常结束/锁与临时区清理。用户将同一开发提示词切到 compare/256 token，做一次停止等待和一次切到 8da5af9b 任务，再对新选择生成成功；增加输出预算只用于给正常人工操作留出观察时间，不注入延迟、不新建训练。HAR另存 cancel-switch.har，真实时序与用户观察回传后核验。

为辅助区分浏览器停止等待与服务端清理，助手开启本轮限时只读观察：每 0.2 秒读取 inference_jobs 的 id/task_id/state/cancelled，仅在状态变化时写 E 盘 runtime/inference-lifecycle-watch.jsonl；不记录提示词/回答，不发 HTTP POST，不改业务状态。观察到 3 个新推理且空闲 2 秒、收到 STOP_INFERENCE_WATCH 或满 10 分钟时退出，结果仍需 HAR/用户观察共同解释，不自行判为取消验收通过。

## 真实取消、切任务与后续成功：核验通过

用户报告取消/切任务正常并回传新任务双回答截图；原图保存 user-final-task-compare.png，原/副本哈希一致。cancel-switch.har=2102487字节，SHA256=b74171c79240717af843a582fd925daf779447bc4ffc23096ee5341530b47001。实际两次取消请求均为旧任务 adapter/64（非原建议compare/256），分别在16:14:58.754、16:15:05.356发起，2.541280秒/1.658274秒后net::ERR_ABORTED，无响应文本。此前另有一条16:14:25.970的旧任务成功adapter请求，独立记录不算取消。

只读观察共9条变化，关联取消任务dc89c68c-da9c-405f-a515-b6d0242fb206和be95bdc7-8a45-4cf1-b18c-f44fea1fa545：均已RUNNING、捕获cancelled=true、Worker以GenerationInterrupted停止并完成清理，浏览器取消至记录清空约0.625224秒/1.128143秒。Worker内部记录INFERENCE_TIMEOUT是本实现复用的中断码，此处不是90秒HTTP超时。两次取消分别由停止等待与切任务触发依据用户操作报告，HAR/状态日志不额外虚构点击轨迹。

最终16:15:39.224对8da5af9b-56ab-4bb3-afd7-fc8d1d56489c发compare/64，HTTP200约5.931660秒，base64/adapter11，微调回答“根据使用情况设置书桌储物格。”；request_id=8cc97d6f-b10d-425a-a34e-f74e110a58af，Worker执行5.865秒。结果身份/文本/参数与用户截图一致，用户确认旧结果未覆盖。cancel-switch-har-review.json的全部核验通过；观察进程25812已正常结束。

## 正常收尾与最终独立复核：通过

确认无在途训练/推理后，按STOP_REQUESTED协议正常结束本轮，exec session64114退出0。原report=manual_session_closed_pending_review、cleanup_errors=[]、source_unchanged=true；保留原report，不将启动器的静态人工核验标记改为自动通过。

独立核对API10659/Worker10698/Vite10668/Redis10662均退出，44433/45605无监听；worker.lock可取得并释放且原文件保留，推理活动记录0，inference/downloads临时区空。三个训练任务均COMPLETED，原18项SHA256SUMS全部一致；后补independent-final-review.json给出passed_for_tested_local_scope，并新增SHA256SUMS.review覆盖后补审核，不修改原清单。

原HAR、DB、模型和Adapter保持E盘；D盘只保存摘要、小型日志及截图。网页地址已关闭，后续需新会话。原本地提交280532a/d00349f未推送；本节新增结果文档和日志更新尚未提交。完整结果、证据摘要和未测范围见 [结果与交接](../testing/laptop-3060-m5-results-2026-11-14.md)，不标整个M5、A/B联合验收、正式效果或云部署通过。

## Git 交付

上述本地未发布状态之后，用户明确要求“提交到远程仓库，并告诉怎样关闭网站”。本轮只提交最终结果说明和本日志的更新，将已验证的280532a/d00349f及最终说明正常推送到既有B分支feature/m4-observability-ui，不更新main、A契约分支或共享里程碑。提交前fetch成功，远端B分支仍为e5be9fb、本地领先3项，无分叉；没有新增A修复。

原HAR、截图/完整证据、模型、DB和Adapter不入Git，不新增忽略例外或workflow。关闭方法补入结果说明；本轮已正常停止，未来沿用每轮ready.stop_command。具体交付SHA和推送成功状态以本轮Git记录及远端核验为准。
