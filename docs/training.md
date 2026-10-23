# M2-04 单 GPU LoRA 训练

日期：2026-10-23。真实 Qwen LoRA、独立 CLI、指标/回调和基础保存已实现；M2-05 独立产物审计与系统故障验收、M2-06 新进程 Adapter 重载仍待完成。当前没有任务 HTTP/Celery 业务接入，不启用前端训练或推理操作。

## 运行

训练机器先 `uv sync --locked --extra training`，按 [模型准备](model-cache.md) 建立同一固定 revision 的缓存。下列命令使用公开格式样例完成两个优化器更新，不代表正式效果实验：

```bash
uv run --locked --extra training python -m trainer.train \
  --dataset docs/examples/train.jsonl \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775 \
  --max-steps 2
```

省略 --max-steps 时按默认一个 epoch 完整训练；指定后按该优化器步数覆盖 epoch 长度。小数据不足一个梯度累积窗口时，Trainer 在 epoch 尾部执行更新，不能用样本数除以累积次数向下取整来计算 total_steps。最终计划步数直接来自锁定版本 Trainer 的 state.max_steps。

可选 --config 接收仅包含 TrainingConfig 字段的 JSON，例如：

```json
{"logging_steps": 2, "num_train_epochs": 1}
```

其余参数保留契约默认值。精度与步数使用 --precision bf16/fp32、--max-steps，不能混入公共 TrainingConfig。--validation-dataset/--dataset-manifest 指定既有验证集与准备清单；不自动划分，不读取 test 正文。审核状态仍为 unknown 或 draft_unreviewed 时仅用于工程验证。

--task-id 可显式给 UUID，省略时生成；--data-dir/--log-dir/--cache-dir/--env-file 用于可信本机配置，不能作为 HTTP 请求字段。相对路径按仓库根解析，不依赖启动目录。CLI 显式读取 .env 并设置 CUDA_VISIBLE_DEVICES；训练要求单进程、恰好一个可见 CUDA GPU。Python API 调用方应在第一次导入 torch 前设置 GPU 环境。

输出固定为 DATA_DIR/outputs/{task_id}，日志为 LOG_DIR/tasks/{task_id}.log。两者均独占创建，已有输出或日志拒绝覆盖，包括链接别名。没有 --force 或断点恢复。CLI 的 stdout 为成功 TrainResult JSON（含仅供本机使用的路径），进度/框架提示到 stderr；失败输出安全 TrainingFailure JSON 和非零退出码，argparse 参数错误沿用其非零退出行为。

## Python 调用和模块

```python
from trainer.train import train

result = train(request, on_progress=consume_event)
```

request 使用 [契约 1.0.0](contracts/training.md) 的 TrainRequest，原导入位置保留。执行前重验可变嵌套配置并生成独立快照，实际路径重新解析。CLI 授权选择根目录；未来 Worker 须从数据库和受控目录构造请求，不能把 Schema 当作路径授权。

| 模块 | 职责 |
| --- | --- |
| trainer/train.py | 输入、目录、缓存/数据、生命周期与错误边界；CPU 可导入 |
| trainer/cli.py | 本地参数/.env、UUID、配置、stdout/stderr 与退出码 |
| trainer/hf_training.py | 执行时导入训练库；Transformers Trainer + PEFT LoRA |
| trainer/events.py | 验证事件、单写入方、flush 后回调、顺序与有限值检查 |
| trainer/run_storage.py | 配置/环境、实际产物基础检查与成功 manifest 原子提交；M2-05 继续扩展 |

直接使用 M2-03 的 as_feature()、InstructionCollator，保持回答 labels、EOS 与 padding，不重新套模板、packing 或手动 shift。基础模型 BF16/显式 FP32；PEFT 可训练 Adapter 使用其默认的 FP32 上转。固定 AdamW、线性学习率调度、无 warmup、weight_decay=0、梯度裁剪 1、不启用梯度检查点；这些是当前锁定 Trainer 的显式执行策略，不是新增的公开配置项。没有量化或分布式训练。

模型与 tokenizer 从已校验的同一 snapshot_dir 离线加载，不自动联网补缓存；首次下载仍使用 prepare_model.py。RuntimeOptions.local_files_only=false 不会触发自动下载，此入口仍选择更严格的本地缓存路径。保存的 Adapter 基础模型引用为公开模型 ID 和完整 revision，不写本机快照路径。

## 指标和失败

step 为优化器更新步数。train Loss 是框架真实日志窗口的平均值；eval Loss 是对应验证过程的平均值。logging_steps 控制 train 日志和定期验证，最后一个训练窗口强制记录；有验证集时补一次尚未执行的末步验证。同一更新步可有 train、eval 两条记录；无验证集时不产生 eval 事件或补 0。

learning_rate 是事件生成时优化器当前值，在线性调度完成后末步可能为 0；框架 train 日志携带的更新使用值另外写入任务日志的 framework_learning_rate，二者不能混淆。aggregate train_loss/train_runtime 不追加为新的优化器步。

MetricWriter 是 metrics.jsonl 唯一写入方：校验 → write → flush → 同源回调。非有限 Loss/梯度、指标写入失败或核心回调异常均使任务失败，不自动重试、降配或伪造指标。加载阶段只有阶段日志。任务日志记录阶段、参数数目、目标模块、冻结权重前后哈希、变化的 LoRA 张量数；异常诊断只含安全错误及异常类型/栈位置，不输出训练正文和异常原始输入。

每次执行检查只有 LoRA 参数可训练，基础参数无梯度；完整冻结参数字节哈希须前后一致，至少一个 LoRA 张量须更新。保存后读取 safetensors，核对张量与当前 Adapter 逐项相等；检查配置引用、模板哈希和必需文件，登记大小/哈希，最后原子写 manifest.json 才返回 TrainResult。该清单代表本地训练/保存成功，不代表业务数据库状态或新进程重载成功。

失败保留本次日志、failure.json、已写入指标及部分文件，不生成有效成功清单。回调失败时已经 flush 的事件会保留。清理模型、优化器与异常栈内的 GPU 引用；cuBLAS 等库工作区可能在进程内缓存，empty_cache 不承诺 allocated_bytes=0。不要依赖私有 CUDA 清理接口；进程退出后库工作区释放。

## 验收与后续

本机已验证默认参数两步更新、格式草稿包完整 epoch、带验证集的稀疏日志/末步，以及同进程连续两次真实回调失败；命令、实际数值及未测项见 [工作日志](worklogs/2026-10-23-m2-04.md)。CPU CI 无需模型/训练依赖，受控 OOM 替身测试不能声称为真实 OOM。

M2-05 应补独立可复用产物校验入口，检查跨文件/指标/配置/哈希和异常产物，系统验证缺失/损坏/保存失败与目录隔离，审查当前 run_storage 的基础实现。M2-06 在训练进程退出后启动新进程重载 Adapter 并生成；本次没有执行 generate，也没有冻结题评分或正式效果提升结论。
