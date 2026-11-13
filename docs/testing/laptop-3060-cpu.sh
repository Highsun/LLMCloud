#!/usr/bin/env bash
# Collect evidence for existing CPU tests; no model download or real training.
set -uo pipefail

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--check" ) ]]; then
    echo "Usage: bash laptop-3060-cpu.sh [--check]" >&2
    exit 2
fi

runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
repo="${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}"
cd "$repo" || exit 2
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then
    uv_bin="$HOME/.local/bin/uv"
fi
if [[ -z "$uv_bin" || ! -x .venv/bin/python || ! -f uv.lock || ! -d tests ]]; then
    echo "Missing uv, project .venv, uv.lock, or tests; no tests started." >&2
    exit 2
fi
if [[ "${1:-}" == "--check" ]]; then
    printf 'READY: repo=%s\n' "$PWD"
    printf 'RESULTS_PARENT=%s/data/acceptance/b-review/laptop-3060\n' "$report_repo"
    printf 'RUNTIME_TMPDIR=/tmp (Ubuntu filesystem)\n'
    "$uv_bin" --version
    .venv/bin/python --version
    exit 0
fi

# Keep this stage independent of GPU, remote model services, and opt-in browsers.
export CUDA_VISIBLE_DEVICES=""
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export UV_OFFLINE=1
export LLMCLOUD_M4_TOOL_BROWSER_TEST=0
export TMPDIR=/tmp

parent="$report_repo/data/acceptance/b-review/laptop-3060"
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-cpu-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\n' "$run_dir"

.venv/bin/python - "$0" "$uv_bin" > "$run_dir/metadata.json" <<'PY'
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
    "repo": str(Path.cwd()),
    "code_commit": output("git", "rev-parse", "HEAD"),
    "working_tree_dirty": bool(status),
    "git_status_porcelain": status,
    "uv_lock_sha256": sha256(Path("uv.lock").read_bytes()).hexdigest(),
    "pyproject_sha256": sha256(Path("pyproject.toml").read_bytes()).hexdigest(),
    "runner_path": str(runner),
    "runner_sha256": sha256(runner.read_bytes()).hexdigest(),
    "python": sys.version,
    "python_executable": sys.executable,
    "platform": platform.platform(),
    "uv": output(sys.argv[2], "--version"),
    "packages": dict(sorted((d.metadata["Name"], d.version)
                            for d in distributions() if d.metadata["Name"])),
    "scope": "CPU automated regression and five contract drift checks",
    "runtime_temp_dir": "/tmp (Ubuntu filesystem)",
    "gpu_devices_visible_to_tests": "",
    "model_network_access": "disabled",
    "optional_m4_browser_test": "disabled; report its skip rather than passing it",
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then
    echo "Metadata collection failed; evidence directory retained." >&2
    exit 2
fi

printf 'check\texit_code\tlog_exit_code\n' > "$run_dir/results.tsv" || exit 2
failed=0
run_check() {
    local name="$1"
    shift
    printf '\nCHECK=%s\n' "$name"
    "$uv_bin" run --offline --locked --extra training "$@" 2>&1 | tee "$run_dir/$name.log"
    local codes=("${PIPESTATUS[@]}")
    printf '%s\t%s\t%s\n' "$name" "${codes[0]}" "${codes[1]}" >> "$run_dir/results.tsv" || exit 2
    printf 'CHECK_EXIT=%s:%s LOG_EXIT=%s\n' "$name" "${codes[0]}" "${codes[1]}"
    if [[ "${codes[0]}" -ne 0 || "${codes[1]}" -ne 0 ]]; then
        failed=1
    fi
}

run_check cpu-tests python -m unittest discover -s tests -v
run_check dataset-contract python scripts/export_dataset_contract.py --check
run_check training-contract python scripts/export_training_contract.py --check
run_check task-contract python scripts/export_task_contract.py --check
run_check task-openapi python scripts/export_task_openapi.py --check
run_check observability-contract python scripts/export_observability_contract.py --check

.venv/bin/python - "$run_dir" <<'PY'
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
with (root / "results.tsv").open() as stream:
    results = list(csv.DictReader(stream, delimiter="\t"))
text = (root / "cpu-tests.log").read_text(errors="replace")
ran = re.search(r"Ran (\d+) tests? in ([\d.]+)s", text)
skips = [line for line in text.splitlines() if " ... skipped " in line]
passed = len(results) == 6 and ran is not None and all(
    row["exit_code"] == "0" and row["log_exit_code"] == "0" for row in results)
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    "status": "passed" if passed else "failed_or_incomplete",
    "checks": results,
    "unittest_count": int(ran[1]) if ran else None,
    "unittest_elapsed_seconds": float(ran[2]) if ran else None,
    "skipped_test_details": skips,
    "evidence_dir": str(root),
    "not_performed": ["real model loading", "real LoRA training", "adapter reload",
                      "real Redis/Worker/browser integration", "joint M3/M4 acceptance",
                      "cloud deployment", "model quality evaluation"],
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
summary_exit=$?
if [[ "$summary_exit" -ne 0 ]]; then
    failed=1
fi
(
    cd "$run_dir" && sha256sum metadata.json results.tsv ./*.log summary.json > SHA256SUMS
) || exit 2
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$failed"
exit "$failed"
