# 开发环境配置

## 一、配置范围

2026-10-23：M2-04 已在现有 uv training 环境完成真实 Qwen LoRA 更新与基础保存，无新增依赖；运行见 [训练说明](training.md)，实测见 [工作日志](worklogs/2026-10-23-m2-04.md)。独立产物审计与新进程 Adapter 重载仍待后续任务。

本项目在 WSL2 Ubuntu 中开发。Python 使用 uv，前端使用 Node.js/npm，训练使用本机 GPU，Redis 为 Celery 提供队列与结果后端。SQLite 由 Python 标准库与 SQLAlchemy 使用，不需要单独部署数据库服务器。

当前阶段采用原生 GPU Worker。PyTorch cu128 wheel 自带所需 CUDA 用户态运行库，Windows NVIDIA 驱动提供 WSL GPU 透传。现阶段不需要 nvcc 或完整 CUDA Toolkit；未来编译自定义 CUDA 扩展时再安装 Toolkit。WSL 中不额外安装 Linux NVIDIA 显示驱动。

## 二、本机工具与配置

| 项目 | 配置 |
| --- | --- |
| 操作系统 | Ubuntu 26.04.1 LTS / WSL2 |
| Python | uv 管理，3.12，项目 `.venv` |
| Python 依赖 | `uv.lock`，已启用 `training` extra |
| Accelerate | 单 GPU、1 个进程、BF16；配置位于 `data/models/huggingface/accelerate/default_config.yaml` |
| GPU | NVIDIA GeForce RTX 5070 / 12227 MiB，Windows 驱动 617.42 |
| Node.js / npm | 22.23.3 / 10.9.9，前端版本记录在 `frontend/.node-version` |
| Redis | 7.4.11，官方源码标签，提交 `aaf0ce63b3239f4b51f86ca1da8711b055721993` |
| Docker / Compose | Engine 29.9.1 / Compose 5.6.0，已由用户完成系统级安装 |
| VS Code | 已有 Python/Pylance，已安装 Vue 官方扩展 `Vue.volar` |
| 环境文件 | 根目录与前端 `.env` 从对应示例生成，不纳入 Git |

Node 和 Redis 安装在 `~/.local/share/llmcloud-tools/`，命令链接位于 `~/.local/bin/`。当前 shell 配置已将该目录加入 PATH。新终端应能直接运行 `node`、`npm`、`redis-server` 和 `redis-cli`。

`.vscode/settings.json` 指定项目 Python 解释器，`.vscode/extensions.json` 保存编辑器扩展建议；其他个人 VS Code 配置仍被 Git 忽略。

## 三、Python 与前端

```bash
uv sync --locked --extra training
uv run --locked python scripts/check_gpu.py
uv run --locked python scripts/check_environment.py --gpu
```

在此 GPU 开发机器上执行同步时保留 `--extra training`，否则精确同步会移除训练依赖。CPU 服务机器只需 `uv sync --locked`。

Accelerate 的本机默认配置位于项目 HF 缓存中。若使用其 CLI，读取根目录 `.env` 后启动：

```bash
uv run --locked --env-file .env accelerate env
```

配置只负责 Accelerate 启动行为；正式训练的精度和参数仍须在训练代码中明确设置。

```bash
cd frontend
npm ci
npm run build
npm run dev
```

前端 `.env` 中的开发代理默认指向 `http://127.0.0.1:8000`。后端启动：`bash scripts/start_api.sh`。

## 四、本地 Redis

Redis 通过用户级 systemd 服务管理，不依赖 root。用户服务已启用，会在该用户的 systemd 会话启动时启动；没有修改系统 linger 设置。

```bash
systemctl --user status llmcloud-redis.service
systemctl --user start llmcloud-redis.service
systemctl --user stop llmcloud-redis.service
redis-cli ping
```

服务配置位于 `~/.config/systemd/user/llmcloud-redis.service`，执行仓库中的 `scripts/start_redis.sh`：

- 监听 `127.0.0.1:6379`，启用 protected mode。
- DB 0 用于 Celery Broker，DB 1 用于结果后端。
- 数据位于 `data/redis/`，启用 AOF 和周期快照，日志位于 `logs/redis.log`。
- 内存上限 256 MiB，使用 noeviction，避免自动淘汰队列任务。

没有用户级 systemd 会话的环境，可以在终端运行 `bash scripts/start_redis.sh`。不要同时运行本地 Redis 和 `docker compose` 中的 Redis，二者使用相同端口。

