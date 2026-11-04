"""Serve real persisted M3 task records from a disposable copy, with writes blocked.

This is a CPU review harness, not a training server. Original evidence is read-only.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import uvicorn
from starlette.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.core.config import Settings
from backend.app.main import create_app


class ReadOnlyReview:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
            response = JSONResponse({"error": {"code": "READ_ONLY_REVIEW", "message": "既有任务复核环境禁止写入。"}}, status_code=405)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True, help="New directory under data/acceptance; never an evidence source")
    parser.add_argument("--port", type=int, default=18007)
    args = parser.parse_args()
    source = args.source_run.resolve(strict=True)
    work = args.work_dir.resolve()
    if not work.is_relative_to((ROOT / "data/acceptance").resolve()) or work.is_relative_to(source):
        parser.error("Work directory must be separate from source evidence and inside data/acceptance")
    if work.exists():
        parser.error("Work directory must not exist; refusing overwrite")
    database = source / "data/llmcloud.db"
    if not database.is_file():
        parser.error("Evidence database snapshot is missing")
    work.mkdir(parents=True, exist_ok=False)
    (work / "data").mkdir()
    shutil.copy2(database, work / "data/llmcloud.db")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", CUDA_VISIBLE_DEVICES="")
    settings = Settings(_env_file=None, data_dir=work / "data", log_dir=work / "logs", database_url="",
        redis_url="redis://127.0.0.1:1/0", celery_result_backend="cache+memory://")
    app = create_app(settings)
    app.add_middleware(ReadOnlyReview)
    print(json.dumps({"mode": "persisted_sql_cpu_review", "writes": "blocked", "gpu_started": False,
        "url": f"http://127.0.0.1:{args.port}"}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
