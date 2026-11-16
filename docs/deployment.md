# M5 单机部署与重启验证

本入口提供 API、静态前端/同源反代、Redis 和唯一 GPU Worker 的部署配置。当前实际验证范围见[部署结果](testing/m5-deployment-2026-11-15.md)，配置存在和镜像构建成功均不能替代云端完整业务验收。

## 持久化布局与前提

使用 Linux x86_64、Python 3.12 镜像、Docker Compose v2.17+（支持额外构建 context）、兼容 CUDA 12.8 的 NVIDIA 驱动和 NVIDIA Container Toolkit。单台主机共享 SQLite、数据和输出，不将 SQLite 放 NFS，不在不同机器分别挂载不同副本。WSL 实际服务的数据与日志应位于 E 盘承载的 ext4 文件系统，不能以 `/mnt/d`、`/mnt/e` 的文件语义替代已有 Linux fd/NOFOLLOW/flock 安全检查。

| 宿主路径变量 | 容器路径 | 使用方和含义 |
| --- | --- | --- |
| `LLMCLOUD_STATE_DIR/data` | `/app/data` | API/Worker 共用；SQLite、上传 JSONL、任务输出、临时下载；写权限 |
| `LLMCLOUD_STATE_DIR/logs` | `/app/logs` | API/Worker 共用；实例锁及运行日志；不得删除/替换活锁文件 |
| `LLMCLOUD_STATE_DIR/redis` | `/data` | Redis AOF；无宿主端口 |
| `LLMCLOUD_MODEL_DIR` | `/app/models/huggingface` | 已完整核验的 HF_HOME，包含 `hub/`；API/Worker 只读、离线 |
| Docker data-root | 镜像与构建缓存 | 本机必须在 E 盘承载的文件系统；云机用持久盘 |
| `LLMCLOUD_PROVENANCE_DIR` | 构建时复制为 `/app/build-provenance.json` | 由有 Git 的宿主导出的源码来源与哈希；不复制 `.git` 或凭据 |

API 镜像只安装基础锁定依赖，不安装 training extra。Worker 安装同一 `uv.lock` 的 training extra，直接 `python -m worker` 保留唯一实例锁、solo/concurrency=1/prefetch=1 和训练/推理互斥；不通过 Compose 扩 Worker 副本。停止 Worker 前等待当前训练/推理完成，10 分钟 graceful stop 只是上限，不能保证任意长训练不被终止。

复制 `deploy/compose.env.example` 到 E 盘私有位置，修改绝对路径、UID/GID、端口。原模型缓存只读复用；不要将模型下载放进镜像构建。镜像构建上下文通过 `.dockerignore` 排除 `.env`、数据、日志、模型、仓库历史和前端依赖缓存。不要通过删除持久盘/数据库解决迁移错误，也不要执行 `docker compose down -v` 作为升级步骤。

构建前必须在有 Git 的源 checkout 运行 `scripts/export_build_provenance.py`，输出到新建的私有 E 盘目录，再把该目录设为 `LLMCLOUD_PROVENANCE_DIR`。它记录真实 40 位 commit、工作区 dirty 状态和全部运行 Python 文件及 README/pyproject/lock 的 SHA-256；API/Worker 通过额外 context 复制该清单。容器内无 `.git` 时，Trainer 逐项校验完整代码集合和字节后才使用该来源；缺失/不符明确失败，不假报 clean。任何被覆盖文件变化后都要生成新目录清单并重建，旧清单保留为旧镜像证据。这是可审计的构建来源说明，不是签名认证。

## 首次准备和启动

以下命令在仓库根目录的 Linux shell 执行；`DEPLOY_ENV` 是私有配置文件路径，不是仓库 `.env`：

```bash
export DEPLOY_ENV=/home/l7/llmcloud-deploy/compose.env
cp deploy/compose.env.example "$DEPLOY_ENV"
# 先编辑 DEPLOY_ENV，确认每个路径和 UID/GID。
mkdir -p /home/l7/llmcloud-deploy/state/{data,logs,redis}
# data/logs 由配置的应用 UID/GID 写入；新目录由部署用户创建。
docker info --format '{{.DockerRootDir}}'
docker compose --env-file "$DEPLOY_ENV" config --quiet
python scripts/export_build_provenance.py \
  --output /home/l7/llmcloud-deploy/provenance/build-provenance.json
docker compose --env-file "$DEPLOY_ENV" build
docker compose --env-file "$DEPLOY_ENV" up -d
docker compose --env-file "$DEPLOY_ENV" ps
curl --fail http://127.0.0.1:8080/api/v1/health
```

示例中的 `/home/l7/llmcloud-deploy` 仅为当前 WSL 的 E 盘 ext4 路径；云机应换为自己的持久盘。Redis 镜像初始以 root 修正其私有目录所有者再降权，API/Worker 固定以应用 UID/GID 运行。若宿主目录已存在且属于其他用户，先只对本项目目标目录核对权限，不能递归改整个磁盘权限。

