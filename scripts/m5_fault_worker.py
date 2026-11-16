"""Opt-in controlled slow-token fault, never imported by the production worker.

Run only through check_m5_faults.py against a new isolated database/queue. A real
model generates its first token before this helper pauses it. HTTP/worker time
budgets and production generation parameters remain unchanged.
"""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--pause-seconds", type=float, default=95)
    args = parser.parse_args()
    if args.pause_seconds < 90 or not args.marker.parent.is_dir() or args.marker.exists():
        parser.error("Require a new marker in an existing isolated run and a pause >=90 seconds")
    from transformers.generation.utils import GenerationMixin
    from transformers import StoppingCriteria, StoppingCriteriaList

    original = GenerationMixin.generate
    paused = False

    class FirstTokenPause(StoppingCriteria):
        def __call__(self, input_ids, scores, **kwargs):
            nonlocal paused
            if not paused:
                paused = True
                args.marker.write_text(json.dumps({"event": "real_first_token_generated",
                    "at_unix": time.time(), "sequence_tokens": int(input_ids.shape[-1]),
                    "cuda": input_ids.is_cuda, "injected_pause_seconds": args.pause_seconds}) + "\n")
                time.sleep(args.pause_seconds)
            return False

    def slow_generate(model, *values, **options):
        criteria = StoppingCriteriaList(options.pop("stopping_criteria", None) or [])
        criteria.append(FirstTokenPause())
        return original(model, *values, stopping_criteria=criteria, **options)

    GenerationMixin.generate = slow_generate
    from worker.__main__ import main as worker_main
    worker_main()


if __name__ == "__main__":
    main()
