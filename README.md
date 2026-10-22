# LLMCloud

**LLMCloud: A Cloud-Based Platform for Parameter-Efficient Large Language Model Fine-Tuning**

《云计算技术及应用》课程大作业：一个基于云端异步任务调度的大语言模型参数高效微调服务平台。

项目重点是将数据管理、任务调度、GPU 训练、过程观测和模型交付连接成完整服务。初始模型为 `Qwen/Qwen2.5-0.5B-Instruct`，优先使用 LoRA，后续再考虑 1.5B 模型。

## 一、当前进度

当前完成 **M0：需求理解与项目初始化** 和 **M1：数据管理的计划交付**。

M1 已完成 **M1-01 契约、M1-02 数据集服务层、M1-03 HTTP 接口、M1-04 数据管理页面**。成员 B 交付的工作台已接通真实上传、列表与详情，本次补齐局部修复和浏览器验收；M1-05 故障验收与 CPU CI、M1-06 数据方案/划分工具/冻结题也已完成。M1 计划范围已验收，下一阶段为 M2 真实 LoRA；正式实验语料仍需人工编写和审核。协作前阅读 [AGENTS.md](AGENTS.md) 和 [近期工作日志](docs/worklogs/README.md)；字段与错误见 [M1 接口契约](docs/api/datasets.md)，项目梳理见 [项目记忆](docs/project-memory.md)，页面接续见 [M1-04 日志](docs/worklogs/2026-10-22-m1-04-integration.md)，故障与 CI 见 [M1-05 日志](docs/worklogs/2026-10-22-m1-05.md)，数据来源/划分/冻结题见 [数据方案](docs/data/README.md) 与 [M1-06 日志](docs/worklogs/2026-10-22-m1-06.md)。

- 已建立：项目结构、环境配置、SQLite 元数据表、数据集服务及共享校验、上传/列表/详情 API 和统一错误、FastAPI 健康检查与模型目录、Celery Worker 配置及连通性诊断任务、Vue3 工作台与数据集页面。
- 已定义：数据集格式、训练参数校验、训练输入/输出及进度回调接口、任务状态、后续 API 契约。
- 待开发：正式语料编写/审核、任务创建和查询、真实 LoRA 训练、日志与 Loss 展示、Adapter 下载、模型推理。

`trainer.train` 和 `worker.train` 是明确报错的接口占位，不会生成虚假训练结果。训练与推理界面依照运行时 OpenAPI 控制操作，尚未实现的服务不可提交。

**当前执行 M2 单机真实 LoRA**：[完整开发计划](docs/m2-development-plan.md) 拆为六项任务。M2-01 已完成 [内部训练契约 1.0.0](docs/contracts/training.md)，M2-02 已完成 [固定模型缓存、离线检查与真实 BF16 GPU 前向](docs/model-cache.md)。M2-03 至 M2-06 待开始，下一步数据转换与监督目标检查。任务 HTTP/Celery 接入属于 M3，当前仍不能执行真实 LoRA 训练。

需求与验收标准见 [docs/requirements.md](docs/requirements.md)，模块设计见 [docs/architecture.md](docs/architecture.md)，实验记录模板见 [docs/experiment.md](docs/experiment.md)。两人八周开发安排、分工和阶段验收见 [docs/project-plan.md](docs/project-plan.md)。

## 二、技术方案

| 模块 | 技术 | 职责 |
| --- | --- | --- |
| Web 界面 | Vue3 + Vite | 数据、训练任务与结果的交互入口 |
| HTTP 服务 | Python + FastAPI | 请求校验、元数据与任务管理 |
| 异步调度 | Redis + Celery | 队列与 GPU Worker 派发 |
| 元数据 | SQLite + SQLAlchemy | 用户、数据集与训练任务；后续可迁移 PostgreSQL |
| 模型训练 | PyTorch + Transformers + Datasets + PEFT + TRL + Accelerate | LoRA 训练与 Adapter 保存，待实现 |
| 文件存储 | 本地文件系统 | 数据集、模型缓存、训练产物与日志 |

开发目标环境：Windows 11 + WSL2 Ubuntu + RTX 5070 12GB。一个物理 GPU 只运行一个训练 Worker，暂不引入 Kubernetes 或多 GPU 分布式训练。

## 三、目录结构

