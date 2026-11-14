# M5 本机真实推理结果与交接（B）

日期：2026-11-14（Asia/Shanghai）。本轮已正常结束，以下实际测试范围通过；不代表整个 M5、M3/M4 双方联合验收、云端部署或正式效果实验完成。

## 基线与环境

- 队友推理实现：0041b8b。用户授权本侧修正旧契约测试，提交 280532a；独立隔离入口/说明为 d00349f。网页会话在 WSL 分支 test/m5-inference-3060-20261114、d00349f clean 上运行。本轮用户已授权将这些本地提交及最终结果正常推送到既有 B 分支 feature/m4-observability-ui，交付结果以远端提交记录为准，不更新 main 或 A 的契约分支。
- Ubuntu-22.04 / RTX 3060 Laptop 6GB；PyTorch 2.9.1+cu128、CUDA runtime 12.8、transformers 4.57.6、BF16。
- Qwen2.5-0.5B-Instruct 模型和 tokenizer revision 同为 7ae557604adf67be50417f59c2c2f167def9a775。模型缓存约 1 GB，9 文件已离线校验。
- run_id：83945e3f-36b1-4093-bb5a-445bed478638。使用真实生产 API/Worker/前端、单 solo Worker 和实例锁、私有 Redis/新队列。
- 从 11/12 的本机 200 步会话只读备份数据库、按哈希复制 datasets/outputs 到 E 盘新目录。旧任务 8e5c706b / 8da5af9b 保留原训练提交 9b1165e，不伪装为本轮训练；原 DB/Adapter 未改变，没有复制模型。

## 已验证结果

| 范围 | 实测与证据 | 结论 |
| --- | --- | --- |
| CPU/契约 | 旧 without_inference 断言修正为检查 POST 与正式请求/响应 Schema，原任务端点断言保留；20 项专项通过；全量 412 项运行，411 通过/1 原可选浏览器跳过，五项契约通过 | 基础回归通过；未删除或跳过失败测试 |
| 独立 GPU 与重载 | BF16 真实前向通过；原两步 Adapter 在新进程加载，96 张量匹配，32 token 生成成功，产物不变 | 独立模型执行可用 |
| 网页 compare | 8e5c706b，HTTP200，输入38/每份最多64，base64/adapter8；HAR、截图、Worker 同请求编号；HTTP 12.689921秒 | 双回答真实链路通过 |
| 网页 adapter-only | HTTP200，base=null，Adapter8；用户确认基础面板清空；HTTP 4.322405秒，Worker4.094秒 | 单模式通过 |
| 未完成任务 | 新任务刚 RUNNING/0步时对其 ID 发一次接口检查，409/ARTIFACT_NOT_READY，47.888ms | 真实 API 错误码通过；页面渲染证据来自此前 mock，非本轮真实截图 |
| 训练占卡 | 两次409/GPU_BUSY，分别落在实际26/27和152/153优化器事件之间，HTTP约11.789/9.444ms；忙请求未派发 Worker | 非加载期/非 mock 的占卡反馈通过 |
| 空闲后重试 | 同一个旧完成任务、相同提示词/adapter/64；新训练完成后用户重试，200、Adapter8，HTTP3.706097秒 | 手动重试成功 |
| 取消与切任务 | 两次 net::ERR_ABORTED；只读观察捕获相应 RUNNING→cancelled=true→记录清空，Worker GenerationInterrupted 后收尾；取消到记录清空约0.625/1.128秒 | 浏览器取消和服务端清理均留证；两次触发动作分别按用户报告为停止等待/切任务 |
| 切换后生成 | 最终选中任务与响应均为8da5af9b，compare/64，base64/adapter11，HTTP200约5.93166秒；用户确认旧结果没有覆盖，截图一致 | 新任务结果隔离、后续继续使用通过 |
| 正常结束 | 原证据18项哈希全通过；3任务均COMPLETED；API/Worker/Vite/Redis PID退出，44433/45605无监听，锁可重新取得并释放且锁文件保留，推理记录无活动，inference/downloads临时区空 | 本轮收尾通过 |

取消组实际请求是 adapter/64，最后成功请求是 compare/64；没有使用原建议的256 token，按真实HAR记录。组内还有一次取消前成功的旧任务 adapter 请求，不将其冒充已取消。Worker 对客户端取消沿用内部 INFERENCE_TIMEOUT/GenerationInterrupted 记录，本轮并未触发90秒HTTP超时。

