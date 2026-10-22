"""Instruction preprocessing and label-aware padding; no eager training imports."""

from dataclasses import dataclass
import hashlib
from pathlib import Path

from pydantic import ValidationError

from trainer.contracts import DatasetSummary, TrainingError, TrainingFailure
from trainer.dataset import DatasetScanner, DatasetValidationError, READ_CHUNK_BYTES
from trainer.dataset_schema import InstructionRecord
from trainer.lora_config import TrainingConfig

IGNORE_INDEX = -100


def _fail(code, message, *, row=None, cause=None):
    prefix = f"第 {row} 条有效记录：" if row is not None else ""
    raise TrainingError(TrainingFailure(code=code, stage="data_preparation", message=prefix + message)) from cause


def _length(value):
    try:
        if type(value) is not int:
            raise ValueError()
        return TrainingConfig(max_seq_length=value).max_seq_length
    except (ValueError, ValidationError):
        _fail("INVALID_REQUEST", "max_seq_length 必须是 64–2048 的整数。")


@dataclass(frozen=True)
class TokenizedSample:
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    labels: tuple[int, ...]
    original_tokens: int
    content_tokens: int
    eos_supervised: bool

    def as_feature(self):
        return {"input_ids": list(self.input_ids), "attention_mask": list(self.attention_mask),
                "labels": list(self.labels)}

    def summary(self):
        return {"original_tokens": self.original_tokens, "tokens": len(self.input_ids),
                "truncated": self.original_tokens > len(self.input_ids),
                "supervised_content_tokens": self.content_tokens,
                "supervised_tokens": sum(label != IGNORE_INDEX for label in self.labels),
                "eos_supervised": self.eos_supervised}


@dataclass(frozen=True)
class PreparedDataset:
    samples: tuple[TokenizedSample, ...]
    summary: DatasetSummary


@dataclass(frozen=True)
class PreparedTrainingData:
    train: PreparedDataset
    validation: PreparedDataset | None


def record_messages(record):
    """Use the shared strict record schema even for direct Python callers."""
    try:
        value = InstructionRecord.model_validate(record)
    except ValidationError as error:
        _fail("INVALID_DATASET", "指令记录不符合共享 Schema。", cause=error)
    user = value.instruction + ("\n\n" + value.input if value.input else "")
    return [{"role": "user", "content": user}, {"role": "assistant", "content": value.output}]


