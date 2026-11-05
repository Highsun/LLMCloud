"""Generate M4 types and explicitly mock fixtures; never register HTTP routes."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic.json_schema import models_json_schema  # noqa: E402

from backend.app.core.observability_contract import (  # noqa: E402
    COMMON_OBSERVABILITY_ERROR_STATUS, LOG_COMMON_FIELDS, LOG_DATASET_FIELDS,
    LOG_DIAGNOSTIC_FIELDS, LOG_FAILURE_FIELDS, LOG_FIELDS_BY_STAGE, LOG_FRAME_FIELDS,
    OBSERVABILITY_CONTRACT_VERSION, OBSERVABILITY_ERROR_STATUS, contract_limits,
)
from backend.app.core.observability_protocols import CompletedArtifactSpec  # noqa: E402
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION  # noqa: E402
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402
from backend.app.models.observability_schemas import (  # noqa: E402
    AdapterDownloadHeaders, AdapterQuery, DownloadBusyHeaders, LogsPage, LogsQuery,
    MetricRecord, MetricsPage, MetricsQuery,
)
from trainer.contracts import TrainingProgress  # noqa: E402

TASK_ID = "44444444-4444-4444-8444-444444444444"
COMPLETED_TASK_ID = "55555555-5555-4555-8555-555555555555"
SOURCE_ID = "a" * 64
MODELS = (MetricsQuery, LogsQuery, AdapterQuery, MetricRecord, MetricsPage, LogsPage,
          AdapterDownloadHeaders, DownloadBusyHeaders, ErrorResponse, CompletedArtifactSpec)


def mock_events():
    """Fixed format-only values. No training or wall-clock sampling occurs."""
    return [TrainingProgress(kind=kind, step=step, total_steps=2, loss=loss,
        learning_rate=0.0002 if step == 1 else 0.0, epoch=step / 2,
        recorded_at=f"2026-11-04T01:00:0{index}Z")
        for index, (kind, step, loss) in enumerate((
            ("train", 1, 1.25), ("eval", 1, 1.5), ("train", 2, 0.75), ("eval", 2, 1.0)), start=1)]


def mock_metric_bytes():
    return b"".join((event.model_dump_json() + "\n").encode("utf-8") for event in mock_events())


def build_examples():
    events, records, cursor = mock_events(), [], 0
    for event in events:
        records.append(MetricRecord(**event.model_dump(), offset=cursor))
        cursor += len((event.model_dump_json() + "\n").encode("utf-8"))

    def page(items, *, status="RUNNING", next_cursor=0, more=False, partial=False):
        return MetricsPage(task_id=TASK_ID, task_status=status, source_state="ready",
            source_id=SOURCE_ID, items=items, next_cursor=next_cursor, has_more=more, tail_incomplete=partial)

    def logs(lines, *, status="RUNNING", truncated=False, partial=False, filtered=0):
        return LogsPage(task_id=TASK_ID, task_status=status, source_state="ready", lines=lines,
            truncated=truncated, tail_incomplete=partial, filtered_lines=filtered)

    def log(stage, **fields):
        return json.dumps({"recorded_at": "2026-11-04T01:00:01Z", "stage": stage, **fields},
            ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    spec = CompletedArtifactSpec.model_validate({
        "spec": {"task_id": COMPLETED_TASK_ID, "dataset_id": "03a853e2-1bf1-45da-92fb-5a1548499fc4",
            "dataset_key": "datasets/03a853e2-1bf1-45da-92fb-5a1548499fc4/train.jsonl",
            "dataset_sha256": "b" * 64, "dataset_size_bytes": 200, "dataset_row_count": 3,
            "base_model": "Qwen/Qwen2.5-0.5B-Instruct", "model_revision": DEFAULT_MODEL_REVISION,
            "config": {}, "runtime": {"precision": "bf16", "max_steps": 2, "local_files_only": True}},
        "output_key": f"outputs/{COMPLETED_TASK_ID}", "manifest_sha256": "c" * 64,
        "training_summary": {"completed_steps": 2, "total_steps": 2, "elapsed_seconds": 1.0,
            "peak_memory_allocated_bytes": 0, "trainable_parameters": 540672,
            "total_parameters": 494032768, "final_loss": 0.75, "eval_loss": None},
    })
    zero = MetricRecord(kind="train", step=1, total_steps=1, loss=0.0, learning_rate=0.0,
        epoch=1.0, recorded_at="2026-11-04T01:00:01Z", offset=0)
    zero_length = len((TrainingProgress.model_validate(zero.model_dump(exclude={"offset"})).model_dump_json() + "\n").encode())
    values = {
        "metrics-query-initial.json": MetricsQuery(limit=2),
        "metrics-query-next.json": MetricsQuery(cursor=records[2].offset, source_id=SOURCE_ID, limit=2),
        "logs-query.json": LogsQuery(),
        "adapter-query.json": AdapterQuery(),
        "metrics-not-created.json": MetricsPage(task_id=TASK_ID, task_status="RUNNING", source_state="not_created",
            source_id=None, items=[], next_cursor=0, has_more=False, tail_incomplete=False),
        "metrics-empty.json": page([]),
        "metrics-first-page.json": page(records[:2], next_cursor=records[2].offset, more=True),
        "metrics-next-page.json": page(records[2:], status="COMPLETED", next_cursor=cursor),
        "metrics-terminal-drained.json": page([], status="COMPLETED", next_cursor=cursor),
        "metrics-incomplete-tail.json": page(records[:2], status="FAILED", next_cursor=records[2].offset, partial=True),
        "metrics-zero-loss.json": page([zero], next_cursor=zero_length),
        "logs-not-created.json": LogsPage(task_id=TASK_ID, task_status="FAILED", source_state="not_created",
            lines=[], truncated=False, tail_incomplete=False, filtered_lines=0),
        "logs-empty.json": logs([]),
        "logs-ready.json": logs([log("model_loading"), log("training", total_steps=2, gradient_accumulation_steps=8)]),
        "logs-truncated.json": logs([log("training_and_save_finished", completed_steps=2)], status="COMPLETED", truncated=True),
        "logs-filtered-tail.json": logs([log("failed", failure={"task_id": TASK_ID,
            "code": "TRAINING_FAILED", "stage": "training"})], status="FAILED", partial=True, filtered=1),
        "adapter-headers.json": AdapterDownloadHeaders.for_task(COMPLETED_TASK_ID),
        "download-busy-headers.json": DownloadBusyHeaders(),
        "completed-artifact-spec.json": spec,
    }
    for code in OBSERVABILITY_ERROR_STATUS:
        values[f"error-{code.value.lower().replace('_', '-')}.json"] = ErrorResponse.model_validate({"error": {
            "code": code.value, "message": f"格式样例：{code.value}。", "details": [], "details_truncated": False,
            "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df",
        }})
    return values


def generate_outputs():
    _, schema = models_json_schema([(model, "validation") for model in MODELS])
    schema.update({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "LLMCloud observability contracts (types only)",
        "x-contract-version": OBSERVABILITY_CONTRACT_VERSION,
        "x-implementation-status": "types_only",
        "x-http-implementation-status": "not_asserted",
        "x-generated-by": "scripts/export_observability_contract.py",
        "x-limits": contract_limits(),
        "x-error-http-status": {**COMMON_OBSERVABILITY_ERROR_STATUS,
            **{code.value: status for code, status in OBSERVABILITY_ERROR_STATUS.items()}},
        "x-log-projection": {"common": LOG_COMMON_FIELDS, "stages": dict(LOG_FIELDS_BY_STAGE),
            "dataset": LOG_DATASET_FIELDS, "failure": LOG_FAILURE_FIELDS,
            "diagnostic": LOG_DIAGNOSTIC_FIELDS, "frame": LOG_FRAME_FIELDS},
        "x-zip-layout": {"root": "{task_id}/", "members": "verified manifest.artifacts plus manifest.json",
            "temporary_directory": "DATA_DIR/downloads", "response_body": "binary ZIP, not JSON"},
    })
    examples = build_examples()
    index = {"mock": True, "contract_version": OBSERVABILITY_CONTRACT_VERSION,
        "http_evidence": False, "note": "All IDs/values/bytes are format-only fixtures, not GPU evidence.",
        "fixtures": {name: {"model": type(model).__name__, "usage": (
            "internal_snapshot" if isinstance(model, CompletedArtifactSpec) else
            "header_description_not_json_body" if isinstance(model, (AdapterDownloadHeaders, DownloadBusyHeaders)) else
            "query" if isinstance(model, (MetricsQuery, LogsQuery, AdapterQuery)) else "json_body"),
            **({"http_status": OBSERVABILITY_ERROR_STATUS[model.error.code.value]} if isinstance(model, ErrorResponse) else {})}
            for name, model in examples.items()}}
    values = {PROJECT_ROOT / "docs/contracts/observability.schema.json": schema,
        PROJECT_ROOT / "docs/examples/observability/index.json": index}
    values.update({PROJECT_ROOT / "docs/examples/observability" / name: model.model_dump(mode="json", by_alias=True)
                   for name, model in examples.items()})
    outputs = {path: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
               for path, value in values.items()}
    outputs[PROJECT_ROOT / "docs/examples/observability/README.md"] = """# M4 观测契约格式样例（全部为 mock）

