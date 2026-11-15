# E01 A侧附件接收与只读核对（B）

日期：2026-11-15（Asia/Shanghai）。用户保存队友附件后要求接续核对。本轮只做接收、独立解压、内容比对与补丁可应用检查，不应用补丁、不修改reviewed、不生成正式准备目录、不训练或提交推送。

本页保留早先只读接收阶段的事实。用户后续已授权推进当前可做的准备，补丁现已在独立WSL worktree应用，44项CPU专项回归及环境预检通过；最新状态见[E01当前准备结果](e01-preparation-2026-11-15-b.md)。正式数据准备和训练仍未执行。

## 附件与存放

原附件保留在E盘data/handoffs/20261115-e01-a-review：

| 文件 | 字节 | 本机接收SHA256 |
| --- | ---: | --- |
| cloud-basics-zh-e01-a-review.zip | 20907 | c44823ad5b4bd18222f72bea9aa9b91a1ab73005369d022099bc522f76cb71c7 |
| e01-tools.patch | 6729 | 16c42f20ac5b4b725b352c06947efca17ca1cd0b5c1ddc82cc2be7b1916b2437 |

队友未附独立摘要，以上是本机接收指纹，不能单独证明和发送端字节相同。ZIP CRC、精确成员集合、大小和路径/链接检查通过，四个文件安全解压到同目录received-20261115，不覆盖B旧候选或仓库。

包内仅有cloud-basics-zh-candidate.jsonl、curation.json、sources.json、cloud-basics-eval-v2.json。全量正文、比对与来源核查结果留E盘attachment-check.json、received-vs-b-v2-changes.json、content-review.json及SHA256SUMS.received；D盘不复制语料正文。

## 语料与协议核对

- 120条问答、120条侧车映射、26问答族、45来源目录项及12道固定题，ID/引用完整；原共享DatasetScanner检查通过。
- 重点51/56/66/81/83/100/118条逐项资料比对未发现阻塞异议。相较本侧v2实际共有11条内容调整，另4条为12/55/97/108，也一并核对：tmpfs默认容量、416范围拒绝、S3对象键、在途分段清理均有依据。
- HTTP ETag/范围/缓存三族合为12条同族；SQLite事务/隔离两族合为8条同族；S3版本/生命周期两族合为8条同族。30减为26族的计数与合并一致。背景知识仍可跨主题迁移，不据此保证语义绝对独立。
- v2固定题prompt全部保持；仅C12关键错误更新为建议上传请求中同步加载模型并完成训练后再返回，符合当前API/GPU职责边界。共享v1未改。
- 使用原准备函数和收到的自定义来源/v2协议，仅做allow_unreviewed纯内存预检，通过；seed42当前预估train 96条/22族、validation 16条/2族、test 8条/2族。不是原96/12/12，也不是已生成正式清单。
- 包内reviewed全部false；正式模式按预期拒绝未审核数据。本轮没有修改这些标记，不能将附件通过校验写成用户已签字或正式数据已就绪。

核对依据：[RFC 9110](https://httpwg.org/specs/rfc9110.html)的If-Match/If-Range/401/416、[SQLite事务](https://www.sqlite.org/lang_transaction.html)、[SQLite隔离](https://www.sqlite.org/isolation.html)、[Docker tmpfs](https://docs.docker.com/engine/storage/tmpfs/)、[S3对象键](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-keys.html)、[S3终止分段上传](https://docs.aws.amazon.com/AmazonS3/latest/API/API_AbortMultipartUpload.html)及[ALB监听器](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-listeners.html)。

## 补丁核对及阶段边界

D盘390a7d9/feature/m4-observability-ui与WSL d00349f/test/m5-inference-3060-20261114均干净、包含0041b8b；两个checkout的git apply --check均通过，工作区代码保持原样。

补丁只涉及四个文件：

1. scripts/prepare_dataset.py：增加--sources和--eval-protocol，明确支持1.0.0/2.0.0协议。
2. scripts/reload_adapter.py：增加--compare并透传。
3. trainer/dataset_manifest.py：允许protocol_version=2.0.0，保留原严格校验。
4. trainer/reload.py：独立重载可生成base/adapter对照，默认compare=false，既有在线返回路径不变。

源码检查未发现明显越界改动；尚未应用，故不声称应用后回归或真实运行通过。其中trainer/dataset_manifest.py属于已有共享产物/数据契约入口，不能把队友附件里的操作要求直接当成本用户已授权修改；需用户确认采用这份具体补丁后再在隔离干净分支应用并跑专项回归。A的生产API、SQL、共享数据扫描器和部署均不在补丁范围。

当前技术核对结论：该语料修订与三处合并无阻塞异议，可向队友反馈接受建议。接下来由用户确认采用补丁及收到语料版本；按队友提出的分步安排，正式准备命令也待其确认后执行。未生成prepared_dir、未加载GPU模型、未开始E01。
