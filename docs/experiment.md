# 实验方案与记录

## 一、实验目标

1. 在 RTX 5070 12GB 上完成 Qwen2.5-0.5B-Instruct LoRA 微调。
2. 验证数据上传、异步调度、训练观测、Adapter 下载和测试推理的完整服务链路。
3. 展示任务串行调度、显存使用与失败反馈，体现云计算服务化能力。

M2-04 已执行格式样例的真实 LoRA 工程验收，记录见第九节；使用正式审核语料的 E01 仍待执行。M2-02 基础模型准备与前向验证已有实际记录，单独列于文末，不是微调或效果实验结果。

M2 的任务与验收见 [完整开发计划](m2-development-plan.md)。先完成真实模型上的工程冒烟和新进程重载，再使用审核后的语料进行正式效果实验；以下异步/Web 步骤分别在 M3–M5 验证。

## 二、环境记录（已核对项来自 M2-02，正式实验需再次记录）

| 项目 | 值 |
| --- | --- |
| Windows 版本 | 待填写 |
| WSL / Ubuntu / 内核版本 | 待填写 |
| GPU / 显存 | NVIDIA GeForce RTX 5070 / 12,227 MiB（NVML） |
| NVIDIA 驱动 | 617.42 |
| Python / PyTorch / CUDA runtime | 3.12.15 / 2.9.1+cu128 / 12.8 |
| Transformers / PEFT / TRL / Accelerate / Datasets | 4.57.6 / 0.18.1 / 0.25.1 / 1.15.0 / 4.8.5 |
| 代码 commit / 模型 revision | M2-02 起点 8f315c5，工作区含本次实现；模型 7ae557604adf67be50417f59c2c2f167def9a775；正式训练 commit 待记录 |
| 数据集来源、授权、SHA256 | 待填写 |

先执行 `uv sync --locked --extra training`，再执行 `nvidia-smi` 与 `uv run --locked --extra training python scripts/check_gpu.py`，保留版本和实际前向/反向运算结果。安装成功或 `cuda.is_available()` 为真均不足以替代 GPU 运算验证。记录本次实验使用的 `uv.lock` 与 Git commit，便于复现实验环境。

## 三、实验步骤

1. 按既有数据方案准备 100–300 条有来源记录且人工审核的领域样本，按问答族划分训练、验证与测试集，记录随机种子；目标规模按质量与工时调整。`docs/examples/train.jsonl` 可用于工程冒烟，不作为效果实验语料。
2. 在固定测试提示词上记录基础模型回答，保持推理解码参数一致。
3. 先用极少量训练步验证模型加载、LoRA 可训练参数、进度回调和产物导出；随后执行正式实验。
4. 导出 Adapter 后重新加载基础模型与 Adapter，使用相同测试提示词比较输出。
5. 从 Web 提交两个任务，验证排队和串行执行；记录任务 ID、状态时间线、日志与 Loss 图。
6. 注入非法数据、Broker 不可用和训练异常场景，验证错误反馈与产物隔离。

初始参数：r=8、alpha=16、dropout=0.05、q_proj/v_proj、epoch=1、batch=1、梯度累积=8、max_seq_length=512、learning_rate=2e-4、seed=42。精度策略在 GPU 检查后确定并记录。

## 四、记录表

| 实验 ID | 数据/模型 revision | 参数差异 | 显存峰值 | 训练耗时 | 最终 train/eval Loss | Adapter 大小 | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E01 | 待填写 | 初始参数 | 待填写 | 待填写 | 待填写 | 待填写 | 尚未执行 |

| 测试问题 | 基础模型回答 | LoRA 模型回答 | 评价依据 |
| --- | --- | --- | --- |
| 待填写 | 待填写 | 待填写 | 事实准确性、格式遵循、领域术语或人工评分 |

训练 Loss 降低并不等于模型能力提升。报告需说明样本规模、数据泄漏控制、评价方式与小数据过拟合限制，保留表现没有提升或退化的样例。

M2 工程验收另需记录：训练/重载进程独立、实际优化器更新步数、LoRA 权重更新证据、基础参数冻结、产物完整性及缓存/revision 匹配。加载阶段无 Loss，未提供验证集时 eval_loss 记为未执行，不能填 0。少量训练后文本不变不单独判为失败，训练保存成功也不能替代新进程重载证据。原始指标、日志与生成文本留在忽略的 data/、logs/ 下，文档只写真实摘要。

## 五、课程报告素材

- 架构图、模块接口、任务状态图。
- 数据上传、任务列表、真实 Loss 曲线、日志、Adapter 下载与推理页面截图。
- 两个任务的排队时间线、GPU 显存与耗时记录。
- 一项失败任务的错误原因及处理方式。
- 完整环境版本、Git commit、模型 revision、数据摘要和实验参数。


