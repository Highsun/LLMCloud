# WSL 退役清点、私有迁移材料与 macOS 接续

日期：2026-11-06（Asia/Shanghai）。起点 main=7d5239c，已含 B 的人工清单/准备日志。用户明确改为 macOS 本地开发/静态与小范围 CPU 检查，Ubuntu+CUDA 云机承担实际运行/部署，用户执行云命令并回传日志；本轮不能依赖旧聊天继续保留。

## 已完成范围

1. 检查工作区、fetch、队友日志和真实文件；代码起点与远端一致。清点仓库 ignored 数据、所有数据库、模型/产物/验收、环境配置、Python/Node/Redis/Docker、home 重复 HF/uv 缓存、用户 Redis 服务和活进程，详见 [逐项清点](../cloud-migration.md)。没有把历史规划当已实现，也未读取/打包 SSH/AWS/AI agent 凭据。
2. 检查原人工会话 0 数据集/0 任务后关闭自有 API/Worker/Vite/私有 Redis，并停用项目 Redis 用户服务自启。确认 inactive/disabled、无项目训练进程；不删除数据、不停止其他项目和全局 Docker。
3. 保留空会话 SIGINT 后真实 `failed/ConnectError` 报告。Uvicorn 先关闭使 manual finally 无法取列表，cleanup_errors=[]；独立 migration-stop.json 记录迁移前空库状态。此关闭顺序缺陷留为迁移后待修，M3/M4 人工验收仍未完成；本轮未进行训练。
4. 新增标准库 `scripts/migration_bundle.py`：停写声明、限定全新输出、排除包自身/旧锁/SQLite sidecar/缓存 token；SQLite backup API+完整性检查；按文件摘要打包、保留相对模型链接、拒绝外部链接与特殊文件；逐项验证和不存在的新目录安全恢复，不覆盖业务库。不复制 Linux .venv/node_modules/工具或凭据，不自动回放 Redis、不自动上传。
5. 私有 runtime.tar.gz=101653472 字节，models.tar.gz=796430805 字节；580 条清单、7 份 SQLite 快照、全部原数据/输出/日志/历史验收及 3 份私有参考配置。9 条模型链接完整，home 同模型权重 SHA 与项目缓存相同，不重复搬运。版本/路径记录在 host-inventory.json，敏感值不放公共文档。
6. 实际将完整归档恢复到新目录：固定缓存 9 文件/999602607 字节离线校验通过，7 DB integrity_check=ok；6 份根 outputs 成功产物与 4 份 M3 成功产物再次通过原 CPU 审计。保留 restore-verification.json。原失败目录/评测规范/草稿/重载记录均保留，不宣称效果提升。
7. 根目录 [continue.md](../../continue.md) 是可交给新 Codex 的完整提示：从零 clone/小测、团队/模块/契约/历史与当前状态、资产目录与摘要、恢复和云端资料缺口、用户运行反馈格式、待修问题/后续优先级、不恢复 Actions。同步 AGENTS/README/需求/架构/环境/项目记忆/计划/M4 入口及日志索引，旧日志不改写。

## 验证与限制

- 标准库迁移边界 **6 项通过**：WAL 中已提交行恢复、链接保留、私有配置不自动激活、旧锁不复制、目录防覆盖/越界、包摘要/成员篡改/穿越与外部链接拒绝、缓存 token 不进入包。
- 小范围既有 CPU 契约：训练 **15**、任务 **20**、观测 **22** 项通过；Python 静态编译通过；五项契约/OpenAPI --check 无漂移。受限沙箱中 TestClient 一度挂起，停止本轮自身测试后在允许本机线程的环境重跑该小范围检查通过，没有扩展为 GPU/全套运行。
- 前端 **3 个指定控制器测试文件通过**、Vite build 通过（33 modules）；未启动浏览器/平台服务，未跑 GPU 或完整业务回归。实际环境仍是原 Ubuntu，不声称 Mac 已验证。
- 数据包本身逐成员 SHA/type/size/link 校验并真实恢复通过；Git 历史在最终提交后导出 code.bundle，另附 handoff.json/最终 SHA256SUMS，实际最终 Git 结果以提交记录及包内元数据为准。

## 交付位置与真实待办

归档生成在 `data/migration/2026-11-06-wsl-to-cloud/`；收尾另复制完整目录到仓库外 `/home/highsun/LLMCloud-migration/2026-11-06-wsl-to-cloud/` 并校验，避免仅删除项目目录时连归档也删除。代码/本文/continue.md 正常提交推送；数据包不入 Git。

**云端 SSH/目标目录、Mac 接收方式均未提供，未实际跨机上传。** 已在会话询问必要接收资料，不能凭过了等待时间推定已授权某服务器。仓库外副本仍在同一 WSL；用户删除 WSL/主机前必须取走并在目标端校验。clone 只恢复代码及两个原固定 M3 证据特例，不恢复这约 898 MB 的其余资产。

后续：接收/校验私有包 → Mac 按 continue.md 导入 CPU 环境 → 用户提供服务器 → 用户执行 Ubuntu 依赖/缓存/数据库/运行检查并反馈 → 修复人工入口关闭顺序/组织新的 M4 GPU与双方人工验收 → 收口 M3/M4 后进入 M5。迁移基础运行提前，不把完整容器化/生产部署或在线推理写成已完成。
