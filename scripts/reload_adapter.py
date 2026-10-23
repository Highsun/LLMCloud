"""Run in a NEW process after training has exited; local acceptance, not HTTP inference."""

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from uuid import UUID
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trainer.contracts import TrainingError, TrainingFailure  # noqa: E402
from trainer.model_cache import resolve_model_paths  # noqa: E402
from trainer.reload import reload_and_generate  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", type=UUID, required=True)
    parser.add_argument("--prompt", required=True, help="独立开发提示词；不使用冻结评测题调参")
    parser.add_argument("--input", default="")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--revision")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        paths = resolve_model_paths(env_file=args.env_file, data_dir=args.data_dir, cache_dir=args.cache_dir)
        env_file = args.env_file or ROOT / ".env"
        if not env_file.is_absolute(): env_file = ROOT / env_file
        values = {**dotenv_values(env_file, interpolate=False), **os.environ}
        os.environ.update(HF_HOME=str(paths.hf_home), HF_HUB_CACHE=str(paths.cache_dir),
            HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", TOKENIZERS_PARALLELISM="false")
        if values.get("CUDA_VISIBLE_DEVICES") is not None:
            os.environ["CUDA_VISIBLE_DEVICES"] = values["CUDA_VISIBLE_DEVICES"]
        with redirect_stdout(sys.stderr):
            result = reload_and_generate(paths.data_dir / "outputs" / str(args.task_id), paths.cache_dir,
                outputs_root=paths.data_dir / "outputs", expected_task_id=args.task_id, expected_revision=args.revision,
                prompt=args.prompt, input_text=args.input, max_new_tokens=args.max_new_tokens)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except TrainingError as error:
        print(error.failure.model_copy(update={"task_id": args.task_id}).model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(TrainingFailure(task_id=args.task_id, code="INVALID_REQUEST", stage="preflight",
            message=f"重载配置无效（{type(error).__name__}）。").model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
