#!/usr/bin/env bash
# Stage L2: prepare/check a pinned model; GPU forward is an explicit separate mode.
set -uo pipefail

mode="${1:-}"
case "$mode" in
    prepare|check|gpu|--check) ;;
    *) echo "Usage: bash laptop-3060-model.sh prepare|check|gpu|--check" >&2; exit 2 ;;
esac
[[ $# -eq 1 ]] || exit 2
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
if [[ -z "$uv_bin" || ! -x .venv/bin/python || ! -f scripts/prepare_model.py ]]; then
    echo "Missing uv, project environment, or model preparation tool." >&2
    exit 2
fi
revision=7ae557604adf67be50417f59c2c2f167def9a775
data_dir="$PWD/data"
hf_home="$data_dir/models/huggingface"
cache_dir="$hf_home/hub"
endpoint="${LLMCLOUD_HF_ENDPOINT:-https://hf-mirror.com}"
parent="$report_repo/data/acceptance/b-review/laptop-3060"
if [[ "$mode" == "--check" ]]; then
    printf 'READY: repo=%s\nMODEL_CACHE=%s\nRESULTS_PARENT=%s\nENDPOINT=%s\n' "$PWD" "$cache_dir" "$parent" "$endpoint"
    exit 0
fi

export TMPDIR=/tmp
export CUDA_VISIBLE_DEVICES=0
export HF_ENDPOINT="$endpoint"
export HF_HUB_DISABLE_XET=1
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_DOWNLOAD_TIMEOUT=60
export HF_HOME="$hf_home"
export HF_HUB_CACHE="$cache_dir"
export HF_XET_CACHE="$hf_home/xet"
if [[ "$mode" == "prepare" ]]; then
    export HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0
    args=(prepare)
    expected=cache_verified
else
    export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
    args=(check)
    expected=cache_verified
    if [[ "$mode" == "gpu" ]]; then
        args+=(--gpu --precision bf16)
        expected=gpu_forward_verified
    fi
fi
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-model-$mode-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\nMODEL_CACHE=%s\n' "$run_dir" "$cache_dir"

.venv/bin/python - "$0" "$uv_bin" "$mode" "$endpoint" "$cache_dir" > "$run_dir/metadata.json" <<'PY'
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
    "python": sys.version, "platform": platform.platform(),
    "uv": output(sys.argv[2], "--version"), "stage": sys.argv[3],
    "download_endpoint": sys.argv[4], "cache_dir": sys.argv[5],
    "model_revision": "7ae557604adf67be50417f59c2c2f167def9a775",
    "packages": dict(sorted((d.metadata["Name"], d.version)
                            for d in distributions() if d.metadata["Name"])),
    "real_training": False,
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo "Metadata collection failed; no model operation started." >&2; exit 2; fi

"$uv_bin" run --offline --locked --extra training python scripts/prepare_model.py \
    "${args[@]}" --revision "$revision" --data-dir "$data_dir" \
    --hf-home "$hf_home" --cache-dir "$cache_dir" 2>&1 | tee "$run_dir/command.log"
codes=("${PIPESTATUS[@]}")
.venv/bin/python - "$run_dir" "$mode" "$expected" "${codes[0]}" "${codes[1]}" <<'PY'
from datetime import datetime, timezone
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
passed = sys.argv[4] == "0" and sys.argv[5] == "0" and result is not None and result.get("status") == sys.argv[3]
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "stage": sys.argv[2], "status": "passed" if passed else "failed_or_incomplete",
    "command_exit_code": int(sys.argv[4]), "log_exit_code": int(sys.argv[5]),
    "evidence_dir": str(root), "model_result": result,
    "real_training": False,
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
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$run_exit"
exit "$run_exit"
