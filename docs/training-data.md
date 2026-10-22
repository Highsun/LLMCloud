# M2-03 训练数据转换与监督标签

日期：2026-10-22。状态：JSONL 转换、回答标签、右截断、批次 padding、准备清单核对与离线诊断已实现。已用固定 Qwen tokenizer 验证；未加载模型参数、使用 GPU 或执行 LoRA 训练。

实现位于 [preprocessing.py](../trainer/preprocessing.py)、[dataset_manifest.py](../trainer/dataset_manifest.py)，沿用 [内部训练契约](contracts/training.md) 和 [模型缓存](model-cache.md)。API、原始数据、TrainingConfig 与生成 Schema 均不改变。

## 一、只读检查入口

训练机器先保留 `uv sync --locked --extra training`，已有完整缓存即可离线运行：

```bash
uv run --locked --extra training python scripts/check_training_data.py \
  --dataset docs/examples/train.jsonl \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775

# 显式检查某一条有效记录的文本、tokens、labels；仅对有权查看的数据使用
uv run --locked --extra training python scripts/check_training_data.py \
  --dataset docs/examples/train.jsonl \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775 --show-sample 1

# 已有 M1-06 格式草稿包：校验 train/validation 与 manifest/provenance 的对应
uv run --locked --extra training python scripts/check_training_data.py \
  --dataset data/prepared/format-smoke-v1/train.jsonl \
  --validation-dataset data/prepared/format-smoke-v1/validation.jsonl \
  --dataset-manifest data/prepared/format-smoke-v1/manifest.json \
  --revision 7ae557604adf67be50417f59c2c2f167def9a775
```

草稿包不存在时按 [数据方案](data/README.md) 的命令生成，不能把这个路径当作正式实验语料。支持 `--max-seq-length`（64–2048，默认 512）、`--env-file` 与 `--cache-dir`；所有相对文件路径按仓库根解析。check-only 工具不创建目录、不保存 token 文件、不更改数据或数据库。

默认只输出哈希、审核状态、数量、前三条的 token 统计及一个小批次形状，不输出训练正文或绝对路径。仅显式 `--show-sample N` 输出该条有效记录的 tokens、input_ids、attention_mask、labels、解码文本与被监督文本；N 从 1 开始，不是物理行号。错误沿用安全的 TrainingFailure，非零退出，不嵌入原始样本。

CLI 设置 HF/Transformers 离线与 tokenizer-only 环境，不导入 torch 或加载模型；缓存完整性检查仍会读取权重字节计算哈希。库的批次输出可按需延迟导入 torch，见后文。普通 CPU CI 使用合成 tokenizer；真实 tokenizer 诊断需 training extra 中的 Transformers 等依赖，但不需要 GPU。

## 二、对话与标签规则

共享 DatasetScanner/InstructionRecord 负责 UTF-8、字段、空白、大小和重复键等 JSONL 规则；训练侧不另写宽松解析。原始字节 SHA-256、大小和有效行数从同一读取过程获得。任意后续行失败都使整次准备失败，不返回半完成数据。

每条记录固定转换为 user/assistant 两个消息：input 非空时 user 为 `instruction + "\n\n" + input`，否则为 instruction；assistant 为 output。保留原字符串和模板默认 system，不插入自定义 system，不拼接多条记录。使用相同的固定模型/tokenizer revision 与原始 chat template。

当前 Qwen 模板没有 `{% generation %}` 区块。实现不修改模板，也不依赖未经验证的 assistant mask：

1. 模板渲染完整 user/assistant，对训练序列设置 add_generation_prompt=false；另渲染 user 的回答前缀和空 assistant，用于确定内容与 EOS 后缀的字符位置。
2. 核对完整文本严格等于“前缀 + 原始 output + 后缀”；不兼容模板立即失败。后缀必须是 tokenizer EOS 加可选空白。
3. 使用 fast tokenizer 对完整文本一次编码，add_special_tokens=false，取得 token 字符偏移，不二次添加特殊 token。
4. 只监督完全位于 output 字符区间内的普通 token，以及模板在 output 之后添加的一个 EOS。system、user、角色头、内容中出现的特殊 token、EOS 后换行均标为 -100。
5. 跨越回答字符边界的 token 保守屏蔽，避免把角色头或提示词混入监督；不使用“分别 tokenize 后直接拼接长度”的假设。Unicode 字符可对应多个 token/相同偏移，不按字符数猜 token 数。

标签与 input_ids 对齐，不在预处理或 collator 中手动左移/右移；后续 causal LM 负责 loss 的因果位移。M2-04 必须保留已有 labels，不能让通用语言建模 collator 重新生成全序列标签。

## 三、截断与 padding

长度限制作用于模板化后的完整 token 序列，右截断到 max_seq_length，不追加人工 EOS。如果回答被部分保留，可使用剩余有效内容；若模板 EOS 被截掉，eos_supervised=false，不伪造结束标记。保留的有效回答内容 token 必须大于零；只剩 prompt 或 EOS/特殊 token 的样本报 NO_SUPERVISED_TOKENS，不静默跳过。

