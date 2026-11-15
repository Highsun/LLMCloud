# E01工具、环境与盲评材料准备结果（B）

后续接续：用户已转达队友确认并授权正式准备与E01，实际96/16/8划分已生成，build_id为8cf9ede8899f618a。本文保留准备阶段事实；正式清单和实际执行结果见[E01运行记录](e01-results-2026-11-15-b.md)。

日期：2026-11-15。用户要求完成当前不依赖队友正式准备确认的工作。**队友工具补丁已在隔离分支应用，44项CPU回归通过，依赖/离线缓存预检通过，实验及空白盲评模板已生成。正式reviewed更新、数据准备、训练和模型回答生成仍未执行。**

## 工具补丁与回归

运行worktree位于E盘承载的WSL路径`/home/l7/LLMCloud-e01-20261115`，分支`test/e01-tools-3060-20261115`。基线完整提交为`390a7d91906e703c5fee785650d89e1a5a80a1d5`，包含0041b8b；先从干净基线应用收到的原补丁。

仅四个生产文件有修改：scripts/prepare_dataset.py、scripts/reload_adapter.py、trainer/dataset_manifest.py、trainer/reload.py。四个文件的Git blob均匹配补丁目标index；反向检查通过，没有另写生产实现。补丁SHA256仍为16c42f20ac5b4b725b352c06947efca17ca1cd0b5c1ddc82cc2be7b1916b2437。

原`/home/l7/LLMCloud`仍在d00349f、原分支且工作区干净；D盘主checkout生产代码未变。新worktree中补丁尚未提交，本轮未提交/推送Git；正式运行前需记录实际提交与补丁状态。

| 专项 | 实际项数 | 结果 |
| --- | ---: | --- |
| 原数据准备 | 10 | 通过 |
| 原预处理/清单/来源与哈希 | 19 | 通过 |
| 原独立重载/错误/CPU导入边界 | 8 | 通过 |
| B新增补丁行为检查 | 7 | 通过 |
| 合计 | 44 | 全通过 |

新增检查入口为本目录`e01-tools-regression.py`。覆盖自定义来源与v2协议CLI实际生效、check-only不写输出、未审核仍拒绝正式模式、未知版本拒绝、v1兼容、v2清单实际消费/篡改拒绝，以及compare的显式开启/默认关闭与JSON转发。全部使用临时合成数据和明确CPU替身；不是正式语料准备、GPU生成或模型效果验证。没有删除、跳过或改写队友已有测试。

## 环境与资源

- Python 3.12.16、uv 0.13.7；WSL Ubuntu，内核6.18.33.2。现有依赖一致性检查通过。
- PyTorch 2.9.1+cu128、transformers 4.57.6、datasets 4.8.5、peft 0.18.1、trl 0.25.1、accelerate 1.15.0。复用原`.venv`，没有安装或更新依赖。
- 以显式`UV_PROJECT_ENVIRONMENT=/home/l7/LLMCloud/.venv`验证`uv run --offline --locked --extra training --no-sync`可使用现有解释器。新worktree没有复制模型或依赖缓存。
- 固定Qwen2.5-0.5B-Instruct与模型/tokenizer revision`7ae557604adf67be50417f59c2c2f167def9a775`，离线核验9文件、999602607字节及chat template哈希通过。缓存使用`/home/l7/LLMCloud/data/models/huggingface/hub`，不回退到新worktree下的空缓存。
- RTX3060 Laptop 6GB、驱动616.92、CUDA runtime12.8，BF16能力检查通过；本次PyTorch未分配模型张量，未进行前向/反向或生成。
- 当时未看到CUDA计算进程，NVIDIA快照约1145MiB已用/17%利用率，含桌面等占用；不据此保证正式训练时GPU空闲。正式执行前重新检查，并持有原`/home/l7/LLMCloud/logs/worker.lock`。本次原锁可取得并释放，inode未替换。
- E盘物理空闲约228GiB；WSL虚拟文件系统另有较大空闲，容量判断同时检查底层E盘，不能只看虚拟容量。

## 实验与盲评模板

完整材料在E盘WSL：

```text
/home/l7/LLMCloud/data/experiments/e01-20261115/
  planning/
    README.md
    experiment-plan.json
    training-config-proposed.json
    result-record-template.json
    paired-responses-template.md
    scores-member-a.md
    scores-member-b.md
    scoring-rubric-v2.json
    SHA256SUMS
  private/
    blind-assignment-key.json
```

计划沿用实际默认配置：r8/alpha16/dropout0.05、q_proj/v_proj、lr0.0002、1epoch、batch1、梯度累积8、seq512、logging1、seed42，BF16，max_steps未设置。实际task_id与build_id均为空，训练结果表没有填写虚构值。

12道固定题各有匿名A/B回答空模板，两位评分者各24行空评分表。评分依据v2：准确性0–2、清晰度0–1、边界0–1，每份回答0–4、每模型总分最高48。尚无任何答案和成绩。

A/B身份在生成前逐题随机安排，私下存于0600权限文件，父目录0700；未把身份对应关系打印到日志、复制到D盘或透露给评分者。双方各自完成并锁定评分后再揭晓；不能用固定题调参。

规划中的`runtime-data/prepared/e01-reviewed`尚不存在，没有生成正式train/validation/test或manifest。96/16/8仍为上一步只读预估，正式数量以队友确认后的实际清单为准。留出test只在参数锁定后评估一次，指标口径需提前与A确认，当前未实现/运行留出评估。

## 接下来给队友的消息

以下仅供用户发送，本侧未代发：

> 我这边已在3060 WSL的独立分支应用工具补丁，基线390a7d9，补丁仍为未提交改动；44项CPU专项回归全部通过，现有依赖和固定revision离线缓存预检也通过。正式语料的reviewed标记未改，尚未生成正式划分或开始训练。请确认可以按收到的120条/26族、v2协议执行正式数据准备；seed42只读预估为训练96条/22族、验证16条/2族、测试8条/2族。留出测试准备在参数锁定后一次评估Loss/困惑度，如需其他口径请明确。确认后我先回传正式清单、build_id、各集数量与SHA256，再按步骤接续E01。

## 证据与限制

D盘小型证据位于`data/acceptance/b-review/laptop-3060/e01-tools-20261115`，含setup、44项回归摘要/小日志、环境预检、模板摘要、final-review及SHA256SUMS。原始回归日志在E盘`data/local-validation/e01-tools-20261115`；收到的附件、解压四文件及原摘要均未变化。

当前阶段结论为`current_authorized_e01_preparation_complete_waiting_for_a`。补丁应用后CPU行为已验收，但不声称已重新进行真实模型base/adapter生成或1epoch训练；不把工具准备完成写成正式E01完成。后续收到队友确认再更新实际审核工作副本并执行正式准备。
