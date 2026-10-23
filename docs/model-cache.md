# M2-02 基础模型准备与离线检查

日期：2026-10-22。状态：固定模型缓存、完整性检查与真实模型 GPU 前向已完成；未执行 LoRA、反向传播、Adapter 导出或在线推理。模型白名单 API 的含义保持不变，不表示缓存或 GPU 就绪。

## 一、命令入口

在仓库根目录操作。训练机器保留 training extra：

```bash
uv sync --locked --extra training

# 显式联网：将 main 解析为不可变 revision，下载并检查所需文件
uv run --locked --extra training python scripts/prepare_model.py prepare

# 使用本次验收的固定 revision，避免以后 main 变化
uv run --locked --extra training python scripts/prepare_model.py prepare \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775

# 只读、离线、无需训练依赖：检查全部缓存文件，不做在线回退
uv run --locked python scripts/prepare_model.py check \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775

# 离线加载真实权重与 tokenizer，并在 cuda:0 执行最小前向
uv run --locked --extra training python scripts/prepare_model.py check \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775 --gpu
```

prepare 默认 revision=main，也可传完整 40 位小写 SHA；check 必须明确传完整 SHA，不能使用 main/tag/短 SHA。GPU 检查默认 BF16，可显式 `--precision fp32`，不自动降配或 CPU offload；只加载 safetensors，trust_remote_code=false。GPU 检查应安排在没有其他训练/推理的时段，M3 统一资源互斥尚未实现。

成功 stdout 是 JSON，CPU 检查 status=cache_verified，GPU 检查 status=gpu_forward_verified；失败输出安全的 TrainingFailure 到 stderr 并返回非零。缺失/损坏文件错误包含固定白名单内的文件名，不包含本机绝对路径、访问令牌或带签名 URL。

## 二、路径配置

prepare/check 均接受 `--env-file`、`--data-dir`、`--hf-home`、`--cache-dir`。优先级为显式 CLI 参数 → 进程环境变量 → 指定 .env（默认仓库根 .env）→ 默认值。显式指定不存在的 env-file 会失败，默认 .env 不存在则使用环境/默认值。不对 .env 做变量插值，不自动加载其中的其他网络/代理/凭据配置。

| 项目 | 默认与含义 |
| --- | --- |
| DATA_DIR | 仓库根 data；相对路径始终按仓库根解析 |
| HF_HOME | 未显式配置时为 DATA_DIR/models/huggingface；HF 的缓存根 |
| HF_HUB_CACHE / cache_dir | 未显式配置时为 HF_HOME/hub；实际 Hub 缓存目录，传给 TrainRequest.cache_dir |
| HF_XET_CACHE | CLI 在未设置时指向 HF_HOME/xet；保持下载临时缓存位于项目配置中 |

HF_HOME 与 HF_HUB_CACHE 各自可显式覆盖；修改 DATA_DIR 不会覆盖一个已经显式指定的 HF_HOME。CLI 在加载 HF 库之前设置解析后的缓存变量，不依赖后端 Settings，也不依赖 shell 当前目录。CLI 的 check 同时开启 HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE，禁用遥测；普通 CPU check 不导入 HF、Transformers 或 torch。

默认布局：

```text
data/models/huggingface/
├── hub/
│   ├── models--Qwen--Qwen2.5-0.5B-Instruct/
│   │   ├── blobs/                       # HF 管理的共享内容
│   │   ├── snapshots/{revision}/        # 固定 revision 的文件/内部链接
│   │   └── refs/                       # HF 自身可能维护，不用它决定离线 revision
│   └── .llmcloud/models--Qwen--Qwen2.5-0.5B-Instruct/{revision}.json
└── xet/                                # 下载器按需产生
```

缓存工具本身使用标准 Hub 布局，不复制基础权重到 outputs。配置根目录可以按机器调整，不能把某位成员的绝对路径写成跨机器固定值。路径解析允许 HF 正常的内部 blob 链接，拒绝越出缓存根或循环的链接；不提供面向不可信 HTTP 客户端的路径访问能力。

## 三、准备、检查与失败语义

prepare 使用官方仓库元数据，将 main 解析一次，随后下载始终使用解析后的同一 SHA。只下载固定 9 个文件：config.json、generation_config.json、model.safetensors、tokenizer.json、tokenizer_config.json、vocab.json、merges.txt、LICENSE、README.md。不 clone 仓库、不下载 pickle 权重或任意自定义代码。