def tokenize_record(record, tokenizer, *, max_seq_length=512, row=None):
    limit = _length(max_seq_length)
    messages = record_messages(record)
    if not getattr(tokenizer, "is_fast", False):
        _fail("MODEL_LOAD_FAILED", "监督标签检查需要支持字符偏移的 fast tokenizer。", row=row)
    try:
        prompt = tokenizer.apply_chat_template(messages[:1], tokenize=False, add_generation_prompt=True)
        rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
        empty = tokenizer.apply_chat_template(
            [messages[0], {"role": "assistant", "content": ""}],
            tokenize=False, add_generation_prompt=False,
        )
        eos_text, eos_id = tokenizer.eos_token, tokenizer.eos_token_id
        if not isinstance(prompt, str) or not isinstance(eos_text, str) or type(eos_id) is not int:
            raise ValueError("Missing template or EOS")
        suffix = empty[len(prompt):] if empty.startswith(prompt) else ""
        if (not eos_text or not suffix.startswith(eos_text) or suffix[len(eos_text):].strip()
                or rendered != prompt + messages[1]["content"] + suffix):
            raise ValueError("Template does not preserve the expected assistant span")
        encoding = tokenizer(rendered, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
        ids, offsets = encoding["input_ids"], encoding["offset_mapping"]
        if not ids or len(ids) != len(offsets):
            raise ValueError("Invalid token offsets")
        start, end = len(prompt), len(prompt) + len(messages[1]["content"])
        eos_end = end + len(eos_text)
        special_ids = set(tokenizer.all_special_ids)
        content_mask, eos_mask = [], []
        for token_id, offset in zip(ids, offsets):
            left, right = offset
            if type(token_id) is not int or not (0 <= left <= right <= len(rendered)):
                raise ValueError("Invalid token offset bounds")
            content_mask.append(start <= left < right <= end and token_id not in special_ids)
            eos_mask.append(token_id == eos_id and left == end and right == eos_end)
        if sum(eos_mask) != 1:
            raise ValueError("Expected exactly one template EOS after the answer")
        labels = [token_id if content or eos else IGNORE_INDEX
                  for token_id, content, eos in zip(ids, content_mask, eos_mask)]
        content_count = sum(content_mask[:limit])
        if not content_count:
            _fail("NO_SUPERVISED_TOKENS", "模板化或右截断后没有有效回答 token。", row=row)
        return TokenizedSample(tuple(ids[:limit]), (1,) * min(len(ids), limit), tuple(labels[:limit]),
                               len(ids), content_count, any(eos_mask[:limit]))
    except TrainingError:
        raise
    except Exception as error:
        _fail("MODEL_LOAD_FAILED", f"模板或 token 偏移不兼容（{type(error).__name__}）。", row=row, cause=error)


def _prepare_file(path, tokenizer, limit):
    scanner = DatasetScanner()
    samples = []
    try:
        with Path(path).open("rb") as stream:
            while chunk := stream.read(READ_CHUNK_BYTES):
                for record in scanner.feed(chunk):
                    samples.append(tokenize_record(record, tokenizer, max_seq_length=limit, row=len(samples) + 1))
        for record in scanner.finish():
            samples.append(tokenize_record(record, tokenizer, max_seq_length=limit, row=len(samples) + 1))
    except DatasetValidationError as error:
        line = f"物理行 {error.line}：" if error.line is not None else ""
        _fail("INVALID_DATASET", line + error.message, cause=error)
    except OSError as error:
        _fail("INVALID_DATASET", "无法读取指定数据集文件。", cause=error)
    stats = scanner.stats
    return PreparedDataset(tuple(samples), DatasetSummary(**vars(stats)))


def prepare_training_data(dataset_path, tokenizer, *, max_seq_length=512,
                          validation_dataset_path=None, dataset_manifest_path=None):
    limit = _length(max_seq_length)
    try:
        train_path = Path(dataset_path).resolve(strict=True)
        validation_path = Path(validation_dataset_path).resolve(strict=True) if validation_dataset_path is not None else None
        if validation_path is not None and train_path.samefile(validation_path):
            _fail("INVALID_DATASET", "训练集与验证集不能是同一文件或链接别名。")
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        _fail("INVALID_DATASET", "数据集路径无法解析。", cause=error)
    train = _prepare_file(train_path, tokenizer, limit)
    validation = _prepare_file(validation_path, tokenizer, limit) if validation_path else None
    if validation is not None and train.summary.sha256 == validation.summary.sha256:
        _fail("INVALID_DATASET", "训练集与验证集的原始内容完全相同。")
    if dataset_manifest_path is not None:
        from trainer.dataset_manifest import verify_prepared_metadata
        summaries = verify_prepared_metadata(dataset_manifest_path, train.summary,
                                             validation.summary if validation else None)
        train = PreparedDataset(train.samples, summaries["train"])
        if validation:
            validation = PreparedDataset(validation.samples, summaries["validation"])
    return PreparedTrainingData(train, validation)


def load_training_tokenizer(cache_dir, revision):
    from trainer.model_cache import verify_model_cache
    cached = verify_model_cache(cache_dir, revision)
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(str(cached.snapshot_dir), use_fast=True,
                                                  local_files_only=True, trust_remote_code=False, token=False)
        if not tokenizer.is_fast or hashlib.sha256(tokenizer.chat_template.encode()).hexdigest() != cached.manifest.chat_template_sha256:
            raise ValueError("Tokenizer does not match the pinned template")
        return tokenizer
    except Exception as error:
        _fail("MODEL_LOAD_FAILED", f"无法离线加载匹配的 fast tokenizer（{type(error).__name__}）。", cause=error)


class InstructionCollator:
    """Right pad without replacing completion labels; torch imported only on demand."""

    def __init__(self, pad_token_id, *, return_tensors="pt"):
        if type(pad_token_id) is not int or pad_token_id < 0 or return_tensors not in (None, "pt"):
            _fail("INVALID_REQUEST", "需要有效 pad_token_id 和 pt/None 输出格式。")
        self.pad_token_id, self.return_tensors = pad_token_id, return_tensors

    def __call__(self, features):
        if not features:
            _fail("INVALID_DATASET", "不能构造空训练批次。")
        for feature in features:
            if not isinstance(feature, dict) or set(feature) != {"input_ids", "attention_mask", "labels"}:
                _fail("INVALID_DATASET", "训练特征必须只含 input_ids/attention_mask/labels。")
            ids, mask, labels = (feature[key] for key in ("input_ids", "attention_mask", "labels"))
            if (not all(isinstance(value, (list, tuple)) for value in (ids, mask, labels))
                    or not ids or len(ids) != len(mask) or len(ids) != len(labels)
                    or any(type(value) is not int or value < 0 for value in ids)
                    or any(value != 1 for value in mask)
                    or any(type(label) is not int or label not in (IGNORE_INDEX, token) for token, label in zip(ids, labels))
                    or not any(label != IGNORE_INDEX for label in labels)):
                _fail("INVALID_DATASET", "训练特征长度、注意力或标签不一致。")
        width = max(len(feature["input_ids"]) for feature in features)
        result = {key: [] for key in ("input_ids", "attention_mask", "labels")}
        for feature in features:
            padding = width - len(feature["input_ids"])
            for key, value in (("input_ids", self.pad_token_id), ("attention_mask", 0), ("labels", IGNORE_INDEX)):
                result[key].append(list(feature[key]) + [value] * padding)
        if self.return_tensors == "pt":
            try:
                import torch
            except ImportError as error:
                _fail("MODEL_LOAD_FAILED", "张量批次需要 training extra 中的 PyTorch。", cause=error)
            return {key: torch.tensor(value, dtype=torch.long) for key, value in result.items()}
        return result
