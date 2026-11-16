# M5 本机容器部署验证（2026-11-15）

运行位置为 E 盘承载的 Ubuntu-22.04/RTX3060 Laptop 6GB。源 checkout 基线为 `3e2e5c349c0b0c38704d04ebcc6a2c80a05f952b` 加本轮未提交修改；镜像清单如实记录 `working_tree_dirty=true`，不能用后续冻结提交改写本次构建身份。部署配置与恢复命令见[部署入口](../deployment.md)。本页不是云端部署通过结论。

## 隔离引擎和镜像

原 Windows Docker Desktop 镜像盘在 C 盘，未向其下载/构建本项目镜像。另将官方 Docker 29.0.1 静态包下载到 `/home/l7/llmcloud-deploy/docker-bin`，用独立 socket、`docker-data` 与 exec-root 启动；项目镜像、构建缓存和运行数据均在 E 盘 ext4。Compose 5.6.0/Buildx 插件只读复用已安装 Docker CLI ISO 后复制到项目私有配置。未安装系统 Docker 服务或开启自启，未迁移/删除原其他项目镜像。

Docker Hub 直连 registry 请求超时。临时 WSL 私网代理中继申请被自动审批拒绝，理由为额外网络暴露/代理滥用面；没有创建或运行中继。随后改用直接 HTTPS 可达的官方 GHCR、ECR 仓库成功拉取基础镜像，不开放代理监听。

- API/Worker：`ghcr.io/astral-sh/uv:0.9.9-python3.12-bookworm-slim`，基础 manifest `sha256:ff651de598f710bada7dddcfb3b9c71ba4ea34669024d60b4b25e1df3b7155b6`。
- Node：`public.ecr.aws/docker/library/node:22.22.0-bookworm-slim`，digest `sha256:dd9d21971ec4395903fa6143c2b9267d048ae01ca6d3ea96f16cb30df6187d94`。
- Redis：`public.ecr.aws/docker/library/redis:7.4-alpine`，digest `sha256:7f7d30b7fdd09467bac58198a1f166dd69789d348d4fe859cccb20e0cf287fbe`。
- nginx：`public.ecr.aws/nginx/nginx-unprivileged:1.28-alpine`，digest `sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8`。

三个应用镜像均真实构建，基础依赖用 `uv sync --locked --no-dev`，Worker 额外使用 training extra。API 容器实际检查 `find_spec("torch") is None` 为 True。原引擎一次并行导出出现 containerd parent snapshot 缺失，串行并关闭额外构建 provenance 后重建完成；保留失败与成功日志，不将该工具问题改写为首轮全部通过。

## GPU 容器

NVIDIA Container Toolkit 1.20.2 四个官方 DEB 只解包到本项目 `nvidia/root`，与官方 Packages 索引 SHA-256 匹配，没有 apt 安装或修改全局 runtime。

| 包 | SHA-256 |
| --- | --- |
| libnvidia-container1 | `466e48e38325bd72ebda9d91653c36f44e71ef9bc261f949689132c892835a4b` |
| libnvidia-container-tools | `a0ded4571083019155661eb53b5fd967d9b83bf7c68516d7e6f489c80caf6946` |
| nvidia-container-toolkit-base | `a6bd7f3a94b0b53b9748872709e70e810473081de0e836a59405073012c49368` |
| nvidia-container-toolkit | `3ea74794dc7fd88526da6fece9fb142e976efac232892fa4c870a96a9708316b` |

使用 `nvidia-ctk cdi generate --mode wsl` 生成私有 CDI spec，独立 daemon 配置其目录；Compose 叠加 `deploy/compose.wsl-cdi.yaml`，标准云端 `driver:nvidia` 路径尚待目标云机验证。Worker 容器真实检查 `torch.cuda.is_available()` 为 True，设备名为 NVIDIA GeForce RTX 3060 Laptop GPU。单 Worker 的 solo/concurrency=1、队列 gpu 和共同锁保留。没有同时启动原生与容器两个 GPU Worker。

