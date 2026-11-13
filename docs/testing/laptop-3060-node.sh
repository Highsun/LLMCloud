#!/usr/bin/env bash
# Install the repository-pinned Linux Node in the E-backed Ubuntu user directory.
set -uo pipefail
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --check ) ]]; then exit 2; fi
runner_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)" || exit 2
report_repo="$(cd -- "$runner_dir/../.." && pwd -P)" || exit 2
report_repo="${LLMCLOUD_REPORT_REPO:-$report_repo}"
[[ -d "$report_repo" ]] || { echo "Report repository must already exist." >&2; exit 2; }
cd "${LLMCLOUD_TEST_REPO:-$HOME/LLMCloud}" || exit 2
version="$(tr -d '\r\n' < frontend/.node-version)"
if [[ "$version" != 22.23.3 || "$(uname -m)" != x86_64 ]]; then
    echo 'This installer is pinned to Node 22.23.3 on Linux x86_64.' >&2; exit 2
fi
expected=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de
filename="node-v$version-linux-x64.tar.xz"
tools="$HOME/.local/share/llmcloud-tools"
install_dir="$tools/node-v$version-linux-x64"
cache="$HOME/.cache/llmcloud/node"
archive="$cache/$filename"
url="https://npmmirror.com/mirrors/node/v$version/$filename"
parent="$report_repo/data/acceptance/b-review/laptop-3060"
for tool in curl tar sha256sum; do command -v "$tool" >/dev/null || exit 2; done
[[ -x .venv/bin/python ]] || exit 2
if [[ "${1:-}" == --check ]]; then
    printf 'READY: Node=%s\nINSTALL_DIR=%s\nDOWNLOAD_CACHE=%s\nRESULTS_PARENT=%s\n' "$version" "$install_dir" "$cache" "$parent"
    exit 0
fi
mkdir -p "$parent" || exit 2
run_dir="$(mktemp -d "$parent/$(date -u +%Y%m%dT%H%M%SZ)-node-install-XXXXXX")" || exit 2
printf 'EVIDENCE_DIR=%s\n' "$run_dir"
run_install() {
    mkdir -p "$tools" "$cache" "$HOME/.local/bin" || return
    if [[ ! -f "$archive" ]]; then
        curl -fL --connect-timeout 10 --max-time 600 --retry 2 --continue-at - \
            "$url" -o "$archive.part" || return
        printf '%s  %s\n' "$expected" "$archive.part" | sha256sum -c - || return
        mv -n -- "$archive.part" "$archive" || return
    fi
    printf '%s  %s\n' "$expected" "$archive" | sha256sum -c - || return
    if [[ ! -e "$install_dir" ]]; then
        tar -xJf "$archive" -C "$tools" || return
    fi
    [[ -x "$install_dir/bin/node" ]] || return 1
    [[ "$("$install_dir/bin/node" --version)" == "v$version" ]] || return 1
    for name in node npm npx; do
        link="$HOME/.local/bin/$name"
        if [[ -e "$link" || -L "$link" ]]; then
            if [[ ! -L "$link" || "$(readlink "$link")" != "$install_dir/bin/$name" ]]; then
                echo "Existing user tool preserved; inspect $link before proceeding." >&2; return 1
            fi
        fi
    done
    for name in node npm npx; do
        link="$HOME/.local/bin/$name"
        if [[ ! -L "$link" ]]; then ln -s "$install_dir/bin/$name" "$link" || return; fi
    done
    export PATH="$install_dir/bin:$PATH"
    node --version || return
    npm --version || return
    node -p 'process.platform + " " + process.arch + " " + process.execPath' || return
}
run_install 2>&1 | tee "$run_dir/command.log"
codes=("${PIPESTATUS[@]}")
.venv/bin/python - "$run_dir" "$install_dir" "$0" "${codes[0]}" "${codes[1]}" "$expected" "$archive" <<'PY'
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys

root, install, runner = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).resolve()
env = {**os.environ, "PATH": str(install / "bin") + os.pathsep + os.environ.get("PATH", "")}
def output(*args):
    return subprocess.check_output(args, text=True, env=env).strip()
versions = {}
if sys.argv[4] == sys.argv[5] == "0":
    versions = {"node": output(str(install / "bin/node"), "--version"),
                "npm": output(str(install / "bin/npm"), "--version"),
                "platform": output(str(install / "bin/node"), "-p", "process.platform"),
                "exec_path": output(str(install / "bin/node"), "-p", "process.execPath")}
passed = sys.argv[4] == sys.argv[5] == "0" and versions.get("node") == "v22.23.3" and versions.get("platform") == "linux"
summary = {"finished_at_utc": datetime.now(timezone.utc).isoformat(), "stage": "linux_node_install",
           "status": "passed" if passed else "failed_or_incomplete",
           "command_exit_code": int(sys.argv[4]), "log_exit_code": int(sys.argv[5]),
           "runner_sha256": sha256(runner.read_bytes()).hexdigest(),
           "code_commit": output("git", "rev-parse", "HEAD"),
           "install_dir": str(install), "download_archive": sys.argv[7],
           "archive_expected_sha256": sys.argv[6], "versions": versions,
           "evidence_dir": str(root)}
(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print("\nRETURN_TO_CODEX_BEGIN")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("RETURN_TO_CODEX_END")
sys.exit(0 if passed else 1)
PY
run_exit=$?
(cd "$run_dir" && sha256sum command.log summary.json > SHA256SUMS) || exit 2
printf 'EVIDENCE_DIR=%s\nRUN_EXIT_CODE=%s\n' "$run_dir" "$run_exit"
exit "$run_exit"
