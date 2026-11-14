# M3/M4 本机证据补测（B）

日期：2026-11-14（Asia/Shanghai）。用户要求逐步指导补齐遗漏操作。本轮未修改生产代码、共享类型、SQL、依赖或部署配置，未重训或生成，只使用已有200步真实任务的独立副本。用户在结果核验后明确授权提交到远程仓库，本次仅交付两份结果文档到既有B分支feature/m4-observability-ui。

## 结果

1. **任务列表隐藏/恢复通过。** 用户在浏览器记录visibilitychange，隐藏14.361秒。HAR核对期间无新增同源API请求，隐藏前12秒6次成功轮询，恢复后2.012秒开始请求、前8秒3次成功轮询。补齐此前缺少准确可见性时间的证据。本轮为已完成任务页面，不扩展为活训练曲线轮询暂停验证。
2. **取消后实际重下副本审计通过。** 用户按人为3G限速取消在途请求，再恢复无限速重下。HAR确认一次net::ERR_ABORTED和一次完整200；实际另存ZIP为18,104,072字节，与HAR成功响应逐字节相同。调用原安全解压与CPU审计，12文件/96张量/200指标、manifest与源产物全部一致。未用历史旧包冒充本次重下副本。
3. **收尾通过。** STOP_REQUESTED正常结束，原启动器退出0、source_unchanged=true、cleanup_errors=[]；四个拥有进程退出、两端口关闭、原Worker锁可重新取得、临时目录空。原10项证据哈希及9项独立收尾检查全部通过，原report不改写为联合验收成功。

## 基线与交接

D盘feature/m4-observability-ui、a52ea24；E盘WSL运行分支test/m5-inference-3060-20261114、d00349f clean，与上一轮已验证生产代码相同，a52ea24仅新增结果说明。启动前fetch成功无新更新。复用已提交的laptop-3060-inference.py做隔离服务入口，原report中的M5名称保持不变，本轮按实际用途记录M4人工补测。

run_id=6cb604b6-bd00-422b-bd4b-c50cffea4456；历史任务8e5c706b/8da5af9b，源训练提交9b1165e。D盘小型证据为data/acceptance/b-review/laptop-3060/20261114T084409Z-m5-kn2re577。E盘完整HAR/复核脚本在data/local-validation/browser-evidence/m4-supplement-20261114，实际ZIP在data/local-validation/downloads/m4-supplement-20261114，均不是远程附件，不入Git。

完整时序、SHA256、下载文件身份与收尾见[补测结果](../testing/laptop-3060-m4-supplement-2026-11-14.md)。

## 保留限制

分页没有额外造任务；专用自动GPU报告没有新增执行；真实活训练的隐藏/恢复指标请求没有新增证据。原有核心训练、观测、串行与下载证据继续有效。双方同步人工确认与阶段收口仍需队友参与，本轮不代签或修改共享里程碑。正式效果实验和云部署不在本轮范围。

## Git交付

提交前fetch成功，远端B分支仍为a52ea24，本地与远端一致，无分叉或队友新增提交。提交范围仅为本日志和本轮补测结果说明；原HAR、ZIP、模型、DB与本机证据不入Git，不新增忽略例外或workflow，不更新main或A的分支。具体提交SHA与推送结果以Git记录和远端核验为准。
