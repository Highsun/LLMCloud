# M3/M4 本机证据补测（2026-11-14）

用户要求指导完成遗漏操作。本轮只补隐藏/恢复的明确时间证据，以及取消后重新下载的独立文件审计；不重做已通过的核心流程，不代替双方联合确认。

**最终状态：本轮两项补测通过，服务已正常关闭。** 任务列表在浏览器隐藏期间停止轮询、恢复后继续；取消后重新保存的实际ZIP已与HAR响应逐字节比对并完成原CPU审计。未执行新的训练或推理，未修改生产代码。用户随后授权将本结果与B工作日志提交并推送到既有B分支，具体交付以Git记录为准。活训练指标的隐藏暂停未在本轮新增实测，分页/专用自动GPU报告及双方确认继续单列。

## 会话与隔离

- D 盘分支 feature/m4-observability-ui，a52ea24，启动前 clean；fetch 成功，无新远端更新。
- E 盘 WSL 运行分支 test/m5-inference-3060-20261114，d00349f clean；与已验证会话相同的代码基线。后续 a52ea24 仅增加结果文档。
- 复用既有 laptop-3060-inference.py 隔离入口；其名称和原 report 保持 M5，不改写为专用 M4 自动验收。实际本轮用途为历史真实任务的 M4 人工补测。
- 源为 m4-07/5421dcac-74c0-4af9-b5a4-d555384a5381/data，两个历史 200 步任务 8e5c706b-332e-4922-97bb-54e8d0cf2e68、8da5af9b-56ab-4bb3-afd7-fc8d1d56489c 均已审计。通过只读 DB 备份与文件哈希复制进入新会话；没有重新训练或生成。
- runtime：/home/l7/LLMCloud/data/acceptance/m5-inference/6cb604b6-bd00-422b-bd4b-c50cffea4456。
- D 盘小型证据：data/acceptance/b-review/laptop-3060/20261114T084409Z-m5-kn2re577。
- exec session：89684；Worker PID：407；入口已输出 ready_for_manual_browser。
- 前端：http://127.0.0.1:60121/；API：http://127.0.0.1:33291。仅为本轮临时本机地址。
- 原 HAR/可导出的可见性时间记录：E:\LLMCloud\data\local-validation\browser-evidence\m4-supplement-20261114。
- 本轮独立下载：E:\LLMCloud\data\local-validation\downloads\m4-supplement-20261114。

## 分步安排与状态

1. 用户已打开任务页面，Network 保留日志，开启每 2 秒刷新并打开第一历史任务曲线。
2. 在浏览器明确记录 visibilitychange 时间，完成前台→隐藏约 10 秒→前台。对照 HAR 区分隐藏前在途请求与隐藏后的新增周期请求。完成任务的指标/日志在拉取完毕后自然停止，不能把静止终态当成活曲线暂停证据；先验证列表轮询，必要时再用一次短训练覆盖活任务。
3. 选第一历史任务，在明确人为网络限速下取消一次在途下载，恢复网络后重新下载到本轮独立目录，不覆盖原证据。核对实际下载文件身份、完整 ZIP、原 CPU 审计与源文件哈希。
4. 已使用本轮 STOP_REQUESTED 协议正常关闭，进程/端口/临时区与锁独立核对通过，详见下方收尾结果。

正常停止命令（仅本轮）：

```bash
touch -- '/home/l7/LLMCloud/data/acceptance/m5-inference/6cb604b6-bd00-422b-bd4b-c50cffea4456/STOP_REQUESTED'
```

分页已有回归但本轮不额外制造训练任务；专用自动 GPU 报告与双方共同确认均单独保留状态。本轮Git交付仅包含两份结果文档，不包含原HAR、ZIP或本机证据目录。

## 隐藏/恢复时间回传

