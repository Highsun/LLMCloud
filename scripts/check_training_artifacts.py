"""Read-only CPU audit; does not load a base model or perform Adapter inference."""

import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trainer.artifacts import verify_training_artifacts  # noqa: E402
from trainer.contracts import TrainingError, TrainingFailure  # noqa: E402
from trainer.model_cache import resolve_model_paths  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", type=UUID, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--revision", help="Expected immutable base revision, if supplied")
    args = parser.parse_args()
    try:
        paths = resolve_model_paths(env_file=args.env_file, data_dir=args.data_dir)
        outputs_root = paths.data_dir / "outputs"
        verified = verify_training_artifacts(outputs_root / str(args.task_id), outputs_root=outputs_root,
                                              expected_task_id=args.task_id, expected_revision=args.revision)
        print(json.dumps(verified.summary(), ensure_ascii=False, indent=2))
        return 0
    except TrainingError as error:
        print(error.failure.model_copy(update={"task_id": args.task_id}).model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(TrainingFailure(task_id=args.task_id, code="INVALID_REQUEST", stage="preflight",
                              message=f"产物检查配置无效（{type(error).__name__}）。").model_dump_json(), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
