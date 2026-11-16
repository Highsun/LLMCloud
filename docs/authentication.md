# 账户、数据归属与显式迁移

2026-11-15 用户授权一并完成登录、注册、用户数据持久化及迁移。账户模式为已有单 GPU 平台的可选访问层，训练/推理仍共用唯一 Worker 和原任务契约。

## 启用与 API

本机历史单用户模式默认 `AUTH_ENABLED=false`；此模式的数据集/任务仍是原有非隔离演示范围。新部署显式设置 `AUTH_ENABLED=true`，仅健康检查、模型目录、账户配置、注册和登录公开。不要把关闭账户模式当作生产访问控制。推荐前端和 API 同源反向代理；跨端口访问需明确 `CORS_ORIGINS` 并使用 cookie credentials，不允许 `*`。SameSite=Strict 不支持跨站嵌入。

| 环境变量 | 默认值 | 含义 |
| --- | --- | --- |
| `AUTH_ENABLED` | `false` | 显式开启登录和资源归属校验 |
| `AUTH_COOKIE_SECURE` | `false` | 本机受限 HTTP；TLS 部署改为 `true` |
| `AUTH_SESSION_SECONDS` | `43200` | 会话期限，允许 300～604800 秒 |

| 方法与路径（`/api/v1` 下） | 行为 |
| --- | --- |
| `GET /auth/config` | 返回 `{"enabled":true/false}`，不暴露账户资料 |
| `POST /auth/register` | `username/password`；201 返回 `id/username`，不自动领取历史数据 |
| `POST /auth/login` | 相同输入；200 返回账户及 HttpOnly 会话 cookie |
| `GET /auth/me` | 当前账户；未登录/到期为 401 `AUTH_REQUIRED` |
| `POST /auth/logout` | 删除当前会话并清 cookie；204，可重复调用 |

用户名为 3～32 位 ASCII 字母、数字、下划线，统一小写；密码 12～128 个字符、最多 512 UTF-8 字节，不写入日志、响应、命令行或浏览器存储。登录失败统一 `401 INVALID_CREDENTIALS`，缺失账户和错误口令走相同 scrypt 成本；重名注册为 `409 USERNAME_UNAVAILABLE`。JSON 使用既有严格解析（重复/未知键拒绝、64 KiB 上限、只接受 UTF-8 application/json）。参数错误继续使用既有 `VALIDATION_ERROR`。

密码采用独立随机 16 字节盐的 scrypt（N=16384,r=8,p=1），数据库仅保留参数、盐和摘要。会话为随机 opaque token，SQLite 仅存其 SHA-256 与过期时间；cookie 为 `llmcloud_session`，HttpOnly、SameSite=Strict、Path=/，登录旋转当前会话，注销/到期失效。账户模式响应设置 no-store。非安全方法检查明确 Origin 和 Fetch Metadata，拒绝跨站请求。每 API 进程按实际连接地址限制注册/登录合计 10 次/分钟，状态有界；这是受限课程环境的基础节流，不是多副本共享的公网防滥用系统。

前端提供注册/登录/退出、会话到期提示；退出和账户切换完整重载，避免保留上一账户页面状态；提交恢复记录按账户 ID 分区，不存密码或 token。跨标签页账户变化通知只传变化标记。原有任务配置和推理/下载的取消与超时行为保留。

## 数据归属

上传在现有 `datasets.user_id` 登记当前账户。数据集列表在计数和分页前过滤；任务归属通过不可变的数据集关联确定，不新增任务公开字段或复制 owner。任务创建拒绝使用他人数据集；任务列表、详情、指标、日志、下载和推理都验证相同归属。不存在和他人 UUID 均返回对应资源的 404，跨账户去重键不能重放出原任务 ID。

Worker 继续使用未按用户过滤的内部仓储领取业务任务，所有用户仍共享单 GPU 互斥。数据所有权与 Worker `claim_token` 是不同概念。

## 已有 SQLite 的升级

