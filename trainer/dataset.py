"""Validate the initial instruction/input/output JSONL format."""

import json
from collections.abc import Iterator
from pathlib import Path


def iter_records(path: Path) -> Iterator[dict[str, str]]:
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"第 {line_number} 行必须是 JSON 对象")
            for field in ("instruction", "output"):
                if not isinstance(record.get(field), str) or not record[field].strip():
                    raise ValueError(f"第 {line_number} 行的 {field} 必须是非空字符串")
            if not isinstance(record.get("input", ""), str):
                raise ValueError(f"第 {line_number} 行的 input 必须是字符串")
            count += 1
            yield {field: record.get(field, "") for field in ("instruction", "input", "output")}
    if count == 0:
        raise ValueError("数据集必须至少包含一条有效记录")
