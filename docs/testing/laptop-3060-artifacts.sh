#!/usr/bin/env bash
# Independent artifact audit or a new-process offline reload, using existing CLIs.
set -uo pipefail
mode="${1:-}"
if [[ "$mode" != audit && "$mode" != reload && "$mode" != --check ]]; then
    echo "Usage: bash laptop-3060-artifacts.sh audit|reload|--check TASK_UUID" >&2; exit 2
fi
[[ $# -eq 2 ]] || exit 2
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
if [[ -z "$uv_bin" || ! -x .venv/bin/python ]]; then echo "Project environment missing." >&2; exit 2; fi
task_id="$(.venv/bin/python -c 'from uuid import UUID; import sys; print(UUID(sys.argv[1]))' "$2")" || exit 2
runtime_dir="$PWD/data/local-validation/laptop-3060/$task_id"
data_dir="$runtime_dir/data"
manifest_path="$data_dir/outputs/$task_id/manifest.json"
hf_home="$PWD/data/models/huggingface"
cache_dir="$hf_home/hub"
parent="$report_repo/data/acceptance/b-review/laptop-3060"
revision=7ae557604adf67be50417f59c2c2f167def9a775
if [[ ! -f "$manifest_path" ]]; then echo "Training manifest missing: $manifest_path" >&2; exit 2; fi
if [[ "$mode" == --check ]]; then
    printf 'READY: repo=%s\nTASK_ID=%s\nRUNTIME_DIR=%s\nRESULTS_PARENT=%s\n' "$PWD" "$task_id" "$runtime_dir" "$parent"
    sha256sum "$manifest_path"
    exit $?
fi
export TMPDIR=/tmp HF_HOME="$hf_home" HF_HUB_CACHE="$cache_dir" HF_XET_CACHE="$hf_home/xet"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
prompt='请给出一个整理书桌的小建议。'
if [[ "$mode" == audit ]]; then
    export CUDA_VISIBLE_DEVICES=""
    args=(python scripts/check_training_artifacts.py --task-id "$task_id" --data-dir "$data_dir" --revision "$revision")
    expected=artifacts_verified
else
    export CUDA_VISIBLE_DEVICES=0
    args=(python scripts/reload_adapter.py --task-id "$task_id" --data-dir "$data_dir" \
        --cache-dir "$cache_dir" --revision "$revision" --prompt "$prompt" --max-new-tokens 32)
    expected=reload_verified
fi
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-$mode-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\nTASK_ID=%s\nRUNTIME_DIR=%s\n' "$run_dir" "$task_id" "$runtime_dir"

.venv/bin/python - "$0" "$uv_bin" "$mode" "$task_id" "$runtime_dir" "$manifest_path" "$prompt" > "$run_dir/metadata.json" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import distributions
import json
from pathlib import Path
import platform
import subprocess
import sys

def output(*args):
    return subprocess.check_output(args, text=True).strip()

runner = Path(sys.argv[1]).resolve()
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
    "stage": sys.argv[3], "task_id": sys.argv[4], "runtime_dir": sys.argv[5],
    "manifest_sha256_before": sha256(Path(sys.argv[6]).read_bytes()).hexdigest(),
    "prompt_sha256": sha256(sys.argv[7].encode()).hexdigest() if sys.argv[3] == "reload" else None,
    "max_new_tokens": 32 if sys.argv[3] == "reload" else None,
    "real_training": False, "model_quality_evaluation": "not_performed",
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo "Metadata failed; audit/reload not started." >&2; exit 2; fi

"$uv_bin" run --offline --locked --extra training "${args[@]}" 2>&1 | tee "$run_dir/command.log"
codes=("${PIPESTATUS[@]}")
.venv/bin/python - "$run_dir" "$mode" "$expected" "$task_id" "$manifest_path" "${codes[0]}" "${codes[1]}" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
decoder = json.JSONDecoder()
text = (root / "command.log").read_text(errors="replace")
result = None
for match in re.finditer(r"(?m)^\{", text):
    try:
        candidate, _ = decoder.raw_decode(text[match.start():])
    except ValueError:
        continue
    if isinstance(candidate, dict) and ("status" in candidate or "code" in candidate):
        result = candidate
if result is not None:
    (root / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
metadata = json.loads((root / "metadata.json").read_text())
manifest = Path(sys.argv[5])
after = sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
passed = (sys.argv[6] == sys.argv[7] == "0" and result is not None
          and result.get("status") == sys.argv[3] and result.get("task_id") == sys.argv[4]
          and after == metadata["manifest_sha256_before"])
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": sys.argv[2],
    "status": "passed" if passed else "failed_or_incomplete", "task_id": sys.argv[4],
    "command_exit_code": int(sys.argv[6]), "log_exit_code": int(sys.argv[7]),
    "manifest_unchanged": after == metadata["manifest_sha256_before"], "manifest_sha256": after,
    "evidence_dir": str(root), "artifact_result": result,
    "real_training": False, "model_quality_evaluation": "not_performed",
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
run_exit=$?
(
    cd "$run_dir" && sha256sum metadata.json command.log summary.json > SHA256SUMS &&
    { [[ ! -f result.json ]] || sha256sum result.json >> SHA256SUMS; }
) || exit 2
printf 'EVIDENCE_DIR=%s\nTASK_ID=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$task_id" "$run_exit"
exit "$run_exit"