根据官方 files_metadata 检查大小和摘要：LFS 文件使用 SHA-256，小型 Git 文件使用带 `blob {size}\0` 头的 Git SHA-1；同时为所有本地文件计算 SHA-256。检查 Qwen2 配置和非空 chat template 后，原子写出缓存清单。清单只包含 cache_format_version=1.0.0、固定模型 ID、模型/tokenizer revision、模板哈希和文件清单，无机器绝对路径。

普通 check 必须同时具备有效清单和全部文件。它逐一重算摘要、核对大小、revision 和模板；只存在 snapshots 目录不算完成，发现同大小损坏也会失败。不联网、不写目录、不用其他 revision 补齐；支持在只安装服务/CPU 依赖的机器上运行。

下载中断、官方元数据不符、路径异常或清单写入失败均返回明确错误；失败不会提交本次成功清单。原有清单也必须重新通过文件校验，不能仅凭清单存在判断可用。工具不自动删除缓存或强制覆盖损坏 blob；命中已有损坏内容时重复 prepare 可能仍失败，应按文件名与 revision 定位后在维护时修复，不自动重试或偷偷换版本。

该清单用于受控本机缓存的一致性检查，不是对恶意修改清单与权重的签名证明。后续 GPU 加载仍是单独验收。缓存清单不等于训练 manifest，不包含训练完成状态。

## 四、后续模块调用

`trainer.model_cache` 提供 CPU 可导入的 ModelPaths、CachedModel 及三个入口：

```python
from trainer.model_cache import resolve_model_paths, verify_model_cache

paths = resolve_model_paths()
cached = verify_model_cache(
    paths.cache_dir,
    "7ae557604adf67be50417f59c2c2f167def9a775",
)
# cached.snapshot_dir：已校验的本地快照，供 from_pretrained 使用
# cached.manifest.model_revision / tokenizer_revision / chat_template_sha256
# paths.cache_dir：供 TrainRequest.cache_dir 使用，不是 HF_HOME
```

resolve_model_paths 只读取配置/解析路径；verify_model_cache 不导入训练包或访问网络；prepare_model_cache 是显式联网的独立准备动作。库函数不自动改变进程环境，环境设置由 CLI 在依赖导入前完成。M2-03/04 从已校验快照按 local_files_only=true 加载，模型与 tokenizer 使用同一清单，不在 API 请求中下载模型。

M2-03 已提供 load_training_tokenizer / prepare_training_data / InstructionCollator，见 [数据处理说明](training-data.md)。M2-04 的 [Trainer](training.md) 已复用这些入口和既有标签，不重新模板化、重复特殊 token 或覆盖监督掩码。

`trainer.model_probe.probe_model_gpu(cache_dir, revision, precision="bf16")` 是独立验收工具：完整检查缓存，加载真实模型到单个 cuda:0，应用固定模板、执行 inference_mode 前向、检查 CUDA logits 有限性，记录参数量、版本、耗时与显存；finally 清理模型引用与分配缓存。它不训练、不生成回答、不操作任务数据库，也不是 M5 推理服务。

GPU 报告的 elapsed_seconds 从依赖导入/缓存校验之后开始，覆盖模型/tokenizer 加载、搬到 GPU 与前向检查；不是完整命令耗时或生成延迟。peak_memory_allocated_bytes 为该进程 PyTorch 分配峰值，不包括桌面占用或整卡显存。

## 五、本机证据与复现边界

实际缓存与 GPU 结果见 [M2-02 工作日志](worklogs/2026-10-22-m2-02.md) 和 [实验记录](experiment.md)。本轮模型参数为 494,032,768，BF16 logits 为 `[1, 34, 151936]` 且有限；Python 网络连接被明确阻断的独立进程验收通过。该任务仅验证前向；M2-04 已验证真实 LoRA/基础保存，M2-05 已完成 [独立产物审计](training-artifacts.md)，M2-06 已完成 Adapter 新进程重载，正式效果评分仍待完成。

CPU 单元测试使用显式合成小文件与 Hub 替身，覆盖缺失、损坏、路径/配置、错误与原子清单，不能作为真实模型/GPU 证据；默认 CI 不下载权重或要求 GPU。真实权重、缓存清单与下载临时文件在忽略的 data/ 下，不进入 Git。

实现依据：[固定模型仓库](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct/tree/7ae557604adf67be50417f59c2c2f167def9a775)、[huggingface_hub 0.36.2 下载实现](https://github.com/huggingface/huggingface_hub/blob/v0.36.2/src/huggingface_hub/_snapshot_download.py)、[Transformers 4.57 模型加载说明](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/model)。具体 API 已核对本机锁定版本源代码，不按最新版文档假定离线完整性行为。
