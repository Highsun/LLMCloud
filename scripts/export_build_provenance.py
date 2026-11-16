"""Export current Git identity and exact image-source SHA-256 to a new private file."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trainer.code_provenance import export_provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.expanduser().resolve()
    if target.is_relative_to(ROOT):
        parser.error("Keep generated image provenance outside the checkout on the runtime disk")
    value = export_provenance(ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "source_provenance_exported", "code_commit": value["code_commit"],
        "working_tree_dirty": value["working_tree_dirty"], "files": len(value["files"])}))


if __name__ == "__main__":
    main()
