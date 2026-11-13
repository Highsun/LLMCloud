#!/usr/bin/env bash
# Install the locked Playwright Chromium and run the existing browser preflight.
set -uo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then exit 2; fi
runner="$(realpath -- "${BASH_SOURCE[0]}")" || exit 2
report_repo="$(cd -- "$(dirname -- "$runner")/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
repo="$PWD"
python_bin="$repo/.venv/bin/python"
version="$(tr -d '\r\n' < frontend/.node-version)"
export PATH="$HOME/.local/share/llmcloud-tools/node-v$version-linux-x64/bin:$HOME/.local/bin:$PATH"
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
export PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=120000
export npm_config_cache="$HOME/.cache/llmcloud/npm"
export TMPDIR=/tmp HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 CUDA_VISIBLE_DEVICES=""
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
uv_bin="$(command -v uv || true)"
cli="$repo/frontend/node_modules/playwright/cli.js"
if [[ ! -x "$python_bin" || -z "$uv_bin" || ! -f "$cli" || "$(node --version)" != "v$version" || "$(node -p process.platform)" != linux ]]; then
    echo 'Expected existing Linux Python, pinned Node, uv and locked Playwright dependencies.' >&2; exit 2
fi
parent="$report_repo/data/acceptance/b-review/laptop-3060"
if [[ "${1:-}" == --check ]]; then
    printf 'READY: repo=%s\nBROWSER_CACHE=%s\nTEMP_DATA=/tmp (E-backed Ubuntu)\nRESULTS_PARENT=%s\n' "$repo" "$PLAYWRIGHT_BROWSERS_PATH" "$parent"
    node "$cli" --version
    exit $?
fi
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-browser-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\n' "$run_dir"
"$python_bin" - "$runner" "$cli" > "$run_dir/metadata.json" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

def output(*args):
    return subprocess.check_output(args, text=True).strip()

status = output("git", "status", "--porcelain")
print(json.dumps({
    "started_at_utc": datetime.now(timezone.utc).isoformat(),
    "repo": str(Path.cwd()), "code_commit": output("git", "rev-parse", "HEAD"),
    "working_tree_dirty": bool(status), "git_status_porcelain": status,
    "runner_sha256": sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),
    "package_json_sha256": sha256(Path("frontend/package.json").read_bytes()).hexdigest(),
    "package_lock_sha256": sha256(Path("frontend/package-lock.json").read_bytes()).hexdigest(),
    "uv_lock_sha256": sha256(Path("uv.lock").read_bytes()).hexdigest(),
    "node": output("node", "--version"), "playwright": output("node", sys.argv[2], "--version"),
    "browser_cache": os.environ["PLAYWRIGHT_BROWSERS_PATH"],
    "installation": "locked local Playwright CLI: install --with-deps chromium; default vendor download source",
    "real_training": False, "services_started": False,
}, ensure_ascii=False, indent=2))
PY
if [[ $? -ne 0 ]]; then echo 'Metadata failed; browser installation not started.' >&2; exit 2; fi
cp -- "$runner" "$run_dir/runner-used.sh" || exit 2
printf 'Installing Chromium and Ubuntu libraries; sudo may ask for the Ubuntu password.\n'
node "$cli" install --with-deps chromium 2>&1 | tee "$run_dir/install.log"
codes=("${PIPESTATUS[@]}")
install_exit="${codes[0]}"; install_log_exit="${codes[1]}"
check_exit=not_run; check_log_exit=not_run
if [[ "$install_exit" == 0 && "$install_log_exit" == 0 ]]; then
    "$uv_bin" run --offline --locked --extra training python scripts/check_m4_acceptance.py --check 2>&1 | tee "$run_dir/preflight.log"
    codes=("${PIPESTATUS[@]}")
    check_exit="${codes[0]}"; check_log_exit="${codes[1]}"
fi
"$python_bin" - "$run_dir" "$install_exit" "$install_log_exit" "$check_exit" "$check_log_exit" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
metadata = json.loads((root / "metadata.json").read_text())
unchanged = all(sha256(Path(path).read_bytes()).hexdigest() == metadata[key] for path, key in (
    ("frontend/package.json", "package_json_sha256"), ("frontend/package-lock.json", "package_lock_sha256"),
    ("uv.lock", "uv_lock_sha256")))
reports = []
log = root / "preflight.log"
if log.exists():
    for line in log.read_text(errors="replace").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            reports.append(item)
browser_ok = any(x.get("status") == "browser_preflight_passed" and x.get("gpu_started") is False for x in reports)
tool_ok = any(x.get("status") == "preflight_passed" and x.get("services_started") is False
              and x.get("training_packages_available") is True for x in reports)
passed = all(x == "0" for x in sys.argv[2:6]) and unchanged and browser_ok and tool_ok
summary = {
    "finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "chromium_install_and_preflight",
    "status": "passed" if passed else "failed_or_incomplete",
    "install_exit_code": sys.argv[2], "install_log_exit_code": sys.argv[3],
    "preflight_exit_code": sys.argv[4], "preflight_log_exit_code": sys.argv[5],
    "dependency_files_unchanged": unchanged, "reports": reports,
    "browser_cache": metadata["browser_cache"], "evidence_dir": str(root),
    "real_training": False, "services_started": False,
    "platform_browser_checks": "not_run", "joint_human_acceptance": "pending",
}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
run_exit=$?
(cd "$run_dir" && sha256sum metadata.json summary.json runner-used.sh ./*.log > SHA256SUMS) || exit 2
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$run_exit"
exit "$run_exit"
