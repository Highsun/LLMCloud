"""Bounded, CPU-only JSONL reader shared by uploads and training."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from collections.abc import Iterator

from pydantic import ValidationError

from trainer.dataset_schema import InstructionRecord, MAX_DATASET_BYTES, MAX_JSONL_LINE_BYTES

READ_CHUNK_BYTES = 64 * 1024


class DatasetValidationError(ValueError):
    """Safe diagnostic: never include a raw JSON record or Pydantic input."""

    def __init__(self, code: str, message: str, *, line=None, column=None, field=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.line, self.column, self.field = line, column, field


@dataclass(frozen=True)
class DatasetStats:
    size_bytes: int
    row_count: int
    sha256: str


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey()
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Non-standard JSON constant")


def _check_nesting(text: str) -> None:
    # Valid instruction records have only string values. Bound malicious JSON
    # before calling the recursive C decoder, irrespective of Python's recursion limit.
    depth = 0
    quoted = escaped = False
    for character in text:
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
        elif character == '"':
            quoted = True
        elif character in "[{":
            depth += 1
            if depth > 128:
                raise ValueError("JSON nesting limit exceeded")
        elif character in "]}":
            depth -= 1


class DatasetScanner:
    """Feed raw bytes; only one bounded physical line is retained between calls."""

    def __init__(self, *, max_bytes=MAX_DATASET_BYTES, max_line_bytes=MAX_JSONL_LINE_BYTES):
        self.max_bytes, self.max_line_bytes = max_bytes, max_line_bytes
        self._size = self._rows = 0
        self._line = 1
        self._pending = bytearray()
        self._hash = hashlib.sha256()
        self._finished = False

    def _append(self, part: bytes) -> None:
        if len(self._pending) + len(part) > self.max_line_bytes:
            raise DatasetValidationError("line_too_large", "数据集单行超过大小限制。", line=self._line)
        self._pending.extend(part)

    def _record(self) -> dict[str, str] | None:
        try:
            text = self._pending.decode("utf-8-sig" if self._line == 1 else "utf-8")
        except UnicodeDecodeError:
            raise DatasetValidationError("invalid_encoding", "数据集必须为有效 UTF-8。", line=self._line) from None
        if not text.strip():
            return None
        try:
            _check_nesting(text)
            value = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except _DuplicateKey:
            raise DatasetValidationError("duplicate_key", "JSON 对象存在重复键。", line=self._line) from None
        except json.JSONDecodeError as error:
            raise DatasetValidationError("invalid_json", "数据集包含无效 JSON。", line=self._line, column=error.colno) from None
        except (ValueError, RecursionError):
            raise DatasetValidationError("invalid_json", "数据集包含非标准或过深的 JSON。", line=self._line) from None
        if not isinstance(value, dict):
            raise DatasetValidationError("invalid_type", "每行必须是 JSON 对象。", line=self._line)
        try:
            record = InstructionRecord.model_validate(value)
        except ValidationError as error:
            issue = error.errors(include_input=False, include_context=False, include_url=False)[0]
            code = {"missing": "missing", "extra_forbidden": "extra_field", "string_type": "invalid_type", "value_error": "blank"}.get(issue["type"], "invalid_type")
            field = issue["loc"][0] if issue["loc"] and issue["loc"][0] in InstructionRecord.model_fields else None
            message = {"missing": "缺少必填字段。", "extra_field": "记录包含不支持的字段。", "blank": "必填字段不能是空白字符串。", "invalid_type": "记录字段类型不正确。"}[code]
            raise DatasetValidationError(code, message, line=self._line, field=field) from None
        self._rows += 1
        return record.model_dump()

    def feed(self, chunk: bytes) -> list[dict[str, str]]:
        if self._finished:
            raise RuntimeError("Scanner is already finished")
        if not isinstance(chunk, bytes):
            raise TypeError("A binary stream must return bytes")
        self._size += len(chunk)
        if self._size > self.max_bytes:
            raise DatasetValidationError("file_too_large", "数据集文件超过大小限制。")
        self._hash.update(chunk)
        records = []
        start = 0
        while (end := chunk.find(b"\n", start)) != -1:
            self._append(chunk[start:end + 1])
            record = self._record()
            if record is not None:
                records.append(record)
            self._pending.clear()
            self._line += 1
            start = end + 1
        self._append(chunk[start:])
        return records

    def finish(self) -> list[dict[str, str]]:
        if self._finished:
            raise RuntimeError("Scanner is already finished")
        records = []
        if self._pending:
            record = self._record()
            if record is not None:
                records.append(record)
        if not self._rows:
            raise DatasetValidationError("empty", "数据集必须至少包含一条有效记录。")
        self._pending.clear()
        self._finished = True
        return records

    @property
    def stats(self) -> DatasetStats:
        if not self._finished:
            raise RuntimeError("Finish validation before reading statistics")
        return DatasetStats(self._size, self._rows, self._hash.hexdigest())


def scan_dataset(path: Path) -> DatasetStats:
    scanner = DatasetScanner()
    with Path(path).open("rb") as source:
        while chunk := source.read(READ_CHUNK_BYTES):
            scanner.feed(chunk)
    scanner.finish()
    return scanner.stats


def iter_records(path: Path) -> Iterator[dict[str, str]]:
    scanner = DatasetScanner()
    with Path(path).open("rb") as source:
        while chunk := source.read(READ_CHUNK_BYTES):
            yield from scanner.feed(chunk)
    yield from scanner.finish()