由 scripts/export_observability_contract.py 从正式 CPU 类型生成，不手工修改。index.json 标注每个文件的模型和用途；数值、UUID、时间、文件版本/哈希及内部完成快照均为格式占位，不是训练/HTTP/GPU 验收。

metrics-first-page 与 metrics-next-page 是同一虚构 UTF-8 JSONL 流的两页，演示查询显式 limit=2（协议默认仍为 200）；offset/next_cursor 根据原 TrainingProgress 紧凑 JSON 加换行的字节数实际计算，同一步 train/eval 都保留。terminal-drained 展示已消费完的终态空页；empty 是存在的空文件，not-created 是尚未产出；incomplete-tail 不把半行当点。zero-loss 的 0 是有效值。其他文件是不同边界场景，不代表同一运行的连续历史；内部完成快照/下载头使用另一个 UUID，避免把含 eval 的格式流误当作当前服务已配置验证集。

logs-* 是安全投影后的格式示例，不表示 M4-02 已实现日志读取/过滤。adapter-headers 和 download-busy-headers 描述 HTTP 头（前者的 task_id 只是上下文），下载成功的真实 body 是 ZIP，不是这些 JSON。completed-artifact-spec 是内部脱离 SQL 的占位 DTO，不包含真实权重，也不能证明数据库完成或产物有效。

本导出器只提供类型，不声明运行时 metrics/logs/adapter 路由是否实现，前端须按真实 OpenAPI 能力探测。正式字段/约束与消费者核对清单见 [观测契约](../../api/task-observability.md)。重新生成使用 uv run --locked python scripts/export_observability_contract.py；加 --check 只读检查 Schema、全部样例及多余 JSON 的漂移。
"""
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check generated types/mock fixtures without writing")
    args = parser.parse_args()
    outputs = generate_outputs()
    stale = []
    for path, expected in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if args.check:
        folder = PROJECT_ROOT / "docs/examples/observability"
        stale += [str(path.relative_to(PROJECT_ROOT)) for path in sorted(folder.glob("*.json")) if path not in outputs]
    if stale:
        print("Stale observability contract files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: observability contract is current" if args.check else "Generated M4 types/mock fixtures; not a runtime OpenAPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
