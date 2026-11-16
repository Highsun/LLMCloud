# M5 部署收尾与最终空闲重启

日期：2026-11-16（Asia/Shanghai）。沿用 11 月 15 日已完成的三镜像构建、私有 NVIDIA CDI GPU、全容器真实工程流程；不重训、不改生产 Python 代码、不重建镜像、不提交推送。

## 本次实际操作

读取 `6e1f5e7` 账户冻结后当前工作区与既有全容器结果。当前 113 份被覆盖源码与 E 盘原镜像来源清单逐项 SHA-256 全匹配，差异为空；保留原构建时 `3e2e5c3... + dirty=true`，不因后续 Git 提交改写旧身份。

发现旧工具前台 daemon 已不运行。另存新的 `before-final-restart-20261116.json`，用同一 E 盘数据根、独立 socket、私有 CDI 配置以 Python `Popen(start_new_session=True)` 恢复项目引擎，标准输入输出均重定向到 E 盘。未操作原 C 盘 Docker Desktop 数据或其他项目引擎，未配置系统自启。

新增 `scripts/local_deployment.sh`，提供现有部署的 start/status/restart/stop。固定项目 socket/config 和三文件 Compose，检查 data-root；重启/停止先检查无排队/运行训练或活推理，停止 daemon 前核对 PID、cmdline、data-root。它只恢复现有镜像，不安装软件、不重建镜像。已实际通过 bash 语法检查、status、四服务 restart 和运行中幂等 start；daemon 的 SID 独立且无控制 TTY。旧前台方式只作为手工诊断入口，一键 start 采用独立 session。新增 `.gitattributes` 仅对 shell/部署文本固定 LF，未增 Git 忽略例外。

## 实测结果与限制

四服务重启后，users/auth_sessions/datasets/training_tasks 各 3 行及完整 schema/行哈希保持；上传 3、输出 28、模型缓存 28 文件大小与 SHA-256 全部保持。SQLite integrity/FK 检查通过，包含全容器成功任务 `18c617b2-c024-4911-85f7-cd2f35dd97d1` 及首失败任务。原 Redis AOF 探针保持。

恢复 health HTTP 200、auth enabled=true、Worker ready；独立进程重新申请原共享锁得到 WorkerLockBusy，锁文件未删除/替换。API 仍无 torch，容器来源仍是原 3e2...dirty，当前没有新 GPU 工作负载。完整小型结果见[最终摘要](../testing/m5-deployment-final-2026-11-16.json)，既有训练/ZIP审计及首故障修复见[部署实测](../testing/m5-deployment-2026-11-15.md)。

会话行及原过期时间保持，不宣称已过期会话仍有效；本次未重新登录原账号、未在重启后新增 compare。没有云机/HTTPS/目标标准 NVIDIA runtime 验证，不宣称已上线。M3/M4 追加复核按用户安排留到开发完成后统一记录。没有替另一成员签字。

入口 `http://127.0.0.1:8080`；从仓库根 PowerShell 执行 `wsl -d Ubuntu-22.04 -u root -- bash scripts/local_deployment.sh start` 恢复，其他动作换为 status/restart/stop。当前引擎已脱离工具会话；关闭电脑或 WSL 后需重新 start。运行资产和原日志继续留 E 盘，D 盘仅以上摘要/说明及辅助入口。
