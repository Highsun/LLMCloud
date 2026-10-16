#!/usr/bin/env bash
# Run explicitly in WSL: sudo bash scripts/setup_docker.sh
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo "需要系统安装权限，请运行：sudo bash scripts/setup_docker.sh" >&2
  exit 1
fi
source /etc/os-release
if [[ "$ID" != ubuntu ]]; then
  echo "此脚本用于 Ubuntu；其他发行版请参阅 Docker 官方安装文档。" >&2
  exit 1
fi
for package in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
  if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" == 'install ok installed' ]]; then
    echo "检测到已有 $package，请先确认现有容器环境的迁移方式。" >&2
    exit 1
  fi
done
apt-get update
apt-get install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl --fail --silent --show-error https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
docker version
docker compose version
docker run --rm hello-world
echo 'Docker 已验证。当前使用 sudo docker 执行容器命令。'