## 已完成的真实重启持久化

首轮浏览器业务使用容器 API/前端/Redis、同机唯一原生 Worker：task `21774371-36a6-4b51-b9a1-ef33a0a7bec0`，实际 3 步，上传→真实训练→3 条 Loss/日志→18,068,100 字节下载→64/64 token compare→390px 无溢出通过，录像和报告留 E 盘。原定只在 Worker 设内部 2 步上限不影响 API 冻结的 RuntimeOptions，因此按实测记录为 3 步；之后修正 smoke override 同时配置 API 和 Worker，并直接检查 API `training_max_steps=2`。

该任务终态、原生 Worker warm shutdown 退出后捕获摘要，停止全部容器和独立 daemon，再从原数据盘恢复引擎、重建 CPU 容器并启动 GPU 容器。`check_deployment_persistence.py` 复核结果：

| 内容 | 重启前后结果 |
| --- | --- |
| SQLite integrity_check / foreign_key_check | 均通过 |
| users、auth_sessions、datasets、training_tasks | 各 1 行，表 schema/完整行摘要匹配 |
| 上传数据 | 1 文件，大小/哈希完全匹配 |
| 训练输出 | 13 文件，大小/哈希完全匹配；其中原共享审计覆盖其要求的 12 份产物 |
| 离线模型缓存 | 28 文件，大小/哈希完全匹配 |
| Redis AOF | 专用无正文探针值 `m5-20261115` 重启后保持 |
| 恢复入口 | `http://127.0.0.1:8080/api/v1/health` 200，auth enabled=true |

清单默认仅排除按设计过期清理的 `inference_jobs`。这些数据含会话等私有信息，原始清单/DB不进 Git。工具自身另用明确工程夹具确认 capture、未变 verify 成功，修改输出文件后 verify 拒绝。

## 首轮全容器故障及修复

全容器 task `7d107c92-264d-4b28-ba74-d96197cd243e` 实际失败为 MODEL_LOAD_FAILED，记录保留。根因是 Trainer 原环境采集无条件调用 Git，而安全镜像故意不携带 `.git` 和 Git 程序。不是补造成功或把无 Git 的镜像标成 clean。

修复为：宿主 `scripts/export_build_provenance.py` 从真实 checkout 导出 commit/dirty 与 113 个运行源文件的哈希；额外构建 context 仅将清单复制入 API/Worker。无 `.git` 的 Trainer 必须核对完整文件集合与每项哈希后才允许训练，缺清单或篡改则明确拒绝。有 Git 的普通 checkout 继续使用真实 Git。专项 CPU 检查由主任务记录；本页后续追加修复后容器实测身份与结果。

修复后的 Worker 容器已直接运行实际 `trainer.run_storage.environment(torch)` 成功，记录 Python 3.12.12、CUDA 12.8、GPU 3060、torch 2.9.1+cu128、transformers 4.57.6、datasets 4.8.5、peft 0.18.1、trl 0.25.1、accelerate 1.15.0。实际 code_commit 为上述完整基线，dirty=true；uv.lock SHA-256 为 `e662c32b0db88fa5e2073693740c44fa9529ad6ca7d2f3f2db6c9616f1714b60`。

| 最终本地镜像 | image ID（未推送镜像仓库） |
| --- | --- |
| llmcloud-api:local | `sha256:7a30b6c2f1c187c3be553cfc6f719b89cca6620691e3cf0901a9c953d99760c0` |
| llmcloud-frontend:local | `sha256:01cb2753bf811577eb9d74fb6f763ba6300c9623604ea5abf1acc3f4822ce0f7` |
| llmcloud-worker:local | `sha256:8bff05a060955ad224ef1c411496eac122f538d2203ff9ebf424ca926a459a4f` |

