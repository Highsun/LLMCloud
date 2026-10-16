# 实验方案与记录

## 一、实验目标

1. 在 RTX 5070 12GB 上完成 Qwen2.5-0.5B-Instruct LoRA 微调。
2. 验证数据上传、异步调度、训练观测、Adapter 下载和测试推理的完整服务链路。
3. 展示任务串行调度、显存使用与失败反馈，体现云计算服务化能力。

当前尚未执行训练，下列内容为计划和待填写记录，不是实验结果。

## 二、环境记录

| 项目 | 值 |
| --- | --- |
| Windows 版本 | 待填写 |
| WSL / Ubuntu / 内核版本 | 待填写 |
| GPU / 显存 | 用户提供：RTX 5070 Desktop / 12GB；待实测确认 |
| NVIDIA 驱动 | 待填写 |
| Python / PyTorch / CUDA runtime | 待填写 |
| Transformers / PEFT / TRL / Accelerate / Datasets | 待填写 |
| 代码 commit / 模型 revision | 待填写 |
| 数据集来源、授权、SHA256 | 待填写 |

先执行 `uv sync --locked --extra training`，再执行 `nvidia-smi` 与 `uv run --locked --extra training python scripts/check_gpu.py`，保留版本和实际前向/反向运算结果。安装成功或 `cuda.is_available()` 为真均不足以替代 GPU 运算验证。记录本次实验使用的 `uv.lock` 与 Git commit，便于复现实验环境。

## 三、实验步骤

1. 准备 100～500 条有明确领域任务的合法指令样本，单独划分训练、验证与测试集，记录随机种子。`docs/examples/train.jsonl` 仅验证格式。
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

## 五、课程报告素材

- 架构图、模块接口、任务状态图。
- 数据上传、任务列表、真实 Loss 曲线、日志、Adapter 下载与推理页面截图。
- 两个任务的排队时间线、GPU 显存与耗时记录。
- 一项失败任务的错误原因及处理方式。
- 完整环境版本、Git commit、模型 revision、数据摘要和实验参数。
