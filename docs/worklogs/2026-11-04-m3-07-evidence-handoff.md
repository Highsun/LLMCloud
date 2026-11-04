# M3-07 跨机器证据交接补齐

日期：2026-11-04（Asia/Shanghai）。起点 main/origin/main=003ac0d，工作区干净。开始及证据包完成后实际 fetch 均成功，无队友新增提交/日志；队友分支仍为 5ec660f。已阅读 M3-07 交接、A 验收日志与工作日志索引。

## 问题与处理

B 的 Codex 反馈本机没有真实验收目录。核对后确认原证据仍完整保存在 A 的 data/acceptance/m3-07/dbdffce3-e453-46bf-b962-d66a424d7199，且被 Git 忽略；先前交接只说明本机路径，没有完成跨机器材料传递。该反馈成立，不是重新拉取代码即可解决的问题。原验收服务已退出，报告中的 URL 不是可访问的现有服务。

本次生成私下交接 ZIP 和外部 SHA256 校验文件：

```text
data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip
data/acceptance/handoffs/m3-07-dbdffce3-e453-46bf-b962-d66a424d7199-review.zip.sha256
```

大小 6,672,377 字节（约 6.4 MiB），ZIP SHA-256：

```text
dba657710cbc2f0d92207c6ce8cb2593efe0474815146bd5d51b2de0e6bae62a
```

包含 63 个文件：原报告、20 张截图、10 份 trace、浏览器 result/submitted、只读源库经 SQLite backup 得到的一致性快照、训练清单/指标/配置/失败诊断、范围说明和文件校验清单。数据库 4 个 COMPLETED、5 个预期 FAILED，users=0。报告/浏览器/训练元数据逐字节复制，源文件哈希与源数据库哈希打包前后均一致。

数据集正文、模型缓存、Adapter/tokenizer 权重、checkpoint、原服务日志未打包；trace 中有本次公开工程格式样例的实际请求内容。材料仅用于团队复核，不添加到 Git 或公开发布。需要独立重新核验权重时应另行传递完整原产物目录。

## 验证

- ZIP testzip 通过；全新解压后逐项 SHA256SUMS 校验通过。
- SQLite 快照 integrity_check=ok，任务状态数量与原库一致；原库只读访问，打包未改动原证据。
- 使用全新解压的临时工作副本、/tmp/llmcloud-ci-env CPU 环境、空 HF_HOME/HF_HUB_CACHE，并设置离线模式，实际执行 scripts/check_m3_acceptance.py --review-run，五类既有任务页面复查通过，退出 0。
- 本次复查只使用真实 API/Vite/浏览器与 SQL 快照，无 Redis/Worker/GPU、模型/数据正文；它更新临时副本的页面证据，不修改原 ZIP 或原训练事实，不能当作新 GPU 验收。
- 本次只补齐私下证据包与交接文档，未修改生产后端/Worker/Trainer/前端或依赖，不重复跑完整训练/CPU 回归。

## 待交接

用户将 ZIP 和 .sha256 两文件交给 B 后，B 才能按 [交接说明](../m3-acceptance.md#跨机器证据交接) 校验/解压并复核。当前仅确认 A 已准备材料，未确认跨机器传输、B 复核或人工页面操作已完成。B 可先做代码/本机 CPU 检查，收到证据后另写 YYYY-MM-DD-m3-07-b.md，区分每类验证和未完成项；实际新上传到 GPU 完成的人工操作另约共同服务时段。M3 阶段共同收口仍待 B。
