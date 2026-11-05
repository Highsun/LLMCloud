"""Export implemented task HTTP operations from the real application only."""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.task_contract import TASK_CONTRACT_VERSION  # noqa: E402
from backend.app.main import create_app  # noqa: E402


def build_contract():
    runtime = create_app(Settings(_env_file=None, api_prefix="/api/v1")).openapi()
    paths = {path.removeprefix("/api/v1"): value for path, value in runtime["paths"].items()
             if path == "/api/v1/tasks" or path.startswith("/api/v1/tasks/")}
    selected = {}

    def collect(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[1]
                if name not in selected:
                    selected[name] = runtime["components"]["schemas"][name]
                    collect(selected[name])
            for item in value.values(): collect(item)
        elif isinstance(value, list):
            for item in value: collect(item)
    collect(paths)
    return {"openapi": runtime["openapi"],
        "info": {"title": "LLMCloud task API", "version": TASK_CONTRACT_VERSION,
                 "description": "Implemented HTTP API; does not certify Worker/GPU execution."},
        "servers": [{"url": "/api/v1"}], "x-implementation-status": "implemented",
        "x-generated-by": "scripts/export_task_openapi.py", "paths": paths,
        "components": {"schemas": {name: selected[name] for name in sorted(selected)}}}


def generate_outputs():
    return {PROJECT_ROOT / "docs/api/tasks.openapi.json":
            json.dumps(build_contract(), ensure_ascii=False, indent=2) + "\n"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check drift without rewriting")
    args = parser.parse_args()
    stale = []
    for path, content in generate_outputs().items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(PROJECT_ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if stale:
        print("Stale task OpenAPI: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: task OpenAPI is current" if args.check else "Generated runtime task OpenAPI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