InstructionCollator 在当前批次最长长度右侧 padding：input_ids 填 pad_token_id，attention_mask 填 0，labels 填 -100。原始位置的 attention_mask 为 1，已有标签逐项保留。即使 pad_token_id 与 eos_token_id 相同，也不能按 token 值屏蔽原本有效的 EOS。

输出只包含 input_ids、attention_mask、labels；默认返回 torch.long CPU 张量，不在 collator 中移动到 GPU。return_tensors=None 返回列表，可用于无 PyTorch 的测试。M2 不启用 packing 或自动断点恢复。

## 四、清单、审核与划分

没有 dataset_manifest_path 时，DatasetSummary 只包含实际原始哈希/大小/行数，review_status=unknown、build_id=null。不能因为 JSONL 格式合法或文件名含 train 就认定已审核。

传入清单时支持现有 prepare_dataset 的 v1 输出，核对：

- tool/protocol 版本、三个 split 的固定文件名/元数据、build_id 与 recipe；问答族不跨 split。
- 同目录 provenance.json 的大小、SHA-256、完整唯一原始行号、record_id、各 split 数量及问答族；审核布尔值必须与清单 reviewed/draft_unreviewed 一致，拒绝越界链接或重复 JSON 键。
- 实际传入 train 和可选 validation 的字节哈希、大小、行数必须匹配对应 split，不能把 validation/test 冒充 train；上传后的同字节文件可在其他可信路径消费。

不读取或 tokenize test 正文，也不核验未消费 test 文件的实际哈希；只检查其声明的族及 provenance 对应。这里不是完整包归档验证器，也不能证明人工审核或识别语义泄漏。正式数据仍须由团队使用原准备工具和来源审核流程，冻结题及其问答族不得训练/调参。模型选择只用 validation，test 和冻结题留到参数确定后的评测。

同一文件、符号/硬链接别名、完全相同字节的训练/验证副本会被拒绝；无清单时不声称完成跨集近重复或问答族识别。正常草稿包保持 draft_unreviewed，不自动升级为 reviewed。

## 五、M2-04 调用方式

```python
from trainer.preprocessing import (
    load_training_tokenizer, prepare_training_data, InstructionCollator,
)

tokenizer = load_training_tokenizer(request.cache_dir, request.model_revision)
prepared = prepare_training_data(
    request.dataset_path, tokenizer,
    max_seq_length=request.config.max_seq_length,
    validation_dataset_path=request.validation_dataset_path,
    dataset_manifest_path=request.dataset_manifest_path,
)
train_features = [sample.as_feature() for sample in prepared.train.samples]
collator = InstructionCollator(tokenizer.pad_token_id)
# 后续 Trainer 使用 train_features / 对应 HF Dataset 与 collator；不重复格式化或覆盖 labels。
# prepared.train.summary / prepared.validation.summary 供训练 manifest 使用。
```

TokenizedSample.summary 提供 original_tokens、tokens、truncated、supervised_content_tokens、supervised_tokens、eos_supervised，仅用于诊断，不混入模型输入。当前准备器保留截断后的样本于内存，适合课程小数据；不承诺任意大规模数据的流式训练。

## 六、真实 tokenizer 验证

固定 revision 为 7ae557604adf67be50417f59c2c2f167def9a775，模板哈希与 M2-02 一致。三条公开格式样例在长度 512 时：

| 有效记录 | 总 token | 回答内容 token | 包含 EOS 的监督 token | 截断 |
| --- | --- | --- | --- | --- |
| 1 | 56 | 22 | 23 | 否 |
| 2 | 73 | 29 | 30 | 否 |
| 3 | 73 | 34 | 35 | 否 |

第一条前 32 个 token 与最后换行都被屏蔽，显式解码监督部分恰为原回答 + EOS。长度改为 64 时后两条保留 22/27 个内容 token，EOS 均被截掉；真实 torch.int64 CPU 批次为 [3, 64]，使用 EOS 作为 padding ID 时原有效标签仍保留。长 prompt 和仅特殊 token 的回答都按预期拒绝。

真实验证中的 input_ids 与直接 apply_chat_template(tokenize=true) 的对应截断序列逐项一致，未重复添加特殊 token；额外禁止 Python 网络 connect 的独立进程验证通过。现有格式草稿包 train/validation 各一条，build_id=5b01fc10b508722a，审核状态保持 draft_unreviewed。详见 [工作日志](worklogs/2026-10-22-m2-03.md)。

参考：[Transformers 4.57 chat templates](https://huggingface.co/docs/transformers/v4.57.1/en/chat_templating)。具体模板与 fast tokenizer 行为已按本机锁定 4.57.6 实测，本页结果不表示训练或效果提升。
