# 内部训练格式样例

配套 [训练契约 1.0.0](../../contracts/training.md)。**这些文件全部是格式示例，不是训练记录，也没有对应的模型或 Adapter。** revision、哈希、Loss、耗时、显存、包版本与文件大小均为人为占位；0.0.0 不是本项目实际安装版本，`/srv/llmcloud` 不是成员机器路径。不能拿这些文件执行真实训练或声称 GPU 验收通过。

| 文件 | 类型 | 用途 |
| --- | --- | --- |
| request.json | TrainRequest | 演示可信内部调用，不是 HTTP 请求体 |
| progress.jsonl | TrainingProgress，每行一个 | 两个 train 事件与同一步 eval 事件，均为示例数值 |
| result.json | TrainResult | 内部产物定位，不可直接作为 HTTP 响应 |
| training_config.json | TrainingSnapshot | 可分享配置快照，不含内部绝对路径 |
| manifest.json | TrainingManifest | 成功清单的格式示例，不存在对应文件可供下载 |
| failure.json | TrainingFailure | 内部稳定错误码与阶段，不是 HTTP ErrorResponse |

由 `uv run --locked python scripts/export_training_contract.py` 从真实类型生成，`--check` 检查漂移。不要手改单个生成文件；改动类型时同步契约与生成器。未知来源/审核状态应保留 unknown，此示例显式标记 draft_unreviewed。未来真实结果保存在被忽略的 data/outputs/、logs/ 下，不提交到此目录。
