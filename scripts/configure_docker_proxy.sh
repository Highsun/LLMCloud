#!/usr/bin/env bash
# Example: sudo bash scripts/configure_docker_proxy.sh http://172.24.224.1:7897
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "需要 sudo；用法：sudo bash scripts/configure_docker_proxy.sh http://HOST:PORT" >&2
  exit 1
fi
proxy_url=${1:?请提供本机 HTTP 代理地址，例如 http://172.24.224.1:7897}
python3 - "$proxy_url" <<'PY'
from pathlib import Path
import sys
from urllib.parse import urlsplit

proxy = sys.argv[1]
parsed = urlsplit(proxy)
if (
    parsed.scheme not in ('http', 'https') or not parsed.hostname or not parsed.port
    or parsed.username or parsed.password or parsed.path not in ('', '/')
    or parsed.query or parsed.fragment or any(c in proxy for c in ('"', '\n', '\r', '%'))
):
    raise SystemExit('请提供不含凭据的 http(s)://HOST:PORT 地址。')
directory = Path('/etc/systemd/system/docker.service.d')
directory.mkdir(parents=True, exist_ok=True)
(directory / 'llmcloud-proxy.conf').write_text(
    '[Service]\n'
    f'Environment="HTTP_PROXY={proxy}"\n'
    f'Environment="HTTPS_PROXY={proxy}"\n'
    'Environment="NO_PROXY=localhost,127.0.0.1,::1"\n'
)
PY
systemctl daemon-reload
systemctl restart docker
docker run --rm hello-world
