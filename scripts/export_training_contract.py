"""Export CPU-only training JSON Schema and explicitly illustrative examples."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic.json_schema import models_json_schema  # noqa: E402

from trainer.contracts import (  # noqa: E402
    TRAINING_CONTRACT_VERSION, RuntimeOptions, TrainRequest, TrainResult,
    TrainingFailure, TrainingManifest, TrainingProgress, TrainingSnapshot,
)
from trainer.lora_config import TrainingConfig  # noqa: E402

MODELS = (RuntimeOptions, TrainRequest, TrainResult, TrainingFailure,
          TrainingManifest, TrainingProgress, TrainingSnapshot)
EXAMPLES = PROJECT_ROOT / "docs/examples/training"


def build_examples() -> dict:
    # These revisions, hashes, measurements and versions are invented fixtures.
    # They are never used for execution or presented as observed GPU results.
    task_id = "4b51f20c-32aa-4d57-b3e2-b21a24542e46"
    root = Path("/srv/llmcloud")
    output = root / "data/outputs" / task_id
    config = TrainingConfig()
    runtime = RuntimeOptions(max_steps=2)
    request = TrainRequest(
        task_id=task_id, dataset_path=root / "data/prepared/example/train.jsonl",
        output_dir=output, base_model="Qwen/Qwen2.5-0.5B-Instruct", config=config,
        model_revision="1" * 40, cache_dir=root / "data/models/huggingface/hub",
        log_path=root / "logs/tasks" / f"{task_id}.log",
        validation_dataset_path=root / "data/prepared/example/validation.jsonl",
        dataset_manifest_path=root / "data/prepared/example/manifest.json", runtime=runtime,
    )
    snapshot = TrainingSnapshot(
        task_id=task_id, base_model=request.base_model, model_revision=request.model_revision,
        config=config, runtime=runtime,
    )
    metrics = [TrainingProgress(
        step=step, total_steps=2, loss=loss, learning_rate=0.0002,
        epoch=epoch, recorded_at=f"2026-10-22T08:00:0{step}Z",
    ) for step, loss, epoch in ((1, 2.0, 0.5), (2, 1.9, 1.0))]
    metrics.append(TrainingProgress(
        kind="eval", step=2, total_steps=2, loss=2.1, learning_rate=0.0002,
        epoch=1.0, recorded_at="2026-10-22T08:00:03Z",
    ))
    result = TrainResult(
        adapter_dir=output / "adapter", metrics_path=output / "metrics.jsonl",
        tokenizer_dir=output / "tokenizer", config_path=output / "training_config.json",
        manifest_path=output / "manifest.json",
    )
    artifact_keys = ["adapter/adapter_model.safetensors", "adapter/adapter_config.json",
                     "tokenizer/tokenizer_config.json", "metrics.jsonl", "training_config.json"]
    manifest = TrainingManifest(
        **snapshot.model_dump(), tokenizer_revision="1" * 40, chat_template_sha256="2" * 64,
        train_dataset={"sha256": "3" * 64, "size_bytes": 200, "row_count": 3,
                       "review_status": "draft_unreviewed", "build_id": "4" * 16},
        validation_dataset={"sha256": "5" * 64, "size_bytes": 100, "row_count": 1,
                            "review_status": "draft_unreviewed", "build_id": "4" * 16},
        environment={"code_commit": "6" * 40, "working_tree_dirty": False,
                     "uv_lock_sha256": "7" * 64, "python_version": "3.12.0",
                     "cuda_runtime": "12.8", "gpu_name": "ILLUSTRATIVE GPU",
                     "packages": {name: "0.0.0" for name in
                                  ("torch", "transformers", "datasets", "peft", "trl", "accelerate")}},
        started_at="2026-10-22T08:00:00Z", finished_at="2026-10-22T08:00:04Z",
        summary={"completed_steps": 2, "total_steps": 2, "elapsed_seconds": 4.0,
                 "peak_memory_allocated_bytes": 1024, "trainable_parameters": 10,
                 "total_parameters": 1000, "final_loss": 1.9, "eval_loss": 2.1},
        artifacts=[{"path": key, "sha256": "8" * 64, "size_bytes": 1} for key in artifact_keys],
    )
    failure = TrainingFailure(
        task_id=task_id, code="MODEL_NOT_CACHED", stage="model_loading",
        message="指定 revision 的模型缓存不完整，请先准备模型。",
    )
    return {"request.json": request.model_dump(mode="json"),
            "training_config.json": snapshot.model_dump(mode="json"),
            "progress.jsonl": [event.model_dump(mode="json") for event in metrics],
            "result.json": result.model_dump(mode="json"),
            "manifest.json": manifest.model_dump(mode="json"),
            "failure.json": failure.model_dump(mode="json")}


def generate_outputs() -> dict[Path, str]:
    _, schema = models_json_schema([(model, "validation") for model in MODELS])
    schema.update({"$schema": "https://json-schema.org/draft/2020-12/schema",
                   "title": "LLMCloud internal training contract",
                   "x-contract-version": TRAINING_CONTRACT_VERSION,
                   "x-implementation-status": "types_only",
                   "x-generated-by": "scripts/export_training_contract.py"})
    outputs = {PROJECT_ROOT / "docs/contracts/training.schema.json": schema}
    outputs.update({EXAMPLES / name: value for name, value in build_examples().items()})
    return {path: ("".join(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
                           for event in value) if path.suffix == ".jsonl" else
                   json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            for path, value in outputs.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check drift without writing")
    args = parser.parse_args()
    stale = []
    for path, expected in generate_outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                stale.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if stale:
        print("Stale training contract files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: training contract is current" if args.check else "Generated training schema and illustrative examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
