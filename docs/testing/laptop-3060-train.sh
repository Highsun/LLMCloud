#!/usr/bin/env bash
# L3: a two-step real LoRA smoke test using existing project entry points.
set -uo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
    echo "Usage: bash laptop-3060-train.sh [--check]" >&2; exit 2
fi
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
if [[ -z "$uv_bin" || ! -x .venv/bin/python || ! -f docs/examples/train.jsonl ]]; then
    echo "Missing uv, project environment, or public training format sample." >&2; exit 2
fi
revision=7ae557604adf67be50417f59c2c2f167def9a775
dataset="$PWD/docs/examples/train.jsonl"
hf_home="$PWD/data/models/huggingface"
cache_dir="$hf_home/hub"
parent="$report_repo/data/acceptance/b-review/laptop-3060"
if [[ "${1:-}" == "--check" ]]; then
    printf 'READY: repo=%s\nDATASET=%s\nMODEL_CACHE=%s\nRESULTS_PARENT=%s\n' "$PWD" "$dataset" "$cache_dir" "$parent"
    .venv/bin/python - <<'PY'
from trainer.lora_config import TrainingConfig
print(TrainingConfig(lora_r=4, lora_alpha=8, per_device_train_batch_size=1,
                     gradient_accumulation_steps=1, max_seq_length=128).model_dump_json())
PY
    exit $?
fi

export TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0
export HF_HOME="$hf_home" HF_HUB_CACHE="$cache_dir" HF_XET_CACHE="$hf_home/xet"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
export TOKENIZERS_PARALLELISM=false
task_id="$(.venv/bin/python -c 'from uuid import uuid4; print(uuid4())')" || exit 2
runtime_parent="$PWD/data/local-validation/laptop-3060"
runtime_dir="$runtime_parent/$task_id"
mkdir -p "$parent" "$runtime_parent" || exit 2
mkdir "$runtime_dir" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-train-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\nTASK_ID=%s\nRUNTIME_DIR=%s\n' "$run_dir" "$task_id" "$runtime_dir"

.venv/bin/python - "$0" "$uv_bin" "$dataset" "$runtime_dir" "$task_id" > "$run_dir/metadata.json" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import subprocess
import sys
from trainer.lora_config import TrainingConfig

def output(*args):
    return subprocess.check_output(args, text=True).strip()

runner, dataset, runtime = Path(sys.argv[1]).resolve(), Path(sys.argv[3]), Path(sys.argv[4])
config = TrainingConfig(lora_r=4, lora_alpha=8, per_device_train_batch_size=1,
                       gradient_accumulation_steps=1, max_seq_length=128)
with (runtime / "config.json").open("x") as stream:
    stream.write(config.model_dump_json(indent=2) + "\n")