## 六、M1-06 数据与评测准备

数据来源、编写/审核与划分规则见 [数据方案](data/README.md)，首批 [12 道固定题](data/cloud-basics-eval-v1.json) 已冻结为 1.0.0。当前仅完成数据工程准备，正式语料仍需人工编写并交叉复核，没有训练结果。

`prepare_dataset.py` 生成 train/validation/test、provenance 和 manifest，记录原始数据、侧车、来源清单、评测协议的 SHA-256 与 seed。格式冒烟包位于忽略的 data/prepared/format-smoke-v1，build_id 为 5b01fc10b508722a，各集 1 条，状态 draft_unreviewed；不能用于声称效果提升。

正式实验上传 train 文件，验证集和测试集由 Trainer 后续独立接入，不能把三个文件合并上传后继续声称留出评测。固定 12 题不属于上述三个子集，禁止训练或调参使用。模型对照默认 do_sample=false、max_new_tokens=192；记录实际 chat template、模型 revision 与解码配置，基础模型/Adapter 保持一致。

每题准确性 0–2、清晰度 0–1、边界意识 0–1；两人盲评，保留分歧、无变化与退化案例。原始答案、双人评分与环境/参数保存到忽略的 data/experiments/<experiment_id>/，课程文档只整理真实汇总。本表当前仍待执行，不填写虚构 Loss 或评分。

## 七、M2-02 基础模型前向实测（非微调）

2026-10-22 使用官方预训练模型，通过 scripts/prepare_model.py 下载校验，再以独立进程禁止 Python IPv4/IPv6 connect/connect_ex，离线加载缓存执行 CUDA 前向。

| 项目 | 实测结果 |
| --- | --- |
| 模型/tokenizer revision | 7ae557604adf67be50417f59c2c2f167def9a775 |
| 必需文件数 / 总原始字节 | 9 / 999,602,607 |
| chat template SHA-256 | cd8e9439f0570856fd70470bf8889ebd8b5d1107207f67a5efb46e342330527f |
| 模型参数量 | 494,032,768 |
| GPU / Windows 驱动 | NVIDIA GeForce RTX 5070 / 617.42；NVML 总显存 12,227 MiB |
| PyTorch / CUDA runtime | 2.9.1+cu128 / 12.8 |
| Transformers / HF Hub | 4.57.6 / 0.36.2 |
| 权重与 logits 精度 | BF16 / torch.bfloat16 |
| 输入 token 数 / logits 形状 | 34 / [1, 34, 151936] |
| 数值检查 | logits 位于 CUDA，全部有限 |
| PyTorch 分配显存峰值 | 1,042,360,320 字节，约 994 MiB；不是整卡或 reserved 占用 |
| 加载与最小前向耗时 | 2.072735 秒；不含依赖导入/缓存哈希，不是生成延迟 |

模型与缓存清单位于忽略的 data/models/huggingface/，来源与哈希可重新验证。此记录没有 Loss、反向传播、优化器更新、Adapter 或回答评分。后续微调仍按 E01 与冻结题协议记录，不能用本次前向结果代替训练效果。验证起点为 8f315c5，执行时工作区包含本次 M2-02 实现；最终代码以 [工作日志](worklogs/2026-10-22-m2-02.md) 与 Git 提交为准。

## 八、M2-03 数据与标签验证（非训练）

2026-10-22 在固定 revision/模板下，离线执行 [数据处理检查](training-data.md)。公开格式样例共 3 条、625 字节，原始 SHA-256 为 0ab7de0f8f7adb17d5bd47ff4b1a6a2df4237e5853c9720acf38d468adb1c5ab。长度 512 时 token 数为 56/73/73，回答内容监督数为 22/29/34，加模板 EOS 后为 23/30/35；首条监督解码恰为原回答 + EOS，系统/用户/角色头和最后换行均为 -100。

长度 64 时后两条被右截断，剩余回答内容为 22/27 个 token，EOS 不再参与监督，没有人为追加。独立进程禁止 Python 网络 connect，参考 apply_chat_template 直接编码与处理结果逐项一致；真实 torch.int64 CPU 批次形状为 [3, 64]，padding 标签全为 -100，原有效 EOS 标签在 pad_id=EOS 的验证中仍保留。长 prompt 和仅特殊 token 的回答均报 NO_SUPERVISED_TOKENS。

已有格式包 build_id=5b01fc10b508722a 的 train/validation 各一条，实际字节哈希/数量与 manifest/provenance 匹配，审核状态保持 draft_unreviewed；不读取 test 正文。无清单的原始样例为 unknown，不据此声称正式语料已审核。本次没有加载模型参数、使用 GPU、Loss、优化器更新或效果评分；E01 仍待执行。详细命令与交接见 [M2-03 日志](worklogs/2026-10-22-m2-03.md)。