用户在本轮页面安装只记录 visibilitychange 的浏览器监听器后，回传 visible=2026-11-14T08:48:12.243Z、hidden=08:48:25.029Z、visible=08:48:39.390Z，隐藏14.361秒。原回传保存在 D 盘本轮证据 visibility-user-events.json。这些用户回传的浏览器事件与下节HAR交叉核验。终态历史任务只验证列表轮询，不冒充活训练曲线暂停证据。

### HAR 回传后核验

用户已保存 E 盘本轮 visibility.har。只读核对实际页面同源 API 请求：隐藏14.361秒期间没有新增 API 请求；隐藏前最后一次列表请求08:48:23.487Z已在隐藏前结束，恢复后08:48:41.402Z重新请求，延迟2.012秒，之后继续约2秒一轮且返回200。该项通过范围为已完成任务页面的任务列表隐藏暂停/恢复，不扩展为真实活训练指标轮询证据。原HAR留E盘，小型计数/时序/哈希/五项核验保存在本轮D盘visibility-har-review.json。后续取消在途下载、恢复网络后的独立重下文件已审计，见下节。

visibility.har为3,885,411字节、117请求，SHA256=7557428c604fbc4f7cb5d03aff494bd8f3a8932e305438c2d4c136a755b3ac54。隐藏前12秒有6次成功列表轮询，恢复后8秒有3次成功轮询，5项检查全部通过。

## 取消后重新下载：通过

用户回传“取消提示正常，重新下载成功，HAR已保存”。本轮明确先选择人为3G限速进行取消，再恢复无限速重下；不称为自然网络故障。

- download-retry.har：27,096,760字节、66请求，SHA256=9745cc5ab1d1e50c63d51e54811742e910cfbccd2296648a7e9b412fc2ea2345。
- 恰好两次同一8e5c706b任务的下载请求：08:52:36.140Z首次请求在2447.242ms后net::ERR_ABORTED，已收到200响应头但未完成body；不能把头部200误判为下载成功。
- 08:52:55.555Z用户重下，553.793ms完整200，application/zip、no-store、文件名与任务身份正确；request_id=7dd8a1dc-b96a-4ab3-bb7e-d5fcd6d6095e。
- 用户实际保存文件为本轮E盘独立下载目录下llmcloud-adapter-8e5c706b-332e-4922-97bb-54e8d0cf2e68.zip，18,104,072字节，SHA256=59572fd6cb3db29fadde511d125a2498a6b33a6571652741711f7f9c185b2525。
- HAR成功响应base64解码后与这份实际保存文件逐字节一致，长度与Content-Length/bodySize一致；不再拿历史旧包代替重下副本。
- 复用scripts.m4_acceptance_support.audit_download，在本轮E盘runtime/download-retry-audit全新目录限量安全解压。12个产物文件、96张量、200条指标及manifest通过原CPU审计，所有文件与本轮历史源产物逐字节哈希一致。review_status仍为unknown，不宣称效果提升或新进程重载。
- 10项HAR/文件核验全部通过；当时两任务均COMPLETED、活动推理0、downloads/inference临时目录空。小型结果为D盘download-retry-review.json。

## 正常收尾与独立复核

已确认没有在途任务，通过本轮STOP_REQUESTED协议正常关闭；exec session89684退出0。原启动器report保留manual_session_closed_pending_review，不改人工标记；source_unchanged=true、cleanup_errors=[]。

独立核对API306、Worker407、Vite377、Redis371均退出，60121/33291无监听，原worker.lock可取得并释放且inode未替换；两历史任务保持COMPLETED，活动推理0，downloads/inference临时区空。原SHA256SUMS的10项全部一致，后补independent-final-review.json结论passed_for_tested_local_scope，并以SHA256SUMS.review覆盖后补审核。9项收尾检查全部通过。

完整HAR、ZIP、解压产物及独立复核脚本留在E盘，D盘仅结果文档/小型日志；临时网页地址已关闭。后续使用需另开新会话。具体B交接见[工作日志](../worklogs/2026-11-14-m4-local-supplement-b.md)。