```text
LLMCloud/
├── README.md
├── AGENTS.md                   # 成员与 AI 助手协作入口
├── .gitignore
├── .python-version
├── pyproject.toml              # Python 依赖声明与 uv 配置
├── uv.lock                     # 服务与训练依赖的统一锁文件
├── requirements.txt            # 从 uv.lock 导出的兼容文件
├── .env.example
├── compose.yaml                # 开发用 Redis
├── backend/
│   └── app/
│       ├── main.py
│       ├── api/                # HTTP 路由
│       ├── core/               # 配置、数据库
│       ├── models/             # SQL 实体与 API Schema
│       └── services/           # 数据集存储、查询与失败清理
├── trainer/
│   ├── train.py                # 训练接口，后续实现
│   ├── contracts.py            # M2-01 CPU-only 内部类型与一致性校验
│   ├── model_cache.py          # 固定 revision 下载、缓存完整性与配置解析
│   ├── model_probe.py          # 已缓存真实模型的独立 GPU 前向验收
│   ├── dataset.py              # JSONL 格式校验
│   ├── lora_config.py          # 训练参数契约
│   └── requirements.txt        # 含训练依赖的兼容导出
├── worker/
│   ├── celery_app.py
│   └── tasks.py
├── frontend/
│   ├── app.py                  # npm 开发服务器的 Python 辅助启动入口
│   ├── package.json
│   └── src/                    # 实际 Vue3 前端
├── data/
│   ├── datasets/
│   ├── models/
│   └── outputs/
├── logs/
├── scripts/
└── docs/
    ├── requirements.md
    ├── architecture.md
    ├── project-plan.md
    ├── m2-development-plan.md  # M2 任务、分工、依赖与验收
    ├── model-cache.md          # 模型缓存命令与后续 Trainer 接入
    ├── contracts/training.md  # 内部训练协议，配套生成 JSON Schema
    ├── experiment.md
    └── examples/train.jsonl
```

空目录通过 `.gitkeep` 保留。真实数据、权重、日志、数据库和密钥均不提交到 Git。

## 四、启动基础服务

以下命令均在 WSL2 中执行。Python 环境统一由 **uv** 管理，`.python-version` 指定 **Python 3.12**，项目支持 Python 3.11/3.12。前端使用 **Node.js 22.18+ 的 22.x 或 24.12+**。先启动基础服务，无需安装 PyTorch，也无需下载模型。

### 1. 后端

先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)；已有 uv 时跳过：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

重新打开终端，确认 `uv --version` 可用，然后在仓库根目录执行：

```bash
uv python install 3.12
uv sync --locked
cp .env.example .env
bash scripts/start_api.sh
```

`uv sync --locked` 自动创建或同步根目录 `.venv`，按 `uv.lock` 安装服务依赖及 dev 测试组。运行命令统一使用 `uv run --locked`，无需手动激活环境。已有不同 Python 版本的 `.venv` 会按项目版本重新创建；代码、数据和日志不受影响。

打开：

- OpenAPI 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/v1/health>
- 基础模型目录：<http://localhost:8000/api/v1/models>

首次启动创建 `data/llmcloud.db`。健康检查仅表示 API 进程存活；模型目录仅表示允许选择的模型，不表示模型已下载或 GPU 可用。

从 M0 旧库升级时，启动会提示数据集表迁移。先停止 API/Worker，执行 `uv run --locked python scripts/migrate_datasets.py --check`，报告允许后再执行 `--apply`；应用迁移会自动备份，有历史数据时需按工作日志提供可信文件名映射。本机空旧库已完成升级，无需重复重建。

后端测试：`uv run --locked python -m unittest discover -s tests -v`；测试依赖 httpx 在默认同步的 dev 组中，CPU 环境即可执行。真实 HTTP 冒烟：`uv run --locked python scripts/check_dataset_http.py`，会启动临时 API 并使用临时存储。只读存储检查：`uv run --locked python scripts/check_dataset_storage.py --verify-hash`。

上传并查询真实数据（API 启动后执行；上传会创建资源）：

```bash
curl -i http://127.0.0.1:8000/api/v1/datasets -F 'file=@docs/examples/train.jsonl' -F 'name=云计算课程样例'
curl 'http://127.0.0.1:8000/api/v1/datasets?page=1&page_size=20'
curl 'http://127.0.0.1:8000/api/v1/datasets/<实际返回的UUID>'
```