先在实际运行环境设置正确的 `DATA_DIR/LOG_DIR/DATABASE_URL`，保留原 `.env` 和运行数据，不把数据库移到代码盘。新空库启动会建完整 schema；已有用户表缺少 `password_hash` 时，账户模式启动明确拒绝并要求迁移，不用 `create_all` 偷改旧表。

```bash
uv run --locked python scripts/migrate_auth.py --check
# 停止 API 和 GPU Worker，确认无运行中的请求后：
uv run --locked python scripts/migrate_auth.py --apply --services-stopped
```

迁移只支持可识别 SQLite 用户/会话结构，校验列、类型、会话 PK/FK/索引和既有外键。应用前使用 SQLite backup API（包含 WAL 中已提交内容）写 `DATA_DIR/backups/auth-before-migration-*.sqlite3`，在 `BEGIN IMMEDIATE` 中重核并提交。CLI 取得原公共 Worker 锁；`--services-stopped` 是操作者对 API 已停止的明确声明，不宣称锁能探测所有 API 进程。检查默认只读，不创建不存在的数据库；重复应用无变更。未知结构/已有外键错误拒绝，保留旧数据。备份包含账户和会话摘要，应与数据库同样保护。

旧用户保留原 UUID/用户名/时间及现有归属，密码字段保持 NULL，不能凭空生成凭据。保留的 ASCII 用户名按不区分大小写查询；旧库已有大小写别名冲突时迁移报告阻塞，不能静默选择其中一个。确需启用旧账户或重置密码，停止服务后，在交互终端运行：

```bash
uv run --locked python scripts/set_user_password.py --user-id EXISTING_USER_UUID --services-stopped
```

命令使用两次隐藏的 getpass 输入确认，复用注册密码规则；不接受命令行、文件或 stdin 管道口令。先备份为 `auth-before-password-reset-*.sqlite3`，取得公共 Worker 锁后更新原账户密码，并作废该账户所有会话。它不更改用户名、数据归属或其他账户。备份回滚会恢复旧会话信息，恢复操作须停服务并按整库恢复方案处理。

历史 `user_id=NULL` 数据默认不分配。用新账户注册登录后，从 `/auth/me` 获取其真实 UUID；双方明确归属后，可仅对指定数据集检查并应用：

```bash
uv run --locked python scripts/migrate_auth.py --check --assign-to-user USER_UUID --dataset-id DATASET_UUID
# 先停 API/Worker；--dataset-id 可重复指定。
uv run --locked python scripts/migrate_auth.py --apply --services-stopped --assign-to-user USER_UUID --dataset-id DATASET_UUID
```

不存在的用户/数据集、无完整参数或已有其他 owner 会阻塞，不按文件名、时间或“第一个注册用户”推断身份，不批量抢占历史数据。关联的旧任务随指定数据集归属可见；文件、模型和 Adapter 不复制或重写。

## 验证和接续

小型结果见 [账户验证摘要](testing/auth-results-2026-11-15.json)；真实 HTTP/SQLite 回归及真实 Edge 浏览器覆盖登录、注册、会话、归属和 API 重启持久化。浏览器检查使用全新隔离库，不消耗 GPU，不代表云部署或旧正式库已迁移。运行原件留 E 盘（含 E 盘承载的 WSL 原生目录）。部署入口见 [部署说明](deployment.md)。

浏览器复现入口为 `frontend/playwright.auth.config.mjs`，设置 `LLMCLOUD_AUTH_TEST_COMMAND` 启动 `frontend/testing/serve_auth_api.py --root E_DISK_NATIVE_LINUX_TEMP_PARENT`，设置 `LLMCLOUD_AUTH_TEST_OUTPUT` 为运行盘输出目录，再执行 `npx playwright test --config playwright.auth.config.mjs`。测试服务仅绑定 127.0.0.1，不连接 Redis/GPU，不包含测试控制路由。

本次没有对已有正式数据库执行上述迁移、激活、归属变更，没有替用户设置真实口令。公网多租户、邮件找回、账户删除、角色授权及分布式节流不属于当前交付。