## 九、M2-04 真实 LoRA 工程验收

日期 2026-10-23，基线代码 5d1dad6，执行时包含本次工作区实现，dirty=true；模型/tokenizer revision 仍为 7ae557604adf67be50417f59c2c2f167def9a775，环境版本与 M2-02 相同。使用现有公开格式样例及 draft_unreviewed 格式包，不使用 test/冻结题，不属于正式 E01。

| 任务 ID | 设置 | 实际结果 |
| --- | --- | --- |
| e54e247f-e321-4a94-a663-cfa680cc5ddf | 三条公开格式样例，默认配置、BF16，max_steps=2 | train Loss 3.6218、3.5100；2 步，9.574 秒，峰值 1,237,656,576 字节；无验证集，无 eval Loss |
| 82fbb46e-bf0e-48da-9d03-789835257106 | 最终默认配置两步，同源回调核验、禁止网络 | train Loss 3.6218、3.5100；8.149 秒，峰值 1,237,656,576 字节；末步当前 LR=0 |
| 5c7d2287-3e03-4c41-9b17-1838a0e19c58 | 格式包 train/validation 各一条，完整一个 epoch，logging_steps=10 | 实际 1 步，末步 train Loss 2.7789、eval Loss 3.9186337；6.619 秒，峰值 1,172,896,256 字节 |
| 4b455de5-5849-46b7-93ec-e3f5852830e8 | 同一格式包，max_steps=3、logging_steps=2，禁止网络连接 | train/eval@2、train/eval@3；train Loss 2.6584、2.4363，eval Loss 3.8981497、3.8893361；6.897 秒，峰值 1,185,742,336 字节 |

总参数 494,573,440（基础 494,032,768 + LoRA 540,672），可训练参数 540,672。首轮及后续成功运行中 96/96 个 LoRA 张量更新；全部冻结基础参数的字节哈希前后一致，且未出现基础参数梯度。首轮哈希为 e0d7e651e5b6b9da6b4c53f5013797d72ffcf4d8ecf42361df6aee925969e079。保存 Adapter 的 safetensors 张量与训练后内存值逐项相等，权重约 2.18 MB；不是完整基础模型导出。

时间包含本次函数的缓存核验、准备、加载、训练及基础保存，不是纯训练吞吐；显存为 torch 分配峰值，非整卡占用。稀疏日志中的 train Loss 是各日志窗口值，不能与 eval Loss 或单样本 Loss 直接比较。首轮采集后进一步按既有 v1 契约明确 learning_rate 为事件时当前优化器值；最终三步运行末步为 0，框架更新使用值保留在任务日志。

同进程两次真实回调故障均在 flush 后收到同源事件，返回 PROGRESS_CALLBACK_FAILED，无成功 manifest 或 Adapter；连续残留分配均为 18,087,936 字节，诊断证明来自 cuBLAS 工作区，清除工作区后归零。正式实现释放模型/优化器引用及异常栈局部变量，不调用该私有诊断清理接口。详见 [工作日志](worklogs/2026-10-23-m2-04.md)。

输出位于忽略的 data/outputs/{task_id}/，日志位于 logs/tasks/，不提交权重或原始运行文件。本次未执行新进程 Adapter 重载、generate、真实 OOM 或效果评分；训练 Loss 下降不能证明正式效果提升。后续 M2-05 已完成，M2-06 和审核语料 E01 仍需完成。

## 十、M2-05 保存与审计联调

日期 2026-10-23，基线代码 12df1b2，工作区包含本次 M2-05 实现，dirty=true。未改变模型、训练配置或训练算法；只用公开三条格式样例完成 1 个优化器更新，验证真实保存链路通过新的共享审计器才提交成功标记。

任务 ID：992aa53a-a246-45de-a8f1-4d4164d9b42e。Loss=3.6218，无验证集/无 eval；耗时 9.669 秒，分配峰值 1,233,330,688 字节。12 个交付文件、96 个 LoRA 张量，trainable=540,672，total=494,573,440。实际环境版本与 M2-04 相同，uv.lock SHA-256 为 21cd327f778de106f03d9679aa14515c281e7ebae36c64cb16d98bda29931297。

独立 CPU 命令随后通过。M2-04 四份真实成功产物也可被本次校验器审计；无训练库/基础缓存/网络依赖，不读取训练正文。此次额外运行仅验收保存集成，不是训练新领域模型或正式效果实验。未执行 M2-06 Adapter 加载/生成，详情见 [M2-05 日志](worklogs/2026-10-23-m2-05.md)。
