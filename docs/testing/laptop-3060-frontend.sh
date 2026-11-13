#!/usr/bin/env bash
# Install locked frontend dependencies, run existing Node tests, and build.
set -uo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then exit 2; fi
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
repo="$PWD"
python_bin="$repo/.venv/bin/python"
version="$(tr -d '\r\n' < frontend/.node-version)"
node_dir="$HOME/.local/share/llmcloud-tools/node-v$version-linux-x64"
export PATH="$node_dir/bin:$HOME/.local/bin:$PATH"
if [[ ! -x "$python_bin" || "$(node --version)" != "v$version" || "$(node -p process.platform)" != linux ]]; then
    echo 'Expected the project-pinned Linux Node and Python environment.' >&2; exit 2
fi
registry=https://registry.npmmirror.com
parent="$report_repo/data/acceptance/b-review/laptop-3060"
export npm_config_cache="$HOME/.cache/llmcloud/npm"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
if [[ "${1:-}" == --check ]]; then
    printf 'READY: frontend=%s/frontend\nNODE=%s\nNPM_CACHE=%s\nREGISTRY=%s\nRESULTS_PARENT=%s\n' "$repo" "$(command -v node)" "$npm_config_cache" "$registry" "$parent"
    npm --version
    exit $?
fi
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-frontend-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\n' "$run_dir"
"$python_bin" - "$0" "$registry" > "$run_dir/metadata.json" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
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
    "runner_sha256": sha256(runner.read_bytes()).hexdigest(),
    "package_json_sha256": sha256(Path("frontend/package.json").read_bytes()).hexdigest(),
    "package_lock_sha256": sha256(Path("frontend/package-lock.json").read_bytes()).hexdigest(),
    "node": output("node", "--version"), "npm": output("npm", "--version"),
    "node_exec_path": output("node", "-p", "process.execPath"), "registry": sys.argv[2],
    "browser_checks": "not_run", "real_training": False,
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo 'Metadata failed; frontend checks not started.' >&2; exit 2; fi
cd "$repo/frontend" || exit 2
run_logged() {
    local name="$1"
    shift
    "$@" 2>&1 | tee "$run_dir/$name.log"
    local codes=("${PIPESTATUS[@]}")
    command_exit="${codes[0]}"
    log_exit="${codes[1]}"
    printf 'CHECK_EXIT=%s:%s LOG_EXIT=%s\n' "$name" "$command_exit" "$log_exit"
}
run_logged install npm ci --include=dev --registry "$registry" --no-audit --no-fund --loglevel=info
install_exit="$command_exit"; install_log_exit="$log_exit"
test_exit=not_run; test_log_exit=not_run; build_exit=not_run; build_log_exit=not_run
if [[ "$install_exit" -eq 0 && "$install_log_exit" -eq 0 ]]; then
    run_logged tests npm test
    test_exit="$command_exit"; test_log_exit="$log_exit"
    run_logged build npm run build
    build_exit="$command_exit"; build_log_exit="$log_exit"
fi
"$python_bin" - "$run_dir" "$repo" "$install_exit" "$install_log_exit" "$test_exit" "$test_log_exit" "$build_exit" "$build_log_exit" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

root, repo = Path(sys.argv[1]), Path(sys.argv[2])
metadata = json.loads((root / "metadata.json").read_text())
lock_unchanged = sha256((repo / "frontend/package-lock.json").read_bytes()).hexdigest() == metadata["package_lock_sha256"]
package_unchanged = sha256((repo / "frontend/package.json").read_bytes()).hexdigest() == metadata["package_json_sha256"]
text = (root / "tests.log").read_text(errors="replace") if (root / "tests.log").exists() else ""
counts = {}
for name in ("tests", "suites", "pass", "fail", "cancelled", "skipped", "todo"):
    match = re.search(r"(?m)^# " + name + r" (\d+)\s*$", text)
    counts[name] = int(match[1]) if match else None
dist = repo / "frontend/dist"
files = [{"path": str(p.relative_to(dist)), "bytes": p.stat().st_size, "sha256": sha256(p.read_bytes()).hexdigest()}
         for p in sorted(dist.rglob("*")) if p.is_file()] if sys.argv[7] == "0" else []
(root / "build-files.json").write_text(json.dumps(files, ensure_ascii=False, indent=2) + "\n")
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "frontend_tests_and_build",
    "status": "passed" if all(x == "0" for x in sys.argv[3:9]) and lock_unchanged and package_unchanged and (dist / "index.html").is_file() and files else "failed_or_incomplete",
    "install_exit_code": sys.argv[3], "install_log_exit_code": sys.argv[4],
    "tests_exit_code": sys.argv[5], "tests_log_exit_code": sys.argv[6],
    "build_exit_code": sys.argv[7], "build_log_exit_code": sys.argv[8],
    "test_counts": counts, "package_lock_unchanged": lock_unchanged, "package_json_unchanged": package_unchanged,
    "dist_dir": str(dist), "dist_file_count": len(files), "evidence_dir": str(root),
    "browser_checks": "not_run", "real_api_worker_integration": "not_run", "real_training": False,
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if summary["status"] == "passed" else 1)
PY
run_exit=$?
(cd "$run_dir" && shopt -s nullglob && sha256sum ./*.json ./*.log > SHA256SUMS) || exit 2
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$run_exit"
exit "$run_exit"
