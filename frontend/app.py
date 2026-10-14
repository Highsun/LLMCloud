"""Compatibility launcher. The frontend itself is Vue3, not a Python web app."""

import shutil
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    if not shutil.which("npm"):
        sys.exit("请先安装 Node.js 22.18+ 和 npm，再执行 cd frontend && npm install。")
    raise SystemExit(
        subprocess.call(["npm", "run", "dev"], cwd=Path(__file__).resolve().parent)
    )