默认只发布 `127.0.0.1:8080`，API/Redis 均不直接发布到宿主。受限远程演示通过 SSH 隧道访问：

```bash
ssh -N -L 8080:127.0.0.1:8080 user@cloud-host
```

浏览器访问 `http://127.0.0.1:8080`。若另设 HTTPS 入口，先配置真实域名/证书、访问控制和准确 CORS origins，再设 `AUTH_COOKIE_SECURE=true`。当前 nginx 同源 `/api/` 保留 cookie；upstream 等待 125 秒以让服务端 90 秒结构化超时到达浏览器；不重试 POST、不将 90 秒前截断成 nginx 默认 60 秒 HTML 错误。

## 旧库升级与账号

新空库可直接启动。旧库必须先停 API/Worker，备份并执行显式迁移检查/应用。登录注册及归属迁移以[认证说明](authentication.md)和 `scripts/migrate_auth.py --help` 为准；数据集和任务的既有迁移分别为 `scripts/migrate_datasets.py`、`scripts/migrate_tasks.py`。不能靠 `create_all` 补旧字段，不能将历史单用户数据静默分配给刚注册的人。

Compose 默认 `AUTH_ENABLED=true`，会话通过 HttpOnly/SameSite cookie 工作。本机 HTTP 的 `AUTH_COOKIE_SECURE=false`；部署到 HTTPS 后必须切换 true。`AUTH_SESSION_SECONDS=43200` 为默认 12 小时。不要将账号密码、会话 cookie、数据库备份或私有环境文件写入报告/Git。

## 镜像网络受限

可使用官方、可直接访问的公共仓库；本机 2026-11-15 已确认 Docker Hub 直连失败而 GHCR/ECR 可达，可在私有 env 中设置：

```dotenv
REDIS_IMAGE=public.ecr.aws/docker/library/redis:7.4-alpine
NODE_IMAGE=public.ecr.aws/docker/library/node:22.22.0-bookworm-slim
NGINX_IMAGE=public.ecr.aws/nginx/nginx-unprivileged:1.28-alpine
```

Python/uv 基础镜像默认来自官方 GHCR。构建完成后记录实际 image digest 与源提交，演示前不要临时升级依赖或镜像。不要为下载自动向网络开放本机代理；本机额外代理中继申请曾被自动审批拒绝，后续使用官方仓库直接 HTTPS 连接。

## 重启后持久化的可执行检查

先完成一次真实流程，等待全部任务终态且无推理；停止用户写入，在 E 盘记录清单，然后重启。清单只存摘要与路径，不复制权重；完整清单仍留 E 盘，不提交 Git。

```bash
python scripts/check_deployment_persistence.py capture \
  --state-dir /home/l7/llmcloud-deploy/state \
  --model-dir /home/l7/LLMCloud/data/models/huggingface \
  --manifest /home/l7/llmcloud-deploy/evidence/before-restart.json
docker compose --env-file "$DEPLOY_ENV" restart
docker compose --env-file "$DEPLOY_ENV" ps
curl --fail http://127.0.0.1:8080/api/v1/health
python scripts/check_deployment_persistence.py verify \
  --manifest /home/l7/llmcloud-deploy/evidence/before-restart.json
```

脚本读事务执行 SQLite integrity/foreign-key 检查，比较各持久表 schema/行摘要及 datasets、outputs、HF cache 文件 SHA-256；默认仅排除应过期清理的 `inference_jobs`。用户与会话表保留在比较中。工作负载、会话过期/重新登录或新注册均会改变内容，故必须在空闲时间窗内执行。Redis AOF 可另用不含用户正文的专用探针 key 在 restart 前后核对，再删除该探针。

字节/行保持是必要条件；仍应在原账号登录后确认原数据列表/详情、任务状态、Loss/日志和 Adapter 下载可读，并实际完成一次推理对比。下载 ZIP 必须解压后复用 `scripts/check_training_artifacts.py` 原审计入口（具体参数见 `--help`）；不能将 ZIP magic 或文件存在当作审计通过。

## 演示与云端验收

按[演示脚本](course/demo-script.md)执行：注册/登录 → 上传工程样例 → 配置真实训练 → 看真实 Loss/日志 → 下载并审计 → 基础/Adapter 对比 → 空闲重启后复查。工程演示可额外使用 `-f deploy/compose.smoke.yaml`，同时在 API 与 Worker 设置内部 `TRAINING_MAX_STEPS=2`；上限由 API 创建任务时冻结进 RuntimeOptions，仅设置 Worker 不会改变已有任务快照。不改公开训练字段、不混为 E01 正式实验，正式训练不叠加该 override。E01 沿用既有 1 epoch 结果。

