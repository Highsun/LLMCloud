# RTX 3060 本地测试与语料交付总览（B）

更新：2026-11-13。该页是队友从GitHub拉取后的阅读入口；不用先取得本机E盘文件即可了解实际结果和剩余项。

## 当前结论

本次为用户授权的 **WSL2 Ubuntu + RTX 3060 Laptop 6GB 本地复现**。基础功能先在本地开发/验收，上线前再租云主机恢复环境、部署并回归。它是2026-11-06仅云端运行安排的后续调整，不宣称云端部署已经通过，也不改变A/B代码边界。

原业务代码基线：`9b1165e38d083a7b8a8b0f4d36c2aeed96b826ca`，各次实际训练清单记录为clean。模型固定Qwen2.5-0.5B-Instruct、revision `7ae557604adf67be50417f59c2c2f167def9a775`。本次新增独立记录/包装入口，没有修改后端、共享契约、Trainer、依赖或部署配置。

| 验证范围 | 实测结果 | 证据说明 |
| --- | --- | --- |
| CPU回归/契约 | 412项运行：411通过、1项可选浏览器检查跳过；5项契约检查通过 | 不是GPU/浏览器替代证据 |
| 前端 | 116项通过、生产构建成功；package.json/package-lock哈希不变 | Linux Node22.23.3/npm10.9.9 |
| HTTP/Redis | 上传/指标日志/合成下载/实际私有Redis生产Worker CPU消费4项通过 | 合成产物明确标CPU；空缓存MODEL_NOT_CACHED为预期失败 |
| 模型 | 缓存完整/离线核验/BF16真实前向通过 | PyTorch分配峰值1042360320字节 |
| L3短训练 | 2步LoRA、独立CPU产物审计、新进程Adapter重载生成通过 | LoRA张量96/96变化，基础权重哈希不变 |
| 40步平台流程 | 用户网页上传、两任务各40步完成且SQL区间无重叠；终态曲线/日志可见 | 两任务末Loss均2.3527；有效ZIP均独立解压审计通过 |
| 200步实时观测 | 用户RUNNING/56步活图；17轮非空活请求覆盖32.593秒 | HAR中200条指标按原文件byte offset/step/Loss/time逐条一致，终态补拉完成 |
| 训练中下载 | 首任务ZIP下载用时590.18ms，完整区间被第二任务两次真实优化器事件包围 | 不是仅处于RUNNING加载阶段；ZIP与源文件逐字节一致 |
| 取消/切换/重下 | 显式3G限速下3个ERR_ABORTED，随后两任务完整ZIP响应均200 | 用户确认按钮/切换/重下正常；人为限速条件保留 |
| 窄屏/日志 | 用户报告390px模式、历史日志滚动和页面恢复正常，截图留存 | 图表在自身区域滚动；未声称实机手机测试 |
| 正常收尾 | 两轮服务均正常capture/退出，下载临时区空，Worker原锁已释放 | 40步清单25项/200步清单19项原哈希全部通过 |

上述显存数字是PyTorch分配峰值，不是整卡显存占用；3条工程样例上的Loss不证明正式效果提升。

## GPU任务摘要

| task_id | 更新步数 | 梯度累积 | Trainer耗时（秒） | 峰值分配（字节） | 最后train Loss |
| --- | --- | --- | --- | --- | --- |
| bea69c0c-44bf-435f-892d-46ba5c16f431 | 40 | 1 | 19.528441828 | 1235489280 | 2.3527 |
| f56625e9-79c3-4004-8ddf-97df8617f7c0 | 40 | 1 | 12.638572753 | 1235882496 | 2.3527 |
| 8e5c706b-332e-4922-97bb-54e8d0cf2e68 | 200 | 1 | 45.921087458 | 1235489280 | 0.0010 |
| 8da5af9b-56ab-4bb3-afd7-fc8d1d56489c | 200 | 8 | 91.015790524 | 1238049792 | 0.0004 |

四个任务实际公开配置均为r8/alpha16、batch1、seq128、logging1、seed42、lr0.0002，第二个200步任务仅梯度累积改8以增加真实计算量；无人工训练延时或补点。40步首任务结束至次任务开始间隔0.018984秒。200步两任务分次人工提交，不冒充同时排队的新证据。

## 120条候选语料

已编写120条/30个问答族，每族4条，独立来源目录记录30个官方文档页面。按原工具seed42分组为train96/validation12/test12，build_id=`54acf9229ff98c04`；格式、规范化去重、冻结精确prompt/保留族检查、可复现重建及原prepared metadata核验通过。固定Qwen tokenizer在256长度下检查train/validation，均0截断、回答监督有效；没有用test正文做token诊断或进行正式训练。

**120条均为draft_unreviewed，人工审核0/120。** 格式和来源可查不代表事实、语义近重复、来源使用及冻结评测独立性已获双人审核。详见 [语料说明](../data/cloud-basics-draft-2026-11-12-b.md) 与 [公开主题/来源索引](../data/cloud-basics-draft-sources-2026-11-12-b.md)。