启动 Worker 并验证真实异步调用：

```bash
bash scripts/start_worker.sh
```

另开终端：

```bash
uv run --locked python -c 'from worker.tasks import ping; print(ping.delay().get(timeout=10))'
```

## 五、Docker 安装

Docker 是后续容器化与部署所需工具；本地原生 API、Worker 和 Redis 可以先独立运行。安装脚本按 Docker 官方 Ubuntu 仓库方式安装 Engine、CLI、Buildx 和 Compose，启用 Docker 服务并运行 hello-world 验证：

```bash
sudo bash scripts/setup_docker.sh
sudo docker info
sudo docker compose version
sudo docker compose config
```

脚本不会删除已有容器数据；检测到冲突的发行版 Docker/containerd 安装时会停止，避免自动替换现有环境。没有将当前用户加入 docker 组，容器管理使用 `sudo docker`。

本机 shell 使用 HTTP 代理 `http://172.24.224.1:7897`，Docker 守护进程不自动继承 shell 代理。实测 Docker Hub 直连超时，经该代理访问成功；配置方式：

```bash
sudo bash scripts/configure_docker_proxy.sh http://172.24.224.1:7897
```

该脚本写入 `/etc/systemd/system/docker.service.d/llmcloud-proxy.conf`，重启 Docker 并运行 hello-world。代理地址取决于当前 WSL/Windows 网络；若地址变化，重新执行脚本。脚本仅支持不含凭据的本地 HTTP(S) 代理地址。

如改用 Compose Redis，先执行 `systemctl --user stop llmcloud-redis.service`，再执行 `sudo docker compose up -d redis`。GPU 容器与 NVIDIA Container Toolkit 在 GPU Worker 镜像开发阶段配置，当前 Worker 使用原生 PyTorch CUDA 环境。

## 六、验证边界

2026-10-16 已完成：

- Node/npm 安装、`npm ci` 和 Vue 生产构建，npm 检查未发现漏洞。
- Vue/Vite 首页与 `/api` 开发代理实际连通 FastAPI 健康接口；SQLite 建表成功。
- `uv sync --locked --extra training` 与锁文件一致，完整训练依赖导入成功。
- RTX 5070 的 CUDA 前向/反向运算，确认 PyTorch wheel 包含 `sm_120`。
- 随机初始化的极小 Qwen2 模型，在 BF16 下完成 LoRA 前向、梯度回传及一个优化步骤。
- Redis PING、真实 Celery 诊断任务入队、solo Worker 执行及结果读取；临时测试 Worker 已停止。
- Docker/Compose 安装与服务启动、代理配置、Docker Hub 镜像下载和 hello-world 容器运行，均已由用户提供的终端输出确认。

`check_environment.py` 检查工具、依赖版本、配置文件、Redis 连接与 Docker Engine；加 `--gpu` 会执行实际 CUDA 前向和反向运算。当前用户没有 Docker API 权限时，脚本回退检查 systemd 服务状态并明确提示需要 sudo；这项服务状态检查不能替代 `sudo docker run --rm hello-world` 的容器运行验证。

环境就绪与项目功能实现分开：GPU 运算和队列诊断通过，并不表示真实 LoRA 训练、模型推理或完整服务闭环已经实现。模型权重和用户训练数据不纳入 Git。

2026-10-22 M2-02 补验：已缓存固定 revision 的真实 Qwen2.5-0.5B-Instruct，并在禁止 Python 网络连接的独立进程中完成 BF16 GPU 前向；缓存共 9 文件、999,602,607 字节，模型/tokenizer revision 一致。最小前向和模型加载耗时约 2.073 秒（不含缓存哈希与依赖导入），PyTorch 分配显存峰值 1,042,360,320 字节。使用入口、路径优先级与完整证据见 [模型缓存](model-cache.md) 和 [工作日志](worklogs/2026-10-22-m2-02.md)。本次不验证 LoRA 训练、Adapter 或在线推理。

依据：[uv PyTorch 配置](https://docs.astral.sh/uv/guides/integration/pytorch/)、[NVIDIA WSL 用户指南](https://docs.nvidia.com/cuda/archive/13.0.3/wsl-user-guide/index.html)、[Redis 源码安装](https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/install-redis-from-source/)、[Docker Ubuntu 安装](https://docs.docker.com/engine/install/ubuntu/)。