成功上传返回 201、资源元数据与 Location；失败按真实状态码返回统一 error 对象。每次响应包含服务端生成的 X-Request-ID。详情与列表字段、大小限制和样例见接口契约。

### 2. Vue3 前端

另开终端：

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

打开 <http://localhost:5173>。开发服务器将 `/api` 请求代理到后端。也可在根目录运行 `uv run --locked python frontend/app.py` 启动相同的 Vue 开发服务器。Node/npm 仍单独管理。

构建检查：`cd frontend && npm run build`；前端回归：`npm test`；隔离浏览器验收：`npm run test:e2e`（浏览器安装与临时服务说明见 [frontend/README.md](frontend/README.md)）。生产部署时需要由反向代理配置 `/api`，Vite 开发代理不会随 `dist/` 一起生效。

### 3. Redis 与 Worker

本机已安装用户级 Redis，使用项目目录保存数据和日志，可通过以下命令管理：

```bash
systemctl --user start llmcloud-redis.service
redis-cli ping
```

在其他已安装 Redis 的机器上，也可运行 `bash scripts/start_redis.sh` 在前台启动本地开发实例。用户服务与 Docker Redis 共用 6379 端口，二者选一种运行。

若已安装 Docker Engine/Compose 或启用 Docker Desktop 的 WSL 集成：

```bash
docker compose up -d redis
docker compose exec redis redis-cli ping
```

也可使用 WSL 中已有的 Redis，默认连接 `127.0.0.1:6379`。再从根目录运行：

```bash
bash scripts/start_worker.sh
```

Worker 使用 `solo` 池、并发 1、预取 1，并消费训练队列和默认诊断队列。不要为同一块 GPU 重复启动 Worker。

另开终端，在根目录验证队列：

```bash
uv run --locked python -c 'from worker.tasks import ping; print(ping.delay().get(timeout=10))'
```

预期结果：`{'status': 'ok', 'service': 'llmcloud-worker'}`。此检查不执行训练。停止开发用 Redis：`docker compose stop redis`。

环境检查：`uv run --locked python scripts/check_environment.py --gpu`。本机安装位置、版本、Redis 管理和 Docker 安装步骤见 [docs/environment.md](docs/environment.md)。

## 五、准备 GPU 训练环境（M2 前置）

服务依赖位于 `project.dependencies`，训练依赖位于可选的 `training` extra。默认同步安装服务依赖及 dev 测试组，按需启用训练依赖；两者由同一份 `uv.lock` 锁定。当前先使用同一个 `.venv`，未来部署时拆为 CPU API 镜像与 GPU Worker 镜像。

RTX 5070 使用 Blackwell 架构，不能沿用只支持旧 GPU 的 PyTorch wheel。PyTorch 官方从 2.7 开始提供 Blackwell/CUDA 12.8 支持；本项目选择 **2.9.1 + cu128** 作为候选基线。`pyproject.toml` 将 Linux/Windows 的 torch 明确绑定到官方 cu128 索引，其余依赖使用 PyPI。先检查 Windows NVIDIA 驱动与 WSL 透传，再在根目录执行：

```bash
nvidia-smi
uv sync --locked --extra training
uv run --locked --extra training python scripts/check_gpu.py
```

`check_gpu.py` 会执行实际前向和反向 GPU 运算。M2-02 已验证真实 Qwen 基础模型的 BF16 前向，LoRA 训练兼容性仍待 M2-04 验证。普通 `uv sync --locked` 会回到服务依赖及 dev 测试组的环境；训练机器同步时应保留 `--extra training`。`uv run` 默认保留环境中的额外包，因此启动 API 或诊断 Worker 不会卸载已安装的训练依赖。

模型准备与离线检查（首次 prepare 联网下载约 1 GB；check 不联网）：

```bash
uv run --locked --extra training python scripts/prepare_model.py prepare --revision 7ae557604adf67be50417f59c2c2f167def9a775
uv run --locked python scripts/prepare_model.py check --revision 7ae557604adf67be50417f59c2c2f167def9a775
uv run --locked --extra training python scripts/prepare_model.py check --revision 7ae557604adf67be50417f59c2c2f167def9a775 --gpu
```

CLI 显式读取仓库 .env，并统一 HF_HOME 与实际 Hub cache_dir；相对路径按仓库根解析。普通 check 无需训练包，GPU check 需要 GPU 和 training extra；模型/文件清单留在忽略目录。路径优先级、故障语义与队友调用方式见 [模型缓存说明](docs/model-cache.md)。

