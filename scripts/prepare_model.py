"""Prepare pinned Qwen weights, or verify existing cache strictly offline."""

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from trainer.contracts import TrainingError, TrainingFailure  # noqa: E402
from trainer.model_cache import prepare_model_cache, resolve_model_paths, verify_model_cache  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "check"):
        command = subparsers.add_parser(name)
        command.add_argument("--revision", required=name == "check", default="main")
        command.add_argument("--env-file", type=Path)
        command.add_argument("--data-dir", type=Path)
        command.add_argument("--hf-home", type=Path)
        command.add_argument("--cache-dir", type=Path)
        if name == "check":
            command.add_argument("--gpu", action="store_true", help="Load real cached model and run CUDA forward")
            command.add_argument("--precision", choices=("bf16", "fp32"), default="bf16")
    args = parser.parse_args()
    try:
        paths = resolve_model_paths(env_file=args.env_file, data_dir=args.data_dir,
                                    hf_home=args.hf_home, cache_dir=args.cache_dir)
        # Before lazy HF imports, align all cache locations with resolved CLI configuration.
        os.environ["HF_HOME"] = str(paths.hf_home)
        os.environ["HF_HUB_CACHE"] = str(paths.cache_dir)
        os.environ.setdefault("HF_XET_CACHE", str(paths.hf_home / "xet"))
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        if args.command == "prepare":
            result = prepare_model_cache(paths.cache_dir, args.revision).summary()
        else:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            if args.gpu:
                from trainer.model_probe import probe_model_gpu
                result = probe_model_gpu(paths.cache_dir, args.revision, precision=args.precision)
            else:
                result = verify_model_cache(paths.cache_dir, args.revision).summary()
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except TrainingError as error:
        print(error.failure.model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        failure = TrainingFailure(code="INVALID_REQUEST", stage="preflight",
                                  message=f"模型准备参数或路径无效（{type(error).__name__}）。")
        print(failure.model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
