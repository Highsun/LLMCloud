#!/usr/bin/env bash
# Existing E-backed private WSL deployment only; does not install or build images.
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo 'Run this helper in the Ubuntu-22.04 root shell; it only controls the project-private daemon.' >&2
  exit 1
fi
runtime_root="${LLMCLOUD_LOCAL_ROOT:-/home/l7/llmcloud-deploy}"
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ "$runtime_root" = /* && "$runtime_root" != / && -f "$runtime_root/compose.env" && -x "$runtime_root/docker-bin/dockerd" ]] || {
  echo 'Missing project-private runtime directory, engine or compose.env.' >&2
  exit 1
}
runtime_root="$(realpath -- "$runtime_root")"
export PATH="$runtime_root/docker-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export DOCKER_HOST="unix://$runtime_root/docker-run/docker.sock"
export DOCKER_CONFIG="$runtime_root/docker-config"
compose=(docker compose --env-file "$runtime_root/compose.env" --project-directory "$repo_root"
  -f "$repo_root/compose.yaml" -f "$repo_root/deploy/compose.smoke.yaml" -f "$repo_root/deploy/compose.wsl-cdi.yaml")

check_daemon() {
  local actual_root
  actual_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)" || return 1
  [[ "$actual_root" == "$runtime_root/docker-data" ]] || {
    echo 'Refusing a daemon whose data-root is not this project directory.' >&2
    return 2
  }
}

assert_idle() {
  python3 - "$runtime_root" <<'PY'
import pathlib, sqlite3, sys
path = pathlib.Path(sys.argv[1]) / 'state/data/llmcloud.db'
if path.exists():
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        busy = 0
        if 'training_tasks' in tables:
            busy += db.execute("SELECT count(*) FROM training_tasks WHERE status IN ('PENDING','QUEUED','RUNNING')").fetchone()[0]
        if 'inference_jobs' in tables:
            busy += db.execute("SELECT count(*) FROM inference_jobs WHERE state IN ('WAITING','RUNNING')").fetchone()[0]
        if busy:
            raise SystemExit('Deployment has active or unresolved work; refusing an automatic restart/stop.')
PY
}

start_daemon() {
  local check_result=0
  check_daemon || check_result=$?
  if [[ "$check_result" -eq 0 ]]; then return; fi
  if [[ "$check_result" -eq 2 ]]; then exit 2; fi
  # Python starts a separate session with all stdio redirected, so closing this
  # tool/terminal does not terminate the daemon. No system service is installed.
  python3 - "$runtime_root" <<'PY'
import os, pathlib, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
pidfile = root / 'docker-run/docker.pid'
if pidfile.exists():
    pid = int(pidfile.read_text().strip())
    proc = pathlib.Path(f'/proc/{pid}/cmdline')
    command = proc.read_bytes() if proc.exists() else b''
    if str(root / 'docker-bin/dockerd').encode() in command:
        raise SystemExit('Project daemon process already exists but is not ready; inspect its log.')
    pidfile.rename(root / f'docker-run/docker.pid.stale-{time.time_ns()}')
log = (root / 'evidence/dockerd-detached.log').open('ab', buffering=0)
args = [str(root / 'docker-bin/dockerd'), '--host', 'unix://' + str(root / 'docker-run/docker.sock'),
        '--data-root', str(root / 'docker-data'), '--exec-root', str(root / 'docker-run/exec'),
        '--pidfile', str(pidfile), '--bip', '172.29.100.1/24',
        '--cdi-spec-dir', str(root / 'nvidia/cdi')]
process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                           start_new_session=True, close_fds=True)
print('Started project-private detached Docker daemon', process.pid)
PY
  for _ in {1..30}; do
    if check_daemon; then return; fi
    sleep 1
  done
  echo 'Project daemon did not become ready; inspect evidence/dockerd-detached.log.' >&2
  exit 1
}

case "${1:-status}" in
  start)
    start_daemon
    "${compose[@]}" up -d --no-build
    "${compose[@]}" ps
    ;;
  restart)
    check_daemon || { echo 'Start the project daemon first.' >&2; exit 1; }
    assert_idle
    "${compose[@]}" restart
    "${compose[@]}" ps
    ;;
  stop)
    check_daemon || { echo 'Project daemon is already stopped.'; exit 0; }
    assert_idle
    "${compose[@]}" stop
    python3 - "$runtime_root" <<'PY'
import os, pathlib, signal, sys
root = pathlib.Path(sys.argv[1])
pid = int((root / 'docker-run/docker.pid').read_text().strip())
command = pathlib.Path(f'/proc/{pid}/cmdline').read_bytes()
if str(root / 'docker-bin/dockerd').encode() not in command or str(root / 'docker-data').encode() not in command:
    raise SystemExit('PID is not the verified project-private daemon; refusing to stop it.')
os.kill(pid, signal.SIGTERM)
print('Stopped verified project-private Docker daemon', pid)
PY
    ;;
  status)
    check_daemon || { echo 'Project daemon is not running.'; exit 1; }
    "${compose[@]}" ps
    ;;
  *) echo 'Usage: bash scripts/local_deployment.sh {start|status|restart|stop}' >&2; exit 2 ;;
esac
