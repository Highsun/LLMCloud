# M2-05 训练产物交付与审计

日期：2026-10-23。状态：共享产物校验器、独立 CPU 审计命令和保存故障验收已完成。训练及审计都不表示 Adapter 已通过新进程加载/生成，M2-06 已完成独立模型加载/生成验收，见 [重载说明](adapter-reload.md)。

## 使用

```bash
# CPU 环境即可，不需要 training extra、GPU、模型缓存或联网。
uv sync --locked
uv run --locked python scripts/check_training_artifacts.py \
  --task-id 82fbb46e-bf0e-48da-9d03-789835257106 \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775
```

上述 ID 是本机 M2-04 的真实产物；其他机器先训练或复制完整产物目录，再指定实际 ID。训练机器同步时继续使用 `uv sync --locked --extra training`，避免移除训练依赖。新增基础依赖 safetensors 0.8.0 是此前已锁定的 Rust 文件解析器，无包版本升级；审计不导入 torch、numpy、Transformers、PEFT 或 Hub。

命令显式读取 .env，以 DATA_DIR/outputs/{task_id} 为受控根目录；--data-dir/--env-file 可覆盖，路径按仓库根解析。--revision 可选，提供时必须与实际清单一致；省略时仍核对清单、快照、Adapter 配置中的固定 revision。不会与联网仓库比较，也不自动修复或改写文件。成功 stdout 是无本机路径的 JSON 摘要，reload_verified=false；失败 stderr 为安全 TrainingFailure，非零退出。argparse 的参数错误同样非零。

Python 入口：

```python
from trainer.artifacts import verify_training_artifacts

verified = verify_training_artifacts(
    output_dir,
    outputs_root=outputs_root,
    expected_task_id=task_id,
    expected_revision=model_revision,
)
# verified.result 提供内部路径，verified.manifest 提供已校验的元数据。
```

输出路径参数属于可信 CLI/Worker；未来 Worker 仍须从数据库及受控目录生成路径。返回 VerifiedArtifacts 是内部对象，不新增 HTTP API/字段，不直接暴露内部路径。

## 校验内容

| 范围 | 检查 |
| --- | --- |
| 任务与清单 | UUID 目录名/可选预期 ID、固定版本/模型 revision、成功状态、无失败标记、严格 JSON 无重复键；类型检查沿用 TrainingManifest |
| 文件与路径 | 文件集合、字节大小、SHA-256；拒绝符号链接、硬链接、非普通/空文件、意外文件及不在配置输出根下的任务 |
| 配置快照 | training_config.json 与 manifest 的任务、模型、完整 TrainingConfig/RuntimeOptions 一致 |
| Adapter 配置 | 基础模型 ID/revision、CAUSAL_LM/普通 LORA、r/alpha/dropout/target_modules/bias 与训练参数一致 |
| Adapter 权重 | safetensors Rust 解析；仅 LoRA A/B 张量、成对、目标模块、二维/rank、F32/F16/BF16、有限值、参数总数与清单一致 |
| Tokenizer | BPE 词表/merges、added token 与 decoder、EOS/padding、特殊 token 文件及可选 legacy 词表/merges 相互一致，模板 SHA-256 与清单一致 |
| 指标 | 流式读取完整 JSONL；有限值、优化器步数/日志窗口、train/eval 顺序、epoch/时间顺序、运行时间范围、验证集存在性、最终步数与 Loss 汇总一致 |

校验当前 M2-04 的执行规范：每 logging_steps 记录并按需验证，末步补记；允许稀疏 step，不能要求每个优化器更新都有数据点。无验证集时无 eval；有验证集时验证各日志窗口和最终 eval。使用模型当前 Loss 的浮点值比较，不重算训练 Loss。

交付目录只接收当前单 Qwen/普通 LoRA 保存规范：adapter 内为 adapter_config.json、adapter_model.safetensors、可选 README.md；tokenizer 内为 tokenizer_config.json、tokenizer.json、chat_template.jinja，及标准 special_tokens_map.json/added_tokens.json/vocab.json/merges.txt。必需三个 tokenizer 主文件，其他文件存在时纳入哈希和一致性核对。拒绝混入完整基础权重、数据文件或额外路径；checkpoints/ 允许保留普通诊断目录，内容不进入交付清单。root 的 failure.json、临时清单或其他意外文件不构成成功交付。

审计不加载基础模型，不能证明 Adapter 所属层的真实输入/输出维度与基础权重匹配，也不实际渲染 Jinja 或运行 tokenizer。它证明本地文件结构与记录一致；M2-06 还须使用已校验的基础缓存、保存的 tokenizer 和 Adapter 实际加载/生成。哈希清单也不是可信签名，不能独自证明来源或训练效果；数据审核状态照实保留，不把 unknown/draft 升为 reviewed。

审计 JSON 清单/配置读取上限 512 KiB，tokenizer 主词表/merges 32 MiB，指标每行 16 KiB，Adapter 512 MiB；指标流式读取，权重通过 deserialize 在 CPU 内存验证，不创建 GPU 张量。这些是本地执行校验器的资源边界，不改变公开 TrainingConfig 或数据上传上限。

## 保存顺序与失败

train → run_storage.finish → inventory/validate_bundle 与独立审计共用校验 → 生成最终时间/统计 → 写唯一临时清单并 flush/fsync → 同文件系统原子创建 manifest.json → 返回 TrainResult。

正式成功文件使用排他硬链接提交，不覆盖已存在清单；移除临时名后仅保留一个链接。此策略针对当前 WSL/Linux 本地文件系统，文件系统不支持硬链接时明确失败，不降级为覆盖写。模型/数据/日志仍独占创建，拒绝恢复或覆盖已有任务。

配置/Adapter/tokenizer 写入失败、审计不一致、临时清单写入/fsync/提交失败均不能返回成功。保留本次部分产物和诊断，不删除源数据、缓存或其他任务；临时清单尽量清理。若提交后临时名清理失败，会回滚本次成功标记；若目录连回滚也不允许，保留两个链接，审计器拒绝这种多链接标记，不把它判为有效成功。已有外来标记保持原样。

独立检查失败使用 INVALID_ARTIFACT；保存流程失败使用 ARTIFACT_WRITE_FAILED。诊断只输出异常类别/安全文案，不输出样本、服务器路径或凭据。manifest 是本地训练/保存成功标记，M3 数据库 COMPLETED、M4 下载打包和 M5 在线推理仍分别待实现。

## 验证与交接

本次只读通过多份 M2-04 真实产物，并用一次真实 LoRA 更新验证新保存链路。CPU 故障检查包括损坏/缺文件、重算哈希后的语义矛盾、链接、意外文件、指标/Tokenizer 不一致、临时清单与提交失败、并发标记和失败隔离，见 [工作日志](worklogs/2026-10-23-m2-05.md)。这些检查使用合成小产物，不充当模型训练或真实 OOM 证据。

M2-06 复用 verify_training_artifacts 的 result/manifest，从 verify_model_cache 的相同 revision 本地快照加载基础模型；再加载保存的 tokenizer/Adapter，在新进程真实生成。不要只看到 artifacts_verified 就跳过加载验收，也不要把它当作模型效果提升结论。
