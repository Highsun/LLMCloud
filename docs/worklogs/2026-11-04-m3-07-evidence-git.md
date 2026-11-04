# M3-07 证据包改为 Git 交付

日期：2026-11-04（Asia/Shanghai）。起点 main/origin/main=3c4e78e，工作区干净。实际 fetch 成功，无队友新增提交/日志；队友分支仍为 5ec660f。已阅读交接说明及证据打包日志。

用户明确要求“把这两文件提交到 GitHub，队友可以直接拉取”，优先于此前私下传输/忽略证据的默认约定。本次仅将下列两个已打包文件精确 git add -f 纳入版本控制，不改变 .gitignore 或纳入其余运行目录：

```text
data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip
data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip.sha256
```

ZIP 保持原字节，6,672,377 字节、63 个文件；SHA-256 仍为 dba657710cbc2f0d92207c6ce8cb2593efe0474815146bd5d51b2de0e6bae62a。发布前复查外部校验文件、ZIP 完整性和包内逐项校验值，未重新打包或改动原训练证据。包内包含隔离 SQLite 快照（0 用户）、真实工程样例的浏览器 trace、截图和元数据，不含独立数据集正文、模型/Adapter/tokenizer 权重、checkpoint 或原服务日志。内容范围与此前 [打包日志](2026-11-04-m3-07-evidence-handoff.md) 一致。

同步更新 AGENTS、README、项目记忆、交接说明及本索引，明确授权范围与 Git 拉取后的校验/解压命令。包内原说明保留当时背景，最新交付方式以仓库交接文档为准。无生产代码/依赖/接口变化，本次检查聚焦文件哈希、ZIP 完整性和实际 Git 交付；沿用之前已完成的全新解压 CPU/空模型缓存页面复查，不重复训练。

B 同步 main 后即可校验、解压，继续独立复核并写日志；材料入库不代表 B 已验收，也不代表 M3 全阶段共同收口。