status = output("git", "status", "--porcelain")
print(json.dumps({
    "started_at_utc": datetime.now(timezone.utc).isoformat(),
    "repo": str(Path.cwd()), "code_commit": output("git", "rev-parse", "HEAD"),
    "working_tree_dirty": bool(status), "git_status_porcelain": status,
    "uv_lock_sha256": sha256(Path("uv.lock").read_bytes()).hexdigest(),
    "runner_path": str(runner), "runner_sha256": sha256(runner.read_bytes()).hexdigest(),
    "python": sys.version, "platform": platform.platform(), "uv": output(sys.argv[2], "--version"),
    "packages": dict(sorted((d.metadata["Name"], d.version)
                            for d in distributions() if d.metadata["Name"])),
    "task_id": sys.argv[5], "runtime_dir": str(runtime),
    "dataset_path": str(dataset), "dataset_sha256": sha256(dataset.read_bytes()).hexdigest(),
    "dataset_purpose": "public engineering format sample; not formal effect evaluation",
    "training_config": config.model_dump(), "max_steps": 2, "precision": "bf16",
    "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo "Metadata/config preparation failed; training not started." >&2; exit 2; fi

run_logged() {
    local name="$1"
    shift
    "$uv_bin" run --offline --locked --extra training "$@" 2>&1 | tee "$run_dir/$name.log"
    local codes=("${PIPESTATUS[@]}")
    command_exit="${codes[0]}"
    log_exit="${codes[1]}"
    printf 'CHECK_EXIT=%s:%s LOG_EXIT=%s\n' "$name" "$command_exit" "$log_exit"
}
run_logged preflight python scripts/check_training_data.py --dataset "$dataset" \
    --revision "$revision" --max-seq-length 128 --cache-dir "$cache_dir"
preflight_exit="$command_exit"
preflight_log_exit="$log_exit"
training_exit=not_run
training_log_exit=not_run
if [[ "$preflight_exit" -eq 0 && "$preflight_log_exit" -eq 0 ]]; then
    run_logged training python -m trainer.train --dataset "$dataset" --revision "$revision" \
        --config "$runtime_dir/config.json" --max-steps 2 --precision bf16 --task-id "$task_id" \
        --data-dir "$runtime_dir/data" --log-dir "$runtime_dir/logs" --cache-dir "$cache_dir"
    training_exit="$command_exit"
    training_log_exit="$log_exit"
fi

.venv/bin/python - "$run_dir" "$runtime_dir" "$task_id" "$preflight_exit" "$preflight_log_exit" "$training_exit" "$training_log_exit" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

root, runtime, task_id = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
manifest_path = runtime / "data/outputs" / task_id / "manifest.json"
result = manifest = None
error_type = None
text = (root / "training.log").read_text(errors="replace") if (root / "training.log").exists() else ""
decoder = json.JSONDecoder()
for match in re.finditer(r"(?m)^\{", text):
    try:
        candidate, _ = decoder.raw_decode(text[match.start():])
    except ValueError:
        continue
    if isinstance(candidate, dict) and ("manifest_path" in candidate or "code" in candidate):
        result = candidate
if result is not None:
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
try:
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
    # Only small result metadata/logs are copied to D. Adapter/tokenizer/data remain in E.
    for source, name in [
        (manifest_path, "training-manifest.json"),
        (manifest_path.parent / "metrics.jsonl", "metrics.jsonl"),
        (manifest_path.parent / "training_config.json", "training-snapshot.json"),
        (manifest_path.parent / "failure.json", "training-failure.json"),
        (runtime / "logs/tasks" / f"{task_id}.log", "task.log"),
    ]:
        if source.is_file():
            if source.is_symlink() or source.stat().st_size > 1024 * 1024:
                raise ValueError("Result copy exceeds the small-evidence limit")
            with (root / name).open("xb") as out:
                out.write(source.read_bytes())
except Exception as error:
    error_type = type(error).__name__
passed = (all(code == "0" for code in sys.argv[4:8]) and error_type is None
          and result is not None and result.get("manifest_path") == str(manifest_path)
          and manifest is not None and manifest.get("task_id") == task_id
          and manifest.get("status") == "completed"
          and manifest["summary"]["completed_steps"] == manifest["summary"]["total_steps"] == 2)
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "two_step_lora",
    "status": "passed" if passed else "failed_or_incomplete", "task_id": task_id,
    "preflight_exit_code": sys.argv[4], "preflight_log_exit_code": sys.argv[5],
    "training_exit_code": sys.argv[6], "training_log_exit_code": sys.argv[7],
    "real_training_attempted": sys.argv[6] != "not_run",
    "runtime_dir": str(runtime), "evidence_dir": str(root),
    "manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.is_file() else None,
    "training_summary": manifest["summary"] if manifest else None,
    "result_copy_error_type": error_type,
    "independent_artifact_audit": "pending", "new_process_reload": "pending",
    "model_quality_evaluation": "not_performed",
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
run_exit=$?
(
    cd "$run_dir" && shopt -s nullglob && sha256sum ./*.json ./*.jsonl ./*.log > SHA256SUMS
) || exit 2
printf 'EVIDENCE_DIR=%s\nTASK_ID=%s\nRUNTIME_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$task_id" "$runtime_dir" "$run_exit"
exit "$run_exit"