本机 E 盘独立 WSL daemon 使用私有 NVIDIA CDI 目录，额外叠加 `-f deploy/compose.wsl-cdi.yaml`（需要 Docker 25+ 和已生成/登记的 CDI spec），与标准云机已配置 NVIDIA runtime 的 `compose.yaml` 区分记录。本机完整工程命令为：

```bash
docker compose --env-file "$DEPLOY_ENV" -f compose.yaml \
  -f deploy/compose.smoke.yaml -f deploy/compose.wsl-cdi.yaml up -d --no-build
```

### 当前本机独立引擎的恢复和停止

推荐在仓库根目录的 Windows PowerShell 直接运行一键入口：

```powershell
wsl -d Ubuntu-22.04 -u root -- bash scripts/local_deployment.sh start
wsl -d Ubuntu-22.04 -u root -- bash scripts/local_deployment.sh status
wsl -d Ubuntu-22.04 -u root -- bash scripts/local_deployment.sh restart
wsl -d Ubuntu-22.04 -u root -- bash scripts/local_deployment.sh stop
```

该入口只操作现有项目私有引擎和三个 Compose 文件，不安装软件、不下载/重建镜像、不配置系统自启。`start` 通过独立 session 启动 daemon，stdin/stdout/stderr 脱离调用终端，随后恢复四服务，因此关闭工具会话后仍可继续访问。`restart/stop` 先只读检查数据库无排队/运行训练和活推理；调用前仍需停止新的用户提交。`stop` 在四服务停止后验证 PID/cmdline/data-root 再停止本项目 daemon，不影响其他 Docker context。电脑或 WSL 关闭后需要重新执行 `start`。2026-11-16 已实际检查恢复、四服务重启、持久化及共享锁。

实际引擎是 E 盘承载的 Ubuntu-22.04 内的 `/home/l7/llmcloud-deploy/docker-bin/dockerd`，数据根为同目录 `docker-data`，socket 为 `docker-run/docker.sock`，与原 C 盘 Docker Desktop 引擎分开。工具只解包在该项目目录，没有 apt 安装、系统自启或全局 runtime 配置。NVIDIA 1.20.2 的四个 DEB 依官方包索引 SHA-256 校验后解包到 `nvidia/root`；`nvidia-ctk cdi generate --mode wsl` 的 spec 在 `nvidia/cdi/nvidia.yaml`，hook 指向同一私有目录的 `usr/bin/nvidia-cdi-hook`。

在 **WSL root shell** 中设置本项目 CLI 环境（普通用户无权访问 root-owned socket；不要将 Docker socket 开放给网络）：

```bash
export PATH=/home/l7/llmcloud-deploy/docker-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DOCKER_HOST=unix:///home/l7/llmcloud-deploy/docker-run/docker.sock
export DOCKER_CONFIG=/home/l7/llmcloud-deploy/docker-config
export DEPLOY_ENV=/home/l7/llmcloud-deploy/compose.env
docker info --format '{{.DockerRootDir}}'
```

以下前台命令仅用于手工诊断，终端关闭时进程可能退出；常规启动使用上方会脱离工具会话的一键 `start`。手工诊断时保留专用终端，不能同时启动两个指向同一 data-root 的 daemon：

```bash
dockerd --host "$DOCKER_HOST" \
  --data-root /home/l7/llmcloud-deploy/docker-data \
  --exec-root /home/l7/llmcloud-deploy/docker-run/exec \
  --pidfile /home/l7/llmcloud-deploy/docker-run/docker.pid \
  --bip 172.29.100.1/24 \
  --cdi-spec-dir /home/l7/llmcloud-deploy/nvidia/cdi
```

手工诊断模式下，另一个 root shell 在仓库根目录执行上面的三文件 `compose ... up -d --no-build` 恢复服务；结束时等待任务终态，先 `compose ... stop`，再在诊断专用终端按 Ctrl+C。常规停止直接使用一键 `stop`，它同时核对 PID/data-root 后停止私有 daemon。保持模型目录原路径可读，不要复制整份模型到仓库或 D 盘。不删除 `state`、`docker-data`、`nvidia` 或 Worker 锁文件。重启前后检查仍用本文清单命令；不同项目的默认 `docker` context 不属于本部署。

`local_deployment.sh` 为宿主恢复入口，不由运行中的镜像加载，不属于已验证的 113 份 Python/配置来源集合。`.gitattributes` 对 `scripts/*.sh` 和 `deploy/*` 固定 LF，避免 Windows checkout 将 shell 入口转换为 CRLF。

云端仍需提供真实单 GPU 主机和持久盘，在目标环境实际完成上述流程、重启、权限/归属及旧库迁移回归，记录域名/入口、镜像摘要、运行身份与缺口，才能写云部署通过。M3/M4 追加异步复核按用户新安排留至开发完成后统一进行，不能由部署作者代写另一位成员的复核结论。
