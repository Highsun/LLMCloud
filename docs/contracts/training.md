# 内部训练契约

版本：**1.0.0**。日期：2026-10-22。范围：M2-01 的 Python 类型、序列化格式和后续执行约定。类型验证与导出已实现，M2-02 已补齐 [模型缓存/检查入口](../model-cache.md)；tokenize、训练、产物写入与 Adapter 重载仍待 M2-03 至 M2-06 实现。

代码来源为 [trainer/contracts.py](../../trainer/contracts.py)，参数沿用 [TrainingConfig](../../trainer/lora_config.py)。[JSON Schema](training.schema.json) 由真实类型生成，不能手改；[样例说明](../examples/training/README.md) 中所有 Loss、revision、哈希、版本和产物条目均为格式示例，不是实验结果。

## 一、调用边界与版本迁移

```text
CLI / 后续 Worker
  → 解析配置、根目录、模型 revision
  → TrainRequest
  → train(request, on_progress)
      → 唯一写入 metrics.jsonl，提供同源 TrainingProgress 回调
      → 保存并检查 Adapter / tokenizer / 配置
      → 最后原子提交成功 manifest
  → TrainResult
```

Trainer 不依赖 FastAPI、Celery、SQL 或后端 Settings；类型导入不加载 torch 等训练库、不创建目录、不连接服务。内部路径只用于可信 CLI/Worker 调用，不公开为 HTTP 请求字段，也不直接把 TrainResult 序列化为 HTTP 响应。后续 Worker 负责数据库状态，Trainer 不写 COMPLETED。

之前未版本化的 dataclass 是占位接口，无已发布训练客户端。本次以 1.0.0 建立可校验的 Pydantic 模型：保留 TrainRequest/TrainingProgress/TrainResult 的原字段名，以及 `from trainer.train import ...` 的导入位置，规范来源改为 `trainer.contracts`。这是内部构造方式的显式变化：

- 改用关键字构造或 `model_validate`，不再使用位置参数或 `dataclasses.asdict`；序列化用 `model_dump(mode="json")` / `model_dump_json()`。
- TrainRequest 新增必填 model_revision、cache_dir、log_path；旧调用不能依赖默认 main revision。task_id 解析为 UUID，配置字典可解析为 TrainingConfig，路径解析为 Path。
- TrainingProgress 新增必填 learning_rate、epoch、recorded_at；TrainResult 新增必填 tokenizer_dir、config_path、manifest_path。
- Request、Progress、Result、Snapshot、Manifest、Failure 均携带固定 contract_version；未知字段或版本被拒绝。后续不兼容格式需升级契约并明确迁移，已存在产物不能静默套用新格式。

契约模型冻结字段赋值，保留原占位对象的值对象用法；这不是深度不可变，嵌套公共 TrainingConfig、列表或字典仍可能被调用方改动，执行时必须先做深拷贝快照。

现有 `TrainingConfig` 的字段、默认值与范围未改；TaskCreate、数据集 Schema、HTTP OpenAPI 均未改，不新增 HTTP API 主版本。当前 `train` 仍抛 NotImplementedError，不能以已构造类型声称完成训练。

## 二、TrainRequest：可信执行输入

| 字段 | 类型／默认 | 约定 |
| --- | --- | --- |
| contract_version | 固定 1.0.0 | 可省略，验证时补默认 |
| task_id | UUID，必填 | CLI 生成 UUID，后续服务使用数据库任务 ID |
| dataset_path | Path，必填 | train JSONL；执行时共用 DatasetScanner/iter_records |
| output_dir | Path，必填 | 独立任务目录，basename 必须等于规范化 task_id |
| base_model | 固定 Qwen/Qwen2.5-0.5B-Instruct | 不接受其他模型或任意本地模型路径 |
| config | TrainingConfig，必填 | 完整训练参数，允许传 `{}` 使用现有默认值 |
| model_revision | 40 位小写十六进制，必填 | 已解析的模型 commit，不接受 main、tag 或短 SHA |
| cache_dir | Path，必填 | HF Hub 实际缓存目录，如 HF_HOME 下的 hub；不是输出目录 |
| log_path | Path，必填 | LOG_DIR/tasks/{task_id}.log |
| validation_dataset_path | Path 或 null，默认 null | 独立验证集；不自动切分上传文件，不自动使用 test/冻结题 |
| dataset_manifest_path | Path 或 null，默认 null | 可选的 prepare_dataset 清单，后续执行时核对实际 train/validation 哈希 |
| runtime | RuntimeOptions，默认值见下表 | 内部运行控制，与公开训练参数分离 |

