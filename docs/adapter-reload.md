# M2-06 新进程 Adapter 重载

2026-10-23：单 GPU 本地工程闭环已验收。正式审核语料/效果实验继续独立推进；任务 HTTP/Celery、网页下载和在线推理仍属 M3–M5。

训练命令退出后，在新终端或新 Python 进程执行：

```bash
uv run --locked --extra training python scripts/reload_adapter.py \
  --task-id 992aa53a-a246-45de-a8f1-4d4164d9b42e \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775 \
  --prompt '请用一句话说明微调服务中记录训练日志的用途。' \
  --max-new-tokens 64
```

该 task_id 是本机已有结果；其他机器使用自己的真实任务 ID 和完整产物、固定 revision 缓存。入口读取 .env，支持 --data-dir/--cache-dir/--env-file，遵循已有配置优先级；--revision 可选但提供时严格核对。--input 为可选上下文，用户消息沿用 instruction + 两个换行 + input 的训练约定。提示词总长最多 8192 字符，套模板后最多 2048 token，不自动截断；生成上限 1–256，默认 128，使用确定性 greedy decoding。不要用冻结题反复调参。

训练和重载不得同时抢占同一 GPU。要求单进程、一个可见 CUDA GPU，精度沿用清单的 BF16/FP32；缺 CUDA、不支持精度或 OOM 时失败，不隐式降配。这里没有实现跨进程资源锁；服务化互斥属于后续阶段。

调用顺序：M2-05 审计产物/期望 ID/revision/根目录 → M2-02 核验同 revision 缓存 → 从保存目录实际加载 tokenizer 并与固定缓存词表、EOS/PAD、模板比较 → 加载基础模型 → PEFT 加载本地 Adapter → 核对全部 Adapter 张量值与 safetensors、激活状态和参数冻结 → CUDA generate。

全部本地加载，trust_remote_code=false，不联网回退。Adapter 采用 PEFT 默认浮点上转，以保留训练时保存的 FP32 LoRA 数值；基础模型精度不改变。逐步检查生成 logits 有限，不将“JSON 文件存在”当成加载成功。

Python 入口为 trainer.reload.reload_and_generate；模块 CPU 可导入，实际模型库在执行时加载。此函数不自动派生子进程，调用方负责与训练进程分离；M2-06 的真实验收通过父进程先等待训练退出再启动不同 PID 的重载进程证明。它不依赖 HTTP、Celery、数据库或后端 Settings，不修改训练成功 manifest/metrics，也不会写入数据库状态。

成功 stdout 为独立重载结果 JSON，包括 PID、产物哈希、模型 revision、实际张量核对、token 数、greedy 参数、响应和资源统计；失败 stderr 为安全 TrainingFailure，退出非零。提示词正文默认只通过显式命令参数传入，结果记录其哈希；回答会输出到 stdout，需保存时放忽略的 data/experiments/，不要提交原始回答。

M2-05 的 artifacts_verified/reload_verified=false 仍只表示文件审计；只有本入口实际加载并生成后返回 status=reload_verified。重载结果为独立验收记录，不覆盖训练清单，也不表示正式效果提升。某个已验收 Adapter 不代表所有将来任务都已重载通过。

真实结果、两进程 PID、已测失败路径与限制见 [工作日志](worklogs/2026-10-23-m2-06.md) 和 [实验记录](experiment.md)。正式语料仍为待人工审核状态，本次不执行冻结题评分，也不要求少量训练后的回答必须改变。
