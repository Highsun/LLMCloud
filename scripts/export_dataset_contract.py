"""Export the implemented dataset API from the real app, plus response examples."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import Settings  # noqa: E402
from backend.app.core.dataset_contract import DATASET_CONTRACT_VERSION  # noqa: E402
from backend.app.main import create_app  # noqa: E402
from backend.app.models.dataset_schemas import DatasetDetail, DatasetPage, DatasetSummary  # noqa: E402
from backend.app.models.error_schemas import ErrorResponse  # noqa: E402
from trainer.dataset_schema import InstructionRecord  # noqa: E402


def build_examples() -> dict[str, dict]:
    source = PROJECT_ROOT / "docs/examples/train.jsonl"
    raw = source.read_bytes()
    records = [InstructionRecord.model_validate_json(line) for line in raw.decode("utf-8-sig").split("\n") if line.strip()]
    detail = DatasetDetail(
        id="03a853e2-1bf1-45da-92fb-5a1548499fc4",
        name="云计算课程样例", format="alpaca_jsonl",
        original_filename="train.jsonl", sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw), row_count=len(records), created_at="2026-10-19T08:00:00Z",
    ).model_dump(mode="json")
    summary = DatasetSummary.model_validate({key: detail[key] for key in DatasetSummary.model_fields}).model_dump(mode="json")
    page = DatasetPage(items=[summary], total=1, page=1, page_size=20, total_pages=1).model_dump(mode="json")
    empty = DatasetPage(items=[], total=0, page=1, page_size=20, total_pages=0).model_dump(mode="json")
    beyond = DatasetPage(items=[], total=1, page=2, page_size=20, total_pages=1).model_dump(mode="json")
    error = ErrorResponse.model_validate({
        "error": {
            "code": "INVALID_DATASET", "message": "数据集第 2 行缺少 output 字段。",
            "details": [{"loc": ["body", "file", "output"], "code": "missing", "message": "output 为必填字符串。", "line": 2, "column": None}],
            "details_truncated": False, "request_id": "f63b14e1-7748-4e24-9db8-6d24810dd6df",
        },
    }).model_dump(mode="json")
    return {
        "upload-response.json": detail, "list-response.json": page,
        "empty-page.json": empty, "beyond-last-page.json": beyond,
        "error-response.json": error,
    }


def build_contract() -> dict:
    # OpenAPI generation never starts lifespan, opens SQL connections, or writes data.
    settings = Settings(_env_file=None, api_prefix="/api/v1")
    runtime = create_app(settings).openapi()
    paths = {path.removeprefix(settings.api_prefix): value
             for path, value in runtime["paths"].items()
             if path == "/api/v1/datasets" or path.startswith("/api/v1/datasets/")}
    schemas = runtime["components"]["schemas"]
    selected = {}

    def collect(value):
        if isinstance(value, dict):
            reference = value.get("$ref", "")
            if reference.startswith("#/components/schemas/"):
                name = reference.rsplit("/", 1)[1]
                if name not in selected:
                    selected[name] = schemas[name]
                    collect(schemas[name])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(paths)
    return {
        "openapi": runtime["openapi"],
        "info": {"title": "LLMCloud dataset API", "version": DATASET_CONTRACT_VERSION,
                 "description": "Implemented API exported from backend.app.main.create_app().openapi()."},
        "servers": [{"url": settings.api_prefix}],
        "x-implementation-status": "implemented",
        "x-generated-by": "scripts/export_dataset_contract.py",
        "paths": paths,
        "components": {"schemas": {name: selected[name] for name in sorted(selected)}},
    }


def generate_outputs() -> dict[Path, str]:
    examples = build_examples()
    values = {PROJECT_ROOT / "docs/api/datasets.openapi.json": build_contract()}
    values.update({PROJECT_ROOT / "docs/examples/datasets" / name: data for name, data in examples.items()})
    return {path: json.dumps(value, ensure_ascii=False, indent=2) + "\n" for path, value in values.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail when generated files differ; never rewrite")
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
        print("Stale contract files: " + ", ".join(stale), file=sys.stderr)
        return 1
    print("PASS: generated dataset contract is current" if args.check else "Generated runtime dataset OpenAPI and five response examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
