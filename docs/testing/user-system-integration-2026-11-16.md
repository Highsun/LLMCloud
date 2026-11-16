# 新发现的用户系统分支与整合边界

日期：2026-11-16，Asia/Shanghai。本轮再次 fetch 后发现队友 `origin/feature/user-system`，提交 **`a93531601cf0ea74a41e818496f26f30aeb10399`**（提交时间 2026-11-15 20:59:54 +0800），直接从 `3e2e5c3` 分出，28 个文件。它与本轮 B 工作副本同时实现了账户功能。此前本轮已按用户授权实现并验证 B 账户、M5 和部署，发现后只读比较远端源码，没有用其中一套覆盖另一套。

本次决定：**保留 A 原分支与提交；本轮交付已验证的 B 课程版本，不直接合入 A，也不让一个运行版本同时使用两套账户实现。** `main` 不变。以下是具体差异和可见证据范围，不构成对 A 整体安全性的否定，也不是双方联合验收结论。

## 不能直接拼接的差异

下表 A 行号均对应固定提交 `a935316`，B 指本轮 `feature/m4-observability-ui` 工作副本；后续冻结 SHA 由交付记录另记，不能改写原实测基线。

| 范围 | A 分支实际实现 | B 本轮实现与整合风险 |
| --- | --- | --- |
| 用户表 | `models/entities.py:27–28`，`password_hash VARCHAR(160)`，新增 `display_name VARCHAR(40)` | B 的密码列为 VARCHAR(255)，当前没有 display_name；B 显式迁移拒绝陌生额外列，不能交替运行两个迁移器 |
| 密码格式 | `services/accounts.py:20–21,39,113`，PBKDF2-HMAC-SHA256/600000 轮，保存 `salt_hex:digest_hex` | B 使用带算法/参数前缀的 scrypt。A 登录代码直接按冒号拆分 B 摘要会抛异常，B 也不会把 A 格式当有效 scrypt；合并源码不能代替密码格式迁移 |
| 会话 | `entities.py:33–37`，`account_sessions(token_digest,user_id,expires_at INTEGER)`；24 小时，cookie 名 llmcloud_session，SameSite=Lax | B 为 `auth_sessions(token_hash,user_id,expires_at FLOAT)`、可配置 12 小时默认期限和 Strict cookie。同名 cookie 不代表相同 SQL/session 语义；切换时应明确撤销旧会话并重新登录 |
| 启用方式 | 所有资源路由要求 `SignedIn`；未提供 `/auth/config` | B 用 AUTH_ENABLED 兼容历史单用户模式，新部署显式启用；B AuthGate 与 A 服务直接拼接时无法通过配置端点判定账户模式，不能保留各一半 |
| API 行为 | 注册自动发会话；me 返回 `id/username/display_name/created_at`，另有 `PATCH /auth/me` 和用户中心 | B 注册和登录分开，me 返回 id/username；没有资料编辑端点。A 新增用户中心保留在原分支，不能宣称 B 已合入这项功能；前端、Schema、错误码与操作流程必须一起选定 |
| 浏览器请求 | `api/account_access.py:24` 要求 X-LLMCloud-Request=1；A 前端发送该头并使用 same-origin credentials；main.py:100 的 CORS credentials=false | B 发送 include credentials，允许明确来源的 credentialed CORS。A 的同源部署有完整请求头配套，但跨源部署不能直接沿用 B 配置而不回归；cookie/Origin/代理/前端传输应统一 |
| 数据归属 | 两侧都使用 datasets.user_id，任务经数据集归属过滤；A 在方法参数传 owner_id | B 为请求作用域的 service/repository，调用签名不同；Worker 内部仓储应保持未按当前浏览器用户过滤，不能机械合并参数或丢掉 HTTP 授权检查 |
| 幂等键 | `services/task_repository.py:86–87`，A 将 owner UUID 与原 key 哈希为 UUIDv4 后入库，形成每用户去重键 | B 保留原 key 并拒绝跨用户重放。切换算法后，旧浏览器恢复记录的相同 key 可能找不到原任务而另建；必须保留旧键查询/来源标记或先清理未决请求，不能只替换 create 方法 |
| 迁移与历史认领 | `core/user_migration.py:46,52,75,83`，支持只读检查、SQLite backup、BEGIN IMMEDIATE；显式 --assign-unowned-to 会认领全部 NULL 归属数据 | B 还有 --services-stopped、原公共 Worker 锁、已知 schema/外键校验、逐 dataset UUID 指定认领及双 getpass 口令激活。A 操作是显式参数触发，不是注册自动认领；但整合时仍须确定操作者认可的具体数据范围，并保留停服务/备份/锁要求 |

两侧都使用随机盐、数据库会话摘要、到期/注销和资源归属。A 还包含独立密码计算并发槽（`services/accounts.py:51,75`）、账户资料编辑和前端会话 generation 隔离，这些是可以在统一实现时评估吸收的已有工作。此处不以算法名称或功能数量推断整体验收结果。

## 可见验证证据

通过 `git diff --name-only 3e2e5c3..a935316` 核查，该提交没有新增/修改 `tests/`、`docs/` 或生成的 API/Schema 文件；唯一测试辅助改动为 `scripts/browser_test_support.py` 的 owner_id 参数传递。仓库树中没有本次 A 用户系统的独立验收日志。**这只表示本次提交及收到的材料中没有这部分证据，不表示队友从未在本机执行测试。**

本次没有启动 A 分支服务、执行其迁移或跑其 GPU 任务，因此不把上述静态兼容性判断写成 A 实测失败。原匿名 HTTP/浏览器测试需要配套账户建立和登录；API/错误枚举/资料字段改变后还须更新相应生成物并验证漂移。

B 已有账户验证见 [账户结果](auth-results-2026-11-15.json)，M5/容器业务结果见 [本轮完成说明](m5-completion-2026-11-15.md)。它们支持所记录 B 版本，不支持 A+B 已合并或双方已通过。现有真实证据不会因发现另一个分支被抹去，也不复用为 A 分支的测试成绩。

## 后续统一成单套实现

1. 从双方冻结提交建立单独整合分支，保留 A 原提交和 B 已测版本，确定最终账户 API、UI、密码格式、会话策略及幂等算法；运行入口只启用一套。
2. 对实际数据库做只读清点：用户、密码格式、重复大小写用户名、两个会话表、NULL/已有 owner 数据和旧幂等请求。停 API/Worker，取得公共锁并用 SQLite backup 备份（包括 WAL 已提交内容）；不删库、不静默认领或改写旧证据。
3. 增加显式桥接迁移：保留 UUID/数据归属，明确接受两种旧密码格式后登录升级或受控重置，不伪造明文口令；撤销旧会话；对历史幂等键保证原请求不产生第二个任务。未知结构明确阻塞，迁移可先 check、重复执行无额外变更。
4. 跑账户/资料/权限/迁移/并发与前端回归，更新 OpenAPI/Schema/示例。再用两名真实隔离账户完成上传、任务创建和单 GPU 串行、Loss/日志、下载、推理及跨用户拒绝检查，重启后验证归属、凭据和资产仍可用；保存实际代码来源与结果。
5. 完成后再记录统一版本及验收范围。M3/M4追加异步复核仍按用户安排留到开发完成后；不代替队友签字，不把本页写成已经联合合入 main。

本页只新增整合记录。A 原生产源码、A 分支、main、现有数据库、模型和产物均未因本次对比发生变更。