独立 GPU 环境也可使用 `UV_PROJECT_ENVIRONMENT=.venv-training uv sync --locked --extra training`，运行 Worker 和 GPU 检查时同样设置该变量。

内部训练类型、Schema 和示例无需 GPU：`uv run --locked python scripts/export_training_contract.py --check`。M2-01 将占位 dataclass 改为 Pydantic 关键字构造，保留原导入位置但新增必填 revision/路径等字段，迁移见 [训练契约](docs/contracts/training.md)。格式样例不是模型、训练日志或可下载产物。

相关依据：[PyTorch Blackwell 支持说明](https://pytorch.org/blog/pytorch-2-7/)、[官方历史版本安装矩阵](https://pytorch.org/get-started/previous-versions/)、[Qwen2.5-0.5B 模型卡](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)、[Vue 官方开发环境说明](https://vuejs.org/guide/quick-start)、[uv PyTorch 配置](https://docs.astral.sh/uv/guides/integration/pytorch/)、[uv 锁定与同步规则](https://docs.astral.sh/uv/concepts/projects/sync/)。

### Python 依赖维护

`pyproject.toml` 是依赖声明的唯一来源，`uv.lock` 保存解析后的完整版本。常用命令：

```bash
uv add <package>                         # 添加服务依赖并更新锁文件
uv add --optional training <package>     # 添加训练依赖
uv remove <package>                      # 删除服务依赖
uv lock                                 # 修改声明后更新锁文件
uv lock --upgrade-package <package>      # 定向升级
bash scripts/export_requirements.sh      # 更新两个兼容 requirements 文件
```

修改依赖后一起提交 `pyproject.toml`、`uv.lock` 和导出的 requirements 文件；不要手工修改导出文件或混用 pip 安装来维护项目环境。训练版导出包含服务依赖与训练依赖，供暂不能使用 uv 的工具使用。

## 六、初始数据与参数

第一版接收 UTF-8 JSONL，每行一个对象：

```json
{"instruction":"什么是云计算？","input":"","output":"云计算通过网络按需提供计算、存储等资源。"}
```

`instruction`、`output` 为必填非空字符串；`input` 为可选字符串。样例位于 `docs/examples/train.jsonl`，仅用于格式验证，不足以形成有意义的微调实验。

保守初始参数：LoRA r=8、alpha=16、dropout=0.05、目标层 q_proj/v_proj、batch size=1、梯度累积=8、序列长度=512、epoch=1、learning rate=2e-4、seed=42。它们是实验起点，显存占用需要实测。

## 七、开发路线

执行基线：2 人，每人每周 6–8 小时，2026-10-19 至 2026-12-13。第 5 周形成核心功能闭环，第 6–8 周用于稳定性、云部署和课程交付；具体任务与验收标准见 [八周项目规划](docs/project-plan.md)。

| 阶段 | 内容 | 完成标准 |
| --- | --- | --- |
| M0 初始化 | 结构、文档、基础服务与接口契约 | API 可启动，前端可构建，接口职责明确 |
| M1 数据管理 | JSONL 上传、校验、列表与详情 | 数据落盘并登记元数据，非法输入被拒绝 |
| M2 单机 LoRA | 真实训练、回调、产物导出 | 在 RTX 5070 上训练小数据集并重新加载 Adapter |
| M3 异步调度 | 创建任务、状态流转、失败处理 | 请求立即返回，GPU Worker 串行执行任务 |
| M4 可观测与交付 | 进度、Loss、日志、Adapter 下载 | 浏览器完整观察任务并下载可用产物 |
| M5 测试与部署 | 微调模型推理、Docker、云端适配 | 完成端到端演示及实验报告 |

M2 的工程验收是“真实模型更新 → 保存 Adapter → 退出训练进程 → 新进程重载生成”。正式领域数据编写与审核并行推进，格式草稿只用于工程冒烟。成员 A 主负责训练契约、模型缓存和产物规范，成员 B 主负责数据转换、训练主体和重载；具体文件归属、约 14 人时排期和验收清单见 [M2 开发计划](docs/m2-development-plan.md)。本阶段不要求改动现有前端业务代码。

MVP 采用单用户课程演示模式，用户表仅预留扩展。云端公开服务前需要实现认证、数据权限和资源配额。混合部署需要共享文件访问方案，不能仅把本地路径传给远端 Worker，详见架构文档。
