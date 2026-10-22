# 需求理解与 MVP 验收标准

## 一、项目定位

项目名称：LLMCloud。

英文名称：LLMCloud: A Cloud-Based Platform for Parameter-Efficient Large Language Model Fine-Tuning。

项目将大语言模型参数高效微调封装为 Web 服务，体现云计算中的服务接口、异步调度、资源管理和可观测性。单个训练脚本是系统内部计算模块，完整交付还包括数据、任务和模型产物管理。

M0 和 M1-01 至 M1-03 已完成，数据集后端已支持真实 HTTP 上传/列表/详情与统一错误。M1-04 页面与基本浏览器功能验收已完成，M1-05 故障验收/CPU CI 与 M1-06 数据方案、划分工具和冻结题已完成；正式语料仍需人工编写/审核。成员与 AI 助手先读 [协作约束](../AGENTS.md) 和 [工作日志](worklogs/README.md)，数据集字段、分页与公共错误以 [M1 接口契约](api/datasets.md) 为准，本次验证见 [M1-03 日志](worklogs/2026-10-21-m1-03.md)。

## 二、开发约束

- 主要开发环境：WSL2 Ubuntu + VS Code Remote WSL。
- 本地 GPU：RTX 5070 Desktop，12GB 显存。
- 初始模型：Qwen2.5-0.5B-Instruct；后续考虑 Qwen2.5-1.5B-Instruct。
- 初始训练方式：LoRA，暂不引入量化、FlashAttention 等额外兼容性变量。
- 元数据先用 SQLite，文件先用本地磁盘。
- 同一 GPU 串行训练，暂不引入 Kubernetes、多 GPU 分布式训练、计费或多租户系统。
- 前端明确采用 Vue3。保留原结构中的 `frontend/app.py` 作为辅助启动脚本。

## 三、功能与验收

| 用户动作 | MVP 行为 | 验收标准 |
| --- | --- | --- |
| 上传数据集 | 上传并验证 UTF-8 JSONL | 合法文件可查询；空数据、字段错误、超限上传被拒绝 |
| 选择基础模型 | 从受控模型目录选择 | 第一版仅允许 Qwen2.5-0.5B-Instruct |
| 配置 LoRA | 校验参数并保存快照 | 非法参数返回 422；查询任务得到原始配置 |
| 提交任务 | 数据库登记后派发 Celery | HTTP 不等待训练，返回任务 ID；队列失败可见 |
| 查询状态 | 查询数据库中的业务状态 | 支持 PENDING、QUEUED、RUNNING、COMPLETED、FAILED |
| 查询进度与 Loss | Worker 上报步数、Loss，前端轮询 | 真实训练时曲线增长；任务失败显示原因 |
| 查看日志 | 按任务读取有限日志尾部 | 日志不跨任务，响应有大小限制 |
| 下载 Adapter | 下载任务专属产物包 | 仅完成任务可下载，包内有权重、配置和训练参数 |
| 测试推理 | 加载原始基础模型与 LoRA Adapter | 用户可输入提示词得到输出，结果关联具体任务 |

MVP 的训练与推理使用同一 GPU 时需要互斥；训练期间推理返回资源忙，前端提示稍后重试。后续可将推理接入相同调度器。

## 四、状态语义

- `PENDING`：元数据已持久化，尚未确认派发。
- `QUEUED`：队列已经接受任务，等待 Worker。
- `RUNNING`：Worker 成功领取任务，正在加载模型或训练。
- `COMPLETED`：训练完成且可加载的 Adapter 和结果清单已写入。
- `FAILED`：校验、派发、执行或产物保存失败，记录错误原因。

派发失败进入 FAILED。Worker 的 RUNNING 更新必须兼容读取到 PENDING 或 QUEUED，防止快速领取与 API 更新竞争；API 只在当前仍为 PENDING 时更新 QUEUED。数据库业务状态与 Celery 内部状态分开。

## 五、后续 HTTP 接口契约

所有业务接口使用 `/api/v1` 前缀，UUID 标识实体。下表中健康检查和模型目录在 M0 实现，数据集三个接口在 M1-03 实现；其余接口在相应里程碑实现。

| 方法与路径 | 输入 | 输出/行为 | 阶段 |
| --- | --- | --- | --- |
| `GET /health` | 无 | API 进程存活与版本 | M0 |
| `GET /models` | 无 | 基础模型白名单，不表示缓存就绪 | M0 |
| `POST /datasets` | multipart `file`，可选 `name` | 201；DatasetDetail，含哈希与原始文件名 | M1 |
| `GET /datasets` | `page=1`，`page_size=20`（最大 100） | DatasetPage；固定时间/ID 倒序 | M1 |
| `GET /datasets/{id}` | 数据集 UUID | DatasetDetail 或 404 | M1 |
| `POST /tasks` | dataset_id、base_model、config | 202；任务 ID 与状态 | M3 |
| `GET /tasks` | 状态、分页参数 | 任务列表 | M3 |
| `GET /tasks/{id}` | 任务 ID | 状态、步数、进度、时间与错误 | M3 |
| `GET /tasks/{id}/metrics` | 游标 after_step | step/loss/learning_rate/epoch 数据点 | M4 |
| `GET /tasks/{id}/logs` | 有上限的 tail 参数 | 日志尾部 | M4 |
| `GET /tasks/{id}/adapter` | 任务 ID | ZIP 下载；未完成返回 409 | M4 |
| `POST /inference` | task_id、prompt、max_new_tokens | 生成结果；GPU 忙返回 409 | M5 |

任务配置 JSON 示例：

```json
{
  "dataset_id": "<已上传数据集的 UUID>",
  "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
  "config": {
    "lora_r": 8,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "target_modules": ["q_proj", "v_proj"],
    "learning_rate": 0.0002,
    "num_train_epochs": 1,
    "per_device_train_batch_size": 1,
    "gradient_accumulation_steps": 8,
    "max_seq_length": 512,
    "logging_steps": 1,
    "seed": 42
  }
}
```

文件上传上限为 50 MiB，整个 multipart 请求体上限为 50 MiB + 64 KiB；超限返回 413，格式错误返回 422，实体不存在返回 404。保存时使用系统生成 ID，客户端文件名仅作显示，API 不接收任意文件系统路径。

## 六、分阶段交付

M0 完成后，按 M1 数据管理 → M2 单机真实训练 → M3 异步任务 → M4 观测与下载 → M5 推理及部署推进。先证明训练模块能够在目标 GPU 上产生可加载产物，再将其接入异步调度。

M2 按 [六项开发计划](m2-development-plan.md) 推进：M2-01 已完成 [内部训练契约与 CPU 类型](contracts/training.md)，M2-02 已完成 [模型缓存、离线校验与真实 GPU 前向](model-cache.md)；数据处理、LoRA 训练、产物交付和 Adapter 新进程重载仍待实现。工程验收要求真实 LoRA 权重更新、真实指标、可追溯产物与独立进程生成；正式领域语料并行编写/审核，效果是否提升按既有评测协议客观记录。M2 不新增任务/推理 HTTP 服务，不因独立 Trainer 可用就启用对应前端提交入口。

最终课程演示：上传小型真实数据集，提交两项任务并展示串行队列，观察 Loss 和日志，下载 Adapter，比较微调前后对固定问题的回答，并演示一项失败任务的错误反馈。