完整语料按仓库现有数据规则私下交接，不新增Git忽略例外。已在E盘准备一个独立包，供用户另行传给队友：

- 文件名：`cloud-basics-zh-draft-20261112-v1-handoff-20261113.zip`
- 本机目录：`E:\LLMCloud\data\handoffs\`，同目录有`.zip.sha256`。
- 大小：79225字节，23个条目，共260249字节未压缩内容。
- SHA-256：`003baaae78cc23572627672552913401f091250a6cd760ec740ce0a796d6773d`。
- 内容：原始JSONL、curation、来源目录、可读双人审核稿、分组编写输入/独立构建入口、96/12/12草稿划分与各层清单及CPU验证结果。没有模型、DB、Adapter或HAR。

接收者先核对ZIP摘要，再解压到一个全新的私有目录，保留`curated/`和`prepared/`布局，核对各层SHA256SUMS；逐条双人审核后，在新版本中记录reviewed结果并重建正式划分。该包当前仍未传输，不把本机打包写成队友已接收。

## 复现入口与路径

新增`laptop-3060-*.sh/.py`为本轮独立包装，调用仓库现有入口，不替换生产服务实现。默认运行仓库为`~/LLMCloud`；结果默认写到包装脚本所在仓库的忽略目录。可通过以下环境变量明确指定不同的运行与记录副本：

```bash
export LLMCLOUD_TEST_REPO="$HOME/LLMCloud"
export LLMCLOUD_REPORT_REPO="$HOME/LLMCloud"
"$LLMCLOUD_TEST_REPO/.venv/bin/python" \
  "$LLMCLOUD_TEST_REPO/docs/testing/laptop-3060-manual.py" --check --max-steps 200
```

如果脚本放在另一份checkout，第二行记录副本可指向该checkout，并使用那份脚本的实际路径。两变量都应指向已有目录；本机D/E布局只是测试事实，不是队友必须照搬的路径。

| 入口 | 用途/是否实际运行过 |
| --- | --- |
| [CPU](laptop-3060-cpu.sh) | 原CPU测试和5项契约；已运行通过 |
| [模型](laptop-3060-model.sh) | prepare显式下载；check离线；gpu显式BF16前向；三模式已通过 |
| [短训练](laptop-3060-train.sh) / [审计与重载](laptop-3060-artifacts.sh) | 两步LoRA工程冒烟及新进程重载；已通过 |
| [Node准备](laptop-3060-node.sh) / [前端](laptop-3060-frontend.sh) | 固定Linux Node校验安装、锁定依赖/测试/构建；已通过 |
| [HTTP/Redis](laptop-3060-http.sh) | 隔离CPU场景；已通过，不作GPU证据 |
| [手动平台](laptop-3060-manual.py) | `--start --max-steps 40或200`；使用现有Windows浏览器，已实际操作 |
| [浏览器准备](laptop-3060-browser.sh) | 可选Playwright准备；用户中止过下载，本轮没有安装/自动验收通过结论 |

`--check`仅检查包装入口及依赖/路径，不开始训练、下载或平台服务；artifacts入口另需已有L3任务UUID。GPU操作必须安排单实例/共同锁，真实训练由用户在页面提交。手动会话以ready.stop_command正常结束，避开原人工工具Ctrl+C快照生命周期问题；本次未修改A的原工具。

## 尚未完成的验收

- M4专用自动GPU浏览器报告未执行；本次为真实人工本地验证。
- M3/M4双方同步人工操作及双方独立确认未执行，不更新共享里程碑为完成。
- 隐藏期间不新增周期请求缺少明确visibility事件时间；两任务不足一页，分页未新测。
- 首任务重试响应完整可由HAR确认，但未单独识别其另存副本；原有效包和第二任务新包已审计，不冒充单独识别的重试副本。
- 新40/200步Adapter没有重新做新进程生成；L3两步Adapter的新进程重载证据仍独立有效。
- 正式语料双人审核、效果对照、M5在线推理、云端恢复/部署回归仍待完成。

## 原始证据与进一步阅读

[完整本机测试记录](laptop-3060-local-validation.md)、[200步补测](laptop-3060-m4-followup.md)、[B工作日志](../worklogs/2026-11-12-laptop-3060-local-validation.md)。这些页面中`data/acceptance`和E盘链接是本机定位，不是GitHub附件；摘要已在本页公开，原始证据不随Git发布。

40步run：`0f5c44ae-a3cb-40ec-8dec-a12763ec7897`；200步run：`5421dcac-74c0-4af9-b5a4-d555384a5381`。对应D盘记录目录为`20261112T105827Z-manual-pr6cllqq`和`20261112T131702Z-manual-po1lbqv7`。原report/原SHA256SUMS保留，后补复核用独立SHA256SUMS.review。原始HAR/权重/数据/DB/产物继续在E，D只存说明/小型结果。
