"""Trusted local CLI. HTTP clients never supply these filesystem paths."""

import argparse
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

from dotenv import dotenv_values
from pydantic import ValidationError

from trainer.contracts import RuntimeOptions, TrainRequest, TrainingError, TrainingFailure
from trainer.lora_config import TrainingConfig
from trainer.model_cache import MODEL_ID, PROJECT_ROOT, resolve_model_paths


def main():
    parser = argparse.ArgumentParser(description="LLMCloud 单 GPU LoRA 训练")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--validation-dataset", type=Path)
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument("--config", type=Path, help="TrainingConfig JSON；省略使用契约默认值")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument("--precision", choices=("bf16", "fp32"), default="bf16")
    parser.add_argument("--task-id", type=UUID)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    task_id = args.task_id or uuid4()
    try:
        def absolute(path):
            return (path if path.is_absolute() else PROJECT_ROOT / path).absolute()
        paths = resolve_model_paths(env_file=args.env_file, data_dir=args.data_dir, cache_dir=args.cache_dir)
        values = {**dotenv_values(absolute(args.env_file) if args.env_file else PROJECT_ROOT / ".env", interpolate=False), **os.environ}
        log_root = absolute(args.log_dir or Path(values.get("LOG_DIR") or "logs")).resolve()
        os.environ.update(HF_HOME=str(paths.hf_home), HF_HUB_CACHE=str(paths.cache_dir),
                          HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                          TOKENIZERS_PARALLELISM="false")
        if values.get("CUDA_VISIBLE_DEVICES") is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = values["CUDA_VISIBLE_DEVICES"]
        config = TrainingConfig()
        if args.config:
            config_path = absolute(args.config)
            if config_path.stat().st_size > 64 * 1024:
                raise ValueError("Configuration too large")
            config = TrainingConfig.model_validate_json(config_path.read_bytes())
        request = TrainRequest(task_id=task_id, dataset_path=absolute(args.dataset),
            validation_dataset_path=absolute(args.validation_dataset) if args.validation_dataset else None,
            dataset_manifest_path=absolute(args.dataset_manifest) if args.dataset_manifest else None,
            output_dir=paths.data_dir / "outputs" / str(task_id), log_path=log_root / "tasks" / f"{task_id}.log",
            base_model=MODEL_ID, model_revision=args.revision, cache_dir=paths.cache_dir, config=config,
            runtime=RuntimeOptions(max_steps=args.max_steps, precision=args.precision))
        from trainer.train import train
        def on_progress(event):
            print(event.model_dump_json(), file=sys.stderr, flush=True)
        with redirect_stdout(sys.stderr):
            result = train(request, on_progress)
        print(result.model_dump_json(indent=2))
        return 0
    except TrainingError as error:
        print(error.failure.model_copy(update={"task_id": task_id}).model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, ValidationError) as error:
        print(TrainingFailure(task_id=task_id, code="INVALID_REQUEST", stage="preflight",
                              message=f"训练参数或路径无效（{type(error).__name__}）。").model_dump_json(), file=sys.stderr)
        return 2