## 新训练任务

task_id=2083a682-386d-4064-9025-c1af79998ded，dataset_id=63d077a8-0c4b-44b6-acc6-834ce8621cb6（train.jsonl，3行/628字节）。一次真实POST202；r8/alpha16、batch1、梯度累积8、seq128、logging1、lr0.0002、seed42，内部200步。SQL时间为16:02:29.762309～16:03:59.393032；Trainer87.852405996秒、PyTorch峰值分配1237853184字节、最后train Loss=.0004、无eval。12产物文件/96张量/200条原指标审计通过，训练提交d00349f clean。

显存数字是 PyTorch 分配峰值，非整卡显存。数据为工程样例，review_status=unknown；不同回答和很低的训练Loss均不证明正式效果提升。

## 原始证据与摘要

完整 HAR 在 `E:\LLMCloud\data\local-validation\browser-evidence\m5-20261114\`：

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| first-compare.har | 495895 | d7bcb9b3207173b16f562560e20c03234ac2308ba3b62712fe8de9bb1c01c924 |
| adapter-only.har | 504275 | cd50b8ac98ceda1be5ff272624b24377b11cde451b999ea002da56013058cc43 |
| busy-retry.har | 2072329 | a2e6735b9700e5d6f37b438638ead9b9ada73a57ee90166b646f85ab12589adf |
| cancel-switch.har | 2102487 | b74171c79240717af843a582fd925daf779447bc4ffc23096ee5341530b47001 |

E盘WSL运行目录为 `~/LLMCloud/data/acceptance/m5-inference/83945e3f-36b1-4093-bb5a-445bed478638/`，保存新DB、训练产物、原 Worker 日志和9条只读状态变化观测。D盘小型证据目录为 `data/acceptance/b-review/laptop-3060/20261114T074641Z-m5-wklgq0uf/`，含三张原始截图、五份场景核验JSON、independent-final-review.json，以及原SHA256SUMS和后补SHA256SUMS.review。

运行工具原report保留manual_session_closed_pending_review，未修改其人工核验标记；其静态real_generation=false字段不作为实际是否生成的判断依据。独立审核结论为passed_for_tested_local_scope、real_generation_independently_verified=true，依据用户截图/HAR/Worker及状态观察。原证据和运行产物不入Git，上述本机路径不是远程附件。

原网页 `http://127.0.0.1:44433/#inference` 已停止，不能当作长期服务地址。

## 怎样正常关闭

本轮已通过停止协议关闭 API、Worker、Vite 和私有 Redis，确认进程/端口退出；用户现在只需关闭浏览器标签页，不必再次停止服务。仅关标签页不能停止仍在运行的后台服务。

以后通过本入口启动新会话时，在 Ubuntu 终端执行那一轮 ready 中的 stop_command。入口会等待训练/推理清理后退出，使用该协议正常收尾，不需要关闭整套 WSL。

本轮实际执行的命令如下，已经完成；新会话必须用新输出的路径，不能沿用此旧 run_id：

```bash
touch -- '/home/l7/LLMCloud/data/acceptance/m5-inference/83945e3f-36b1-4093-bb5a-445bed478638/STOP_REQUESTED'
```

## 队友复核与剩余项

1. 审查本侧旧测试修复和独立入口（不涉及队友生产实现变更），收录本机结果；需要原证据时另行交接并验哈希。具体日志见 [本轮记录](../worklogs/2026-11-14-m5-local-inference-validation-b.md)。
2. 新推理模块仍需专门 CPU 行为覆盖：请求/响应边界、SQLite预留/领取竞争、派发确认丢失、Worker退出、缓存缺失和真实超时等。本轮未完整执行这组故障矩阵。
3. 90秒HTTP和120秒浏览器超时、真实切模式/离开缓存页面、本轮真实手机/窄屏没有新增实测证据；前端已有 mock 测试须与真实验证区分。
4. 正式语料双人审核、效果对照、双方M3/M4同步人工确认、云端恢复/部署回归仍待完成。当前用户与助手的本机操作不替代A/B联合签字，不提前更新共享里程碑为完成。
