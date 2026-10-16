"""Inspect the development environment without changing configuration.

Run: uv run --locked python scripts/check_environment.py
Add --gpu to execute a CUDA forward/backward check (requires training extra).
"""

import argparse
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def check(label: str, success: bool, detail: str) -> bool:
    print(f"[{'OK' if success else 'MISSING'}] {label}: {detail}", flush=True)
    return success


def command_version(command: list[str]) -> tuple[bool, str]:
    if not shutil.which(command[0]):
        return False, "未安装或不在 PATH"
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        output = (result.stdout.strip() or result.stderr.strip()).splitlines()
        return result.returncode == 0, output[0] if output else f"exit={result.returncode}"
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description="LLMCloud 开发环境检查")
    parser.add_argument("--gpu", action="store_true", help="执行实际 GPU 前向/反向运算")
    args = parser.parse_args()
    ready = check("Python", sys.version_info[:2] in ((3, 11), (3, 12)), sys.version.split()[0])
    for label, command in (
        ("uv", ["uv", "--version"]),
        ("Git", ["git", "--version"]),
        ("Node.js", ["node", "--version"]),
        ("npm", ["npm", "--version"]),
        ("Redis server", ["redis-server", "--version"]),
        ("Docker CLI", ["docker", "--version"]),
        ("Docker Compose", ["docker", "compose", "version"]),
    ):
        success, detail = command_version(command)
        ready = check(label, success, detail) and ready
    success, detail = command_version(["docker", "info", "--format", "{{.ServerVersion}}"])
    if not success and shutil.which("docker"):
        service_active, _ = command_version(["systemctl", "is-active", "docker"])
        if service_active:
            success = True
            detail = "systemd 服务 active；当前用户访问 API 需要 sudo，容器运行请用 sudo docker 验证"
    ready = check("Docker Engine", success, detail) and ready
    for package in (
        "fastapi", "uvicorn", "sqlalchemy", "celery", "redis", "torch",
        "transformers", "datasets", "peft", "trl", "accelerate",
    ):
        try:
            version = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            ready = check(package, False, "未安装") and ready
        else:
            check(package, True, version)
    for relative_path in (".env", "frontend/.env", "frontend/node_modules"):
        ready = check(relative_path, (PROJECT_ROOT / relative_path).exists(), relative_path) and ready

    from backend.app.core.config import get_settings
    from redis import Redis

    settings = get_settings()
    try:
        client = Redis.from_url(settings.redis_url, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
        client.close()
        check("Redis 连接", True, "PING -> PONG")
    except Exception as error:
        # Do not print URLs/exceptions that could include connection credentials.
        ready = check("Redis 连接", False, type(error).__name__) and ready
    if args.gpu:
        # Ensure CUDA_VISIBLE_DEVICES follows the project configuration.
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env", override=False)
        result = subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts/check_gpu.py")])
        ready = check("GPU 实际运算", result.returncode == 0, f"exit={result.returncode}") and ready
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
