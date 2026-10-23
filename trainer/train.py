"""CPU-importable public training boundary; CLI and future Worker share train()."""

from collections.abc import Callable
from datetime import datetime, timezone
import json
import gc
import os
import sys
import time
import traceback

from trainer.contracts import TrainRequest, TrainResult, TrainingProgress, TrainingError, TrainingFailure
from trainer.events import MetricWriter, fail
from trainer.model_cache import verify_model_cache
from trainer.preprocessing import load_training_tokenizer, prepare_training_data
from trainer.run_storage import environment, finish, resolve_request, snapshot, write_json


def train(
    request: TrainRequest,
    on_progress: Callable[[TrainingProgress], None] | None = None,
) -> TrainResult:
    """Perform one isolated CUDA LoRA run, publishing success only after saving."""
    started_at, started_clock = datetime.now(timezone.utc), time.monotonic()
    request = resolve_request(request)
    if on_progress is not None and not callable(on_progress):
        fail("INVALID_REQUEST", "preflight", "on_progress 必须为可调用对象。")
    if os.environ.get("WORLD_SIZE", "1") != "1":
        fail("INVALID_REQUEST", "preflight", "当前训练入口仅支持单进程单 GPU。")
    owned = log_owned = False
    try:
        request.output_dir.parent.mkdir(parents=True, exist_ok=True)
        request.output_dir.mkdir()
        owned = True
        request.log_path.parent.mkdir(parents=True, exist_ok=True)
        with request.log_path.open("x", encoding="utf-8") as log_stream:
            log_owned = True
            def log(stage, **fields):
                try:
                    log_stream.write(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                                                 "stage": stage, **fields}, ensure_ascii=False, allow_nan=False) + "\n")
                    log_stream.flush()
                except (OSError, ValueError) as error:
                    fail("ARTIFACT_WRITE_FAILED", "saving", "无法写入任务日志。", cause=error)
            log("preflight", task_id=str(request.task_id), precision=request.runtime.precision)
            write_json(request.output_dir / "training_config.json", snapshot(request))
            log("model_loading")
            cached = verify_model_cache(request.cache_dir, request.model_revision)
            tokenizer = load_training_tokenizer(request.cache_dir, request.model_revision)
            log("data_preparation")
            prepared = prepare_training_data(request.dataset_path, tokenizer, max_seq_length=request.config.max_seq_length,
                validation_dataset_path=request.validation_dataset_path, dataset_manifest_path=request.dataset_manifest_path)
            log("data_verified", train=prepared.train.summary.model_dump(),
                validation=prepared.validation.summary.model_dump() if prepared.validation else None)
            from trainer.hf_training import execute
            try:
                import torch
                env = environment(torch)
            except Exception as error:
                fail("MODEL_LOAD_FAILED", "model_loading", "无法读取训练依赖、GPU 或代码环境。", cause=error)
            with (request.output_dir / "metrics.jsonl").open("x", encoding="utf-8") as stream:
                execution = execute(request, cached, tokenizer, prepared, MetricWriter(stream, on_progress), log)
            log("training_and_save_finished", completed_steps=execution["completed_steps"])
        return finish(request, prepared, cached, execution, env, started_at, started_clock)
    except Exception as error:
        if isinstance(error, TrainingError):
            failure = error.failure.model_copy(update={"task_id": request.task_id})
        else:
            failure = TrainingFailure(task_id=request.task_id, code="ARTIFACT_WRITE_FAILED", stage="saving",
                                      message=f"任务文件操作失败（{type(error).__name__}）。")
        # Keep stack locations and safe failure metadata, without retaining GPU
        # tensors in inactive Trainer/callback exception-frame locals.
        cause = error
        seen = set()
        diagnostic = []
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            diagnostic.append({"type": type(cause).__name__, "frames": [
                {"file": os.path.basename(frame.filename), "function": frame.name, "line": frame.lineno}
                for frame in traceback.extract_tb(cause.__traceback__)]})
            traceback.clear_frames(cause.__traceback__)
            cause = cause.__cause__ or cause.__context__
        gc.collect()
        torch = sys.modules.get("torch")
        if torch is not None and torch.cuda.is_initialized():
            torch.cuda.empty_cache()
        if log_owned:
            try:
                with request.log_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"recorded_at": datetime.now(timezone.utc).isoformat(),
                                             "stage": "failed", "failure": failure.model_dump(mode="json"),
                                             "diagnostic": diagnostic}, ensure_ascii=False) + "\n")
            except OSError:
                pass
        if owned:
            try:
                write_json(request.output_dir / "failure.json", failure)
            except OSError:
                pass
        raise TrainingError(failure) from error


if __name__ == "__main__":
    from trainer.cli import main
    raise SystemExit(main())
