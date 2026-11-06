# Windows 下载中转与完整恢复方法

日期：2026-11-06（Asia/Shanghai）。起点 main=95c42dd；本轮用户确认云服务器暂时没有，要求把私有迁移材料放到 Windows“下载”，后续自行传 Mac，并写好完整恢复方法。

通过 Windows User Shell Folders 的 Downloads GUID 获取当前实际路径 `C:\Users\PC\Downloads`，未猜用户名或扫描其他用户资料。交付文件夹为 `LLMCloud-migration-2026-11-06`，位于 Windows NTFS、WSL 项目之外；原两个 WSL 副本保留。云端仍未上传，Mac 接收待用户完成。

新增 [完整恢复说明](../migration-restore.md)：Windows PowerShell/Mac SHA256 校验、在线/离线 Git clone、Mac Codex 导入提示、Ubuntu 接收/全新目录安全恢复、排除 Redis 历史回放的持久目录复制、从示例重建配置、固定模型/7 份 DB/10 份成功产物只读核对及删除旧副本条件。明确 datasets 迁移脚本用环境变量指定路径，不能误传不存在的 --data-dir 参数。

根 continue.md、README、AGENTS、项目记忆/迁移清点与索引已同步 Windows 中转事实。最终将最新 Git 历史重导出 code.bundle，包内补离线 continue.md/RESTORE.md、更新 handoff.json/SHA256SUMS；两份原始 runtime/models 归档不重打，固定数据摘要不变。总计 10 文件，数据/权重/DB/日志/包继续不入 Git。

复制使用新的临时目录，校验通过才改名为最终交付目录；不覆盖已有用户文件。实际复制/摘要与恢复验证结果以本轮工具结果和私有 windows-delivery.json 记录为准。恢复脚本和原数据均未改；本轮不启动服务、GPU、Actions，不执行云机尚未具备条件的安装/部署命令。完成前及推送前 fetch 检查队友更新，保持正常共享历史。

Windows 副本能独立于 WSL 项目保留，但仍在同一物理主机。用户清空整台主机前，必须把整个目录复制到 Mac/独立存储并再次验包；仅 clone 不能恢复私有资产。云服务器就绪后由 Mac 的新 Codex 按恢复说明指导用户运行，实际结果回传后再调整代码。