所有路径必须为绝对路径且不含 `..`；入口根据各机器配置解析根目录，不能硬编码仓库位置或代理。类型校验要求训练/验证路径不同，输入、缓存和任务日志位于输出目录之外，输出不在模型缓存之内。

这些检查只验证结构，不访问文件系统，不能排除符号链接、硬链接、目录别名或数据内容重复。M2-02/03/05 的可信执行入口还要解析真实路径、检查配置根目录、文件/缓存完整性、数据哈希及输出目录不存在；CLI/Worker 负责路径授权，Schema 不是文件系统沙箱。拒绝覆盖已有任务，不提供 force/恢复入口。

HF_HOME 在环境中通常指缓存根，cache_dir 指实际 Hub 缓存目录（默认 HF_HOME/hub）；M2-02 已由 resolve_model_paths 和 prepare_model.py 统一配置，见 [使用说明](../model-cache.md)。不能因为 `.env.example` 写了 HF_HOME 就假定任意 Python 入口自动加载 `.env` 或所有库自动接受 DATA_DIR。仅为结构演示的 request.json 使用 `/srv/llmcloud`，不能直接当作本机运行配置。

### RuntimeOptions

| 字段 | 默认与范围 | 执行语义 |
| --- | --- | --- |
| precision | bf16；仅 bf16/fp32 | 运行前检查 GPU 支持，失败给出原因；不默默改精度 |
| max_steps | null 或严格正整数 | null 按 epoch 计算步数；设定后按该优化器步数停止并覆盖 epoch 训练长度 |
| local_files_only | true，严格布尔值 | 缺缓存时明确失败；首次下载由 M2-02 缓存入口负责，显式 false 才允许加载时联网 |

冒烟选项不进入 TrainingConfig 或 Vue 参数表单。运行时以输入参数深拷贝生成快照，不能在执行中修改调用方配置。模型与 tokenizer 使用相同 revision；tokenizer 如需修改模板，必须另立兼容方案，不能静默覆盖基础模板。

## 三、数据转换与训练参数

保持现有 JSONL：instruction/output 非空，input 可省略。转换为一个 user 消息和一个 assistant 消息：非空 input 时 user 文本为 `instruction + "\n\n" + input`，空 input 时为 instruction；assistant 文本为 output，保留原有字符串，不额外 strip。应用模型 chat template，不额外插入自定义 system，保留模板自身默认行为，特殊 token 只添加一次。

初版不 packing 多条记录；长度限制作用于模板化后的 token 序列，采用右截断。M2-03 检查助手回答标签，用户/系统和 padding 使用忽略标签，有效回答监督 token 必须大于零；截断后无目标时报 NO_SUPERVISED_TOKENS，不静默跳过。不依赖未经检查的模板掩码配置，不另写宽松 JSONL 校验。

| 参数 | 默认 | 保留的约束 |
| --- | --- | --- |
| lora_r / lora_alpha | 8 / 16 | 1–64 / 1–128 |
| lora_dropout | 0.05 | 0 ≤ x < 1 |
| target_modules | q_proj、v_proj | 非空列表；执行时检查模块存在 |
| learning_rate | 0.0002 | 0 < x ≤ 0.01 |
| num_train_epochs | 1 | 1–10 |
| per_device_train_batch_size | 1 | 1–4 |
| gradient_accumulation_steps | 8 | 1–64 |
| max_seq_length | 512 | 64–2048 |
| logging_steps | 1 | 1–100，按优化器更新步数 |
| seed | 42 | 非负整数 |

正式数据复用 prepare_dataset，按问答族隔离 train/validation/test；test 及独立冻结 12 题不用于训练或调参。未传清单或无法验证来源/审核时，结果 review_status 明确为 unknown；格式草稿保留 draft_unreviewed。类型只验证标签取值，不能替代人工审核或清单核对。

## 四、TrainingProgress 与 metrics.jsonl

每行一个完整 UTF-8 JSON 对象，不写数组或跨行对象。契约类型为 TrainingProgress：