宿主原始来源清单 SHA-256=`f1a5e332bb935b50ea90678c37e40b7be0a37550a98088fc91eec5490ea262a2`；私有 WSL CDI spec SHA-256=`71b8f8989e48f7bd7be9edfc7dde5a28b03ef5fcf8bfb103f6662a11edd2fbaa`；第一轮重启前原清单 SHA-256=`5ae9fca6eb5063876678b698db00a582ae036623a3ac9f17049c42473aed3ade`。这些摘要用于定位原件，不将清单摘要当作新的训练或审查结论。

## 修复后全容器业务与 2026-11-16 最终重启

2026-11-15 的修复后全容器浏览器流程已通过，独立结果见[原摘要](m5-container-demo-results-2026-11-15.json)：task `18c617b2-c024-4911-85f7-cd2f35dd97d1`，2/2 步、19.016 秒、2 条真实指标与日志，compare 为 64/64 token，390px 无溢出。下载 18,067,901 字节，SHA-256=`990f98fdd9ad8aae6e3f8ef7734762cdaacc0109776cab9ff280b01891b73721`；独立解压后原审计通过 12 文件/96 张量/2 指标，逐字节匹配源产物。首轮失败 task 和报告继续保留。

2026-11-16 另做空闲恢复/重启，未新增训练或推理，未改写前述 11 月 15 日原件。原工具前台 daemon 已不运行，先从原 E 盘根以独立 session 恢复引擎，再使用新 `scripts/local_deployment.sh restart` 显式重启四服务。新的原始基线 `evidence/before-final-restart-20261116.json` SHA-256=`e7975d59b5ff478896f052defe12fd05aa05c99b6969c18f0245e746eedd1dd3`，没有覆盖旧清单。

| 最终重启核验 | 实际结果 |
| --- | --- |
| users/auth_sessions/datasets/training_tasks | 各 3 行，全部 schema/行摘要保持；包含新全容器成功任务及原失败任务 |
| datasets / outputs / model cache | 3 / 28 / 28 文件，大小与 SHA-256 全部保持 |
| SQLite integrity/FK | 均通过 |
| health / auth config | HTTP 200 / enabled=true |
| Worker / 共享锁 | Worker 重新 ready；另一独立进程申请原锁被 WorkerLockBusy 拒绝 |
| Redis AOF | 旧探针 `m5-20261115` 仍保持 |
| CPU/GPU 边界 | API 仍未安装 torch；无新增 GPU 请求 |
| 构建来源 | 当前 checkout 113 份被覆盖源码与原镜像清单全部逐字节匹配，差异为空 |

源码原件位于 `E:/LLMCloud/data/deployment-runtime/provenance-01/build-provenance.json`，仍记录实际构建时的 `3e2e5c3... + dirty`。账户冻结提交 `6e1f5e7` 只是后续 Git 关联，不改原实验/镜像身份。小型可解析结果见[最终重启摘要](m5-deployment-final-2026-11-16.json)。持久化保留了会话行与过期时间，不把历史会话跨过期限仍存在写成仍有效；本轮没有重新登录原账号或重跑 GPU compare。

最终入口为 `http://127.0.0.1:8080`，引擎已独立于工具会话运行；一键 start/status/restart/stop 见[部署说明](../deployment.md)。本机关闭或 WSL 停止后无系统自启，需执行 start 恢复。

## 仍需目标环境完成

没有云机、域名或云上持久盘运行结果。标准云端 NVIDIA runtime、真实 HTTPS/Secure cookie、目标服务器旧库迁移/归属和完整业务重启回归尚须在目标环境执行。当前本机 HTTP 只绑定 loopback，不将此结果写成已上线或公网多租户验收。M3/M4追加异步复核按用户本轮要求留到开发完成后统一记录。

原始日志位于 E 盘 ext4 `/home/l7/llmcloud-deploy/evidence`，包括首次/官方直连/最终镜像构建、重启清单及摘要；浏览器录像/报告位于 `E:/LLMCloud/data/local-validation/m5-completion-20261115/` 的独立运行目录。后续失败或成功另记，不覆盖这些原件。
