#!/usr/bin/env bash
# Existing TCP/HTTP and private Redis/production Worker CPU smoke checks.
set -uo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then exit 2; fi
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
uv_bin="$(command -v uv || true)"
if [[ -z "$uv_bin" && -x "$HOME/.local/bin/uv" ]]; then uv_bin="$HOME/.local/bin/uv"; fi
if [[ -z "$uv_bin" || ! -x .venv/bin/python ]]; then exit 2; fi
for tool in redis-server redis-cli; do command -v "$tool" >/dev/null || exit 2; done
parent="$report_repo/data/acceptance/b-review/laptop-3060"
if [[ "${1:-}" == --check ]]; then
    printf 'READY: repo=%s\nRESULTS_PARENT=%s\nTEMP_DATA=/tmp (Ubuntu filesystem)\n' "$PWD" "$parent"
    redis-server --version
    redis-cli --version
    exit $?
fi
export TMPDIR=/tmp CUDA_VISIBLE_DEVICES="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export LLMCLOUD_M4_TOOL_BROWSER_TEST=0
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-http-redis-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\n' "$run_dir"
.venv/bin/python - "$0" "$uv_bin" > "$run_dir/metadata.json" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
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
    "runner_sha256": sha256(runner.read_bytes()).hexdigest(),
    "python": sys.version, "platform": platform.platform(), "uv": output(sys.argv[2], "--version"),
    "redis_server": output("redis-server", "--version"), "redis_cli": output("redis-cli", "--version"),
    "temporary_data": "/tmp (E-backed Ubuntu)", "gpu_visible": "",
    "scope": "existing isolated TCP/HTTP checks and real private Redis + production Worker CPU consumption",
    "real_training": False, "browser_checks": "not_run",
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo 'Metadata failed; no service checks started.' >&2; exit 2; fi
printf 'check\texit_code\tlog_exit_code\n' > "$run_dir/results.tsv" || exit 2
run_check() {
    local name="$1"
    local script="$2"
    printf '\nCHECK=%s\n' "$name"
    "$uv_bin" run --offline --locked --extra training python "$script" 2>&1 | tee "$run_dir/$name.log"
    local codes=("${PIPESTATUS[@]}")
    printf '%s\t%s\t%s\n' "$name" "${codes[0]}" "${codes[1]}" >> "$run_dir/results.tsv" || exit 2
    printf 'CHECK_EXIT=%s:%s LOG_EXIT=%s\n' "$name" "${codes[0]}" "${codes[1]}"
}
run_check dataset-http scripts/check_dataset_http.py
run_check observability-http scripts/check_task_observability.py
run_check download-http scripts/check_task_download.py
run_check redis-worker-cpu scripts/check_worker_dispatch.py
.venv/bin/python - "$run_dir" <<'PY'
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
with (root / "results.tsv").open() as stream:
    checks = list(csv.DictReader(stream, delimiter="\t"))
decoder = json.JSONDecoder()
for item in checks:
    text = (root / f"{item['check']}.log").read_text(errors="replace")
    item["result"] = None
    for match in re.finditer(r"(?m)^\{", text):
        try:
            result, _ = decoder.raw_decode(text[match.start():])
        except ValueError:
            continue
        if isinstance(result, dict) and result.get("status") == "ok":
            item["result"] = result
passed = len(checks) == 4 and all(x["exit_code"] == x["log_exit_code"] == "0" and x["result"] is not None for x in checks)
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "isolated_http_redis_cpu",
    "status": "passed" if passed else "failed_or_incomplete", "checks": checks,
    "evidence_dir": str(root), "real_training": False, "browser_checks": "not_run",
    "scope_note": "Controlled CPU metrics/synthetic bundle; Worker deliberately uses empty isolated cache. Not GPU or joint acceptance.",
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
run_exit=$?
(cd "$run_dir" && sha256sum metadata.json summary.json results.tsv ./*.log > SHA256SUMS) || exit 2
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$run_exit"
exit "$run_exit"