| 字段 | 类型／约束 | 含义 |
| --- | --- | --- |
| contract_version | 固定 1.0.0 | 序列化包含 |
| kind | train（默认）或 eval | 区分训练/验证；loss 的含义由 kind 确定 |
| step / total_steps | 严格正整数，step ≤ total_steps | 实际优化器更新步数；不把微批次或加载阶段计为步数 |
| loss | 非负有限数 | train 为训练框架该日志窗口的真实 Loss；eval 为该次验证平均 Loss |
| learning_rate | 非负有限数 | 事件时优化器学习率，可为 0 |
| epoch | 非负有限数 | 框架报告的 epoch 进度，可为小数 |
| recorded_at | 带时区 datetime / RFC 3339 | 序列化归一为 UTC；不接受朴素时间或数字时间戳 |

单个事件验证步数边界；序列顺序由 M2-04 写入器保证：train 的 step 严格增加，同一更新步允许随后写一个 eval 事件，同一种 kind 不重复同一步。total_steps 在运行开始确定；以训练框架实际计算值为准，max_steps 非 null 时等于该值。M4 增量查询后续另行约定游标，不能仅凭本事件假定按 step 可以无遗漏读取 train/eval。

Trainer 先写入并 flush 真实事件，再以相同字段值调用 on_progress。只由 Trainer 追加 metrics，Worker 不重复写。指标写入或核心回调失败使训练失败，不吞异常、不自动重试。加载/预处理阶段通过日志说明，不产生零 Loss 或虚假进度。没有执行验证就没有 eval 事件；summary.eval_loss 为 null，不填 0。

## 五、TrainResult、配置快照与成功清单

TrainResult 的 adapter_dir、metrics_path、tokenizer_dir、config_path、manifest_path 均为内部绝对 Path，必须处于同一个任务目录，名称分别为 adapter、metrics.jsonl、tokenizer、training_config.json、manifest.json。类型验证只检查布局；M2-05 执行时验证文件后才返回结果，M2-06 再做独立进程加载。

文件相对 output_dir 的布局：

```text
adapter/adapter_model.safetensors
adapter/adapter_config.json
tokenizer/tokenizer_config.json    # 还需保存实际 tokenizer 的其他必要文件
metrics.jsonl
training_config.json
manifest.json
checkpoints/                      # 可选，非下载产物清单
```

training_config.json 对应 TrainingSnapshot：contract_version、task_id、base_model、model_revision、完整 config 和 runtime，既用于追溯，也供未来重载检查。不得把整个 TrainRequest 直接写进去，以免导出内部路径。

manifest.json 对应 TrainingManifest，包含 TrainingSnapshot 全部字段及：

| 字段 | 内容与约束 |
| --- | --- |
| status | 仅 completed；不存在失败成功混合清单 |
| tokenizer_revision / chat_template_sha256 | revision 与 model_revision 一致，模板 UTF-8 原文 SHA-256 为 64 位小写十六进制 |
| train_dataset | DatasetSummary：原始文件字节 sha256、正整数 size_bytes/row_count、review_status；可选 16 位 build_id |
| validation_dataset | DatasetSummary 或 null；不能从 train 统计推断 |
| environment | RunEnvironment：40 位代码 commit、严格布尔 working_tree_dirty、uv_lock_sha256、Python/CUDA runtime/GPU 名称、包版本字典 |
| started_at / finished_at | 带时区时间归一 UTC，结束不早于开始 |
| summary | TrainingSummary，统计与单位见下文 |
| artifacts | ArtifactFile 列表：相对路径 path、文件原始字节 sha256、正整数 size_bytes；无重复，至少覆盖上述五个必需文件 |

environment.packages 必须记录 torch、transformers、datasets、peft、trl、accelerate 的实际版本，可补充其他库。记录锁文件哈希和实际安装版本，两者不能互相替代。未知 provenance 不伪造，不能自动将审核状态升为 reviewed。

