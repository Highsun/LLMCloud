"""Read-only tokenizer/labels diagnostic. No model weights, GPU or training."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trainer.contracts import TrainingError, TrainingFailure  # noqa: E402
from trainer.model_cache import resolve_model_paths  # noqa: E402
from trainer.preprocessing import InstructionCollator, load_training_tokenizer, prepare_training_data  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--validation-dataset", type=Path)
    parser.add_argument("--dataset-manifest", type=Path)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--show-sample", type=int, help="Explicitly print one 1-based training sample's text/tokens/labels")
    args = parser.parse_args()
    try:
        paths = resolve_model_paths(env_file=args.env_file, cache_dir=args.cache_dir)
        os.environ.update(HF_HOME=str(paths.hf_home), HF_HUB_CACHE=str(paths.cache_dir),
                          HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                          USE_TORCH="0", USE_TF="0", USE_FLAX="0", TOKENIZERS_PARALLELISM="false")
        tokenizer = load_training_tokenizer(paths.cache_dir, args.revision)
        def dataset_path(path):
            return path if path.is_absolute() else ROOT / path
        prepared = prepare_training_data(
            dataset_path(args.dataset), tokenizer, max_seq_length=args.max_seq_length,
            validation_dataset_path=dataset_path(args.validation_dataset) if args.validation_dataset else None,
            dataset_manifest_path=dataset_path(args.dataset_manifest) if args.dataset_manifest else None,
        )
        def summary(dataset):
            return {**dataset.summary.model_dump(), "truncated_rows": sum(sample.summary()["truncated"] for sample in dataset.samples),
                    "sample_tokens": [sample.summary() for sample in dataset.samples[:3]]}
        result = {"status": "training_data_verified", "model_revision": args.revision,
                  "chat_template_sha256": hashlib.sha256(tokenizer.chat_template.encode()).hexdigest(),
                  "max_seq_length": args.max_seq_length, "train": summary(prepared.train),
                  "validation": summary(prepared.validation) if prepared.validation else None}
        features = [sample.as_feature() for sample in prepared.train.samples[:2]]
        batch = InstructionCollator(tokenizer.pad_token_id, return_tensors=None)(features)
        result["batch_shape"] = [len(batch["input_ids"]), len(batch["input_ids"][0])]
        if args.show_sample is not None:
            if not 1 <= args.show_sample <= len(prepared.train.samples):
                raise ValueError("Sample number out of range")
            sample = prepared.train.samples[args.show_sample - 1]
            result["explicit_sample"] = {"row": args.show_sample, **sample.as_feature(),
                                         "tokens": tokenizer.convert_ids_to_tokens(list(sample.input_ids)),
                                         "decoded_text": tokenizer.decode(list(sample.input_ids), skip_special_tokens=False),
                                         "supervised_text": tokenizer.decode([label for label in sample.labels if label != -100],
                                                                             skip_special_tokens=False)}
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except TrainingError as error:
        print(error.failure.model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(TrainingFailure(code="INVALID_REQUEST", stage="data_preparation",
                              message=f"数据检查参数或路径无效（{type(error).__name__}）。").model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