summary 包含 completed_steps、total_steps（成功时相等），elapsed_seconds（有限非负数，覆盖本次调用到最终清单提交前的加载/预处理/训练/保存校验，不含新进程重载），peak_memory_allocated_bytes（本次单 GPU 分配显存峰值字节，不是整卡显存或 reserved 值），trainable_parameters、total_parameters（均为正，可训练参数少于总参数），final_loss（最后 train 事件的 Loss）与可空 eval_loss（最后 eval 事件的 Loss）。具体是否真正冻结基础参数、统计是否真实，必须由执行与 GPU 验证证明，Schema 不能证明。

artifact path 使用规范相对 POSIX 键，拒绝绝对路径、反斜杠、冒号、控制字符、`..`、重复斜杠或 `./`。仅允许 adapter/、tokenizer/ 下文件以及 metrics.jsonl、training_config.json；不包含数据、日志、检查点、完整基础模型或 manifest 自身，避免自哈希循环。文件与声明哈希必须由 M2-05 核对，不能仅通过 JSON 类型验证就宣布产物可用。

保存顺序：独占创建新任务目录 → 写配置/真实指标/Adapter/tokenizer → 检查必需文件、配置和哈希 → 写临时清单并原子提交 manifest.json → 返回 TrainResult。中途失败允许留下本次部分文件供诊断，但不能有有效成功 manifest；不能删除输入、缓存或其他任务。未来数据库完成状态晚于该流程。manifest 不声称已完成 M2-06 新进程验收。

## 六、失败边界

TrainingFailure 字段为 contract_version、可空 task_id、稳定 code、stage、message。message 为 1–1000 字符的安全说明，不嵌入原始样本、令牌、内部路径或 traceback。类型约束不自动清理文案，构造方负责安全内容；完整必要诊断留在受控任务日志。TrainingError 携带 `.failure`，后续执行层使用该异常向上传递。

| code | 典型条件 | 常用 stage |
| --- | --- | --- |
| INVALID_REQUEST | 配置、路径、revision 或输出冲突 | preflight |
| INVALID_DATASET | 扫描、数据清单/哈希不匹配 | data_preparation |
| MODEL_NOT_CACHED | 本地模式下指定 revision 缓存不完整 | model_loading / reloading |
| MODEL_LOAD_FAILED | 权重、tokenizer、精度或设备加载失败 | model_loading / reloading |
| NO_SUPERVISED_TOKENS | 模板/截断后没有有效回答目标 | data_preparation |
| CUDA_OUT_OF_MEMORY | 实际捕获的显存不足 | model_loading / training / reloading |
| TRAINING_FAILED | 非上述明确类型的训练异常 | training |
| ARTIFACT_WRITE_FAILED | 指标、配置、权重、日志或清单写入失败 | saving；训练期间指标写入可为 training |
| INVALID_ARTIFACT | 产物缺失、损坏、哈希/revision 不符 | saving / reloading |
| PROGRESS_CALLBACK_FAILED | 核心进度回调异常 | callback |

code 与 stage 分别验证取值，上表是映射指南，不是静态的一对一绑定。JSON 解析错误/Pydantic ValidationError 在可信 CLI/Worker 边界转为 INVALID_REQUEST；复用 DatasetValidationError 转为 INVALID_DATASET，保留适当行号于任务日志，不另造宽松解析器。不能把包含原始 input 的完整 ValidationError 字符串直接公开。

CLI 成功 exit 0，执行失败非零；无自动重试或隐式降配。后续 Worker 映射业务 FAILED，不能把错误响应作为成功结果返回。此内部失败格式不是已有 HTTP ErrorResponse；M3 对外映射时单独定稿 HTTP 状态与安全字段，不提前借用 Celery 状态或现有 API 错误 code。

## 七、导出与验证

```bash
uv run --locked python scripts/export_training_contract.py
uv run --locked python scripts/export_training_contract.py --check
uv run --locked python -m unittest discover -s tests -p test_training_contract.py -v
```

导出内容为 JSON Schema 定义集合（从 `$defs/TrainRequest` 等入口使用）和六个示例文件；不是 OpenAPI，也不写数据目录。`--check` 只检查漂移，缺失或不一致时失败、不修复。CI 包含契约行为检查与导出漂移检查。

Pydantic 还验证跨字段一致性，JSON Schema 无法独自表达所有 Python 校验；执行时使用模型验证，再按各任务完成真实 I/O/GPU 校验。M2-01 的 CPU 检查不要求模型下载、训练依赖或 GPU，也不替代 M2-02 至 M2-06 的验收。
