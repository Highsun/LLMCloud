"""Validate curated instruction data and create a reproducible grouped split.

Only local, explicitly supplied data is processed. No download, model inference,
or automatic assertion of human review occurs here.
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trainer.dataset import DatasetScanner, DatasetValidationError  # noqa: E402

TOOL_VERSION = "1.0.0"
PROTOCOL = ROOT / "docs/data/cloud-basics-eval-v1.json"
SOURCES = ROOT / "docs/data/sources.json"
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    row: int = Field(ge=1)
    record_id: Identifier
    group_id: Identifier
    source_ids: list[Identifier] = Field(min_length=1)
    reviewed: bool


class Curation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["1.0.0"]
    rows: list[Annotation] = Field(min_length=1)


class PreparationError(ValueError):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def normalized(value: str) -> str:
    # Comparison only: never modify training strings or overwrite source bytes.
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in text if not character.isspace()
                   and not unicodedata.category(character).startswith("P"))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PreparationError("JSON metadata contains duplicate keys")
        result[key] = value
    return result


def load_document(path: Path):
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise PreparationError("Metadata document exceeds 2 MiB")
    try:
        return raw, json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError):
        raise PreparationError("Metadata must be valid UTF-8 JSON") from None


def load_protocol(protocol_path=PROTOCOL, sources_path=SOURCES):
    source_raw, catalog = load_document(Path(sources_path))
    protocol_raw, protocol = load_document(Path(protocol_path))
    try:
        source_ids = {source["id"] for source in catalog["sources"]}
        cases = protocol["cases"]
        if not source_ids or len(source_ids) != len(catalog["sources"]) or not cases:
            raise PreparationError("Source IDs must be unique and evaluation cases nonempty")
        ids = set()
        for case in cases:
            if case["id"] in ids or not case["prompt"].strip() or not case["group_id"]:
                raise PreparationError("Evaluation cases need unique IDs, prompts and groups")
            ids.add(case["id"])
            if not case["expected_points"] or not case["critical_errors"] or not set(case["source_ids"]) <= source_ids:
                raise PreparationError("Evaluation case rubric/source references are invalid")
    except (KeyError, TypeError):
        raise PreparationError("Invalid source catalog or evaluation protocol") from None
    return source_raw, protocol_raw, source_ids, protocol


def plan_dataset(source: Path, curation: Path, *, seed=42, allow_unreviewed=False,
                 protocol_path=PROTOCOL, sources_path=SOURCES):
    """Return output bytes and manifest without creating any directories/files."""
    source = Path(source)
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise PreparationError("Seed must be a uint32 integer")
    catalog_raw, protocol_raw, source_ids, protocol = load_protocol(protocol_path, sources_path)
    metadata_raw, metadata = load_document(Path(curation))
    try:
        annotations = Curation.model_validate(metadata).rows
    except ValidationError:
        raise PreparationError("Curation metadata does not match the versioned schema") from None
    # Shared scanner validates the entire file, including BOM, duplicate keys and limits.
    scanner = DatasetScanner()
    records = []
    with source.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            records.extend(scanner.feed(chunk))
    records.extend(scanner.finish())
    source_hash = scanner.stats.sha256
    if len(annotations) != len(records) or sorted(item.row for item in annotations) != list(range(1, len(records) + 1)):
        raise PreparationError("Curation rows must map every nonblank source record exactly once")
    annotations.sort(key=lambda item: item.row)
    if len({item.record_id for item in annotations}) != len(annotations):
        raise PreparationError("record_id must be unique")
    if any(not set(item.source_ids) <= source_ids for item in annotations):
        raise PreparationError("Unknown source_id in curation metadata")
    if not allow_unreviewed and any(not item.reviewed for item in annotations):
        raise PreparationError("Unreviewed records require explicit --allow-unreviewed; outputs remain draft")
    reserved = {case["group_id"] for case in protocol["cases"]}
    frozen_prompts = {normalized(case["prompt"]) for case in protocol["cases"]}
    seen = set()
    for record, annotation in zip(records, annotations):
        key = normalized(record["instruction"]), normalized(record.get("input", ""))
        if key in seen:
            raise PreparationError("Duplicate normalized question/input; curate before splitting")
        seen.add(key)
        if annotation.group_id in reserved or key[0] in frozen_prompts:
            raise PreparationError("Frozen evaluation question/family cannot enter development splits")
    groups = sorted({item.group_id for item in annotations},
                    key=lambda group: digest(f"{seed}\0{group}".encode()))
    if len(groups) < 3:
        raise PreparationError("At least three independent question families are required")
    held_out = max(1, len(groups) // 10)
    assignment = {group: ("validation" if index < held_out else "test" if index < 2 * held_out else "train")
                  for index, group in enumerate(groups)}
    recipe = {"tool_version": TOOL_VERSION, "seed": seed, "source_sha256": source_hash,
              "curation_sha256": digest(metadata_raw), "protocol_sha256": digest(protocol_raw),
              "source_catalog_sha256": digest(catalog_raw)}
    manifest = {**recipe, "build_id": digest(encoded(recipe))[:16], "domain": protocol["domain"],
                "protocol_version": protocol["version"], "review_status": "reviewed" if all(item.reviewed for item in annotations) else "draft_unreviewed",
                "split_policy": "question_family_sha256_seed_v1; approximately 80/10/10 by family, minimum one held-out family per split",
                "splits": {}}
    files, provenance = {}, {}
    for split in ("train", "validation", "test"):
        chosen = [(record, item) for record, item in zip(records, annotations) if assignment[item.group_id] == split]
        raw = b"".join((json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
                       for record, _ in chosen)
        check = DatasetScanner()
        for offset in range(0, len(raw), 64 * 1024):
            check.feed(raw[offset:offset + 64 * 1024])
        check.finish()
        filename = f"{split}.jsonl"
        files[filename] = raw
        manifest["splits"][split] = {"file": filename, "sha256": check.stats.sha256,
                                     "row_count": check.stats.row_count, "size_bytes": check.stats.size_bytes,
                                     "group_ids": sorted({item.group_id for _, item in chosen})}
        provenance[split] = [item.model_dump() for _, item in chosen]
    files["provenance.json"] = encoded(provenance)
    manifest["provenance_sha256"] = digest(files["provenance.json"])
    files["manifest.json"] = encoded(manifest)  # Written last: partial bundles have no manifest.
    return files, manifest


def write_bundle(output: Path, files: dict[str, bytes]):
    """Create one new local bundle; never overwrite an existing output directory."""
    output = Path(output)
    if set(files) != {"train.jsonl", "validation.jsonl", "test.jsonl", "provenance.json", "manifest.json"}:
        raise PreparationError("Unexpected output members")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()  # Exclusive ownership, including when an existing directory is empty.
    owned = []
    try:
        for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "provenance.json", "manifest.json"):
            path = output / name
            with path.open("xb") as stream:
                owned.append(path)
                stream.write(files[name])
    except BaseException:
        incomplete = False
        for path in reversed(owned):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                incomplete = True
        try:
            output.rmdir()
        except OSError:
            incomplete = True
        if incomplete:
            print("Bundle cleanup incomplete; inspect the requested output directory", file=sys.stderr)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--curation", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--allow-unreviewed", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        files, manifest = plan_dataset(args.source, args.curation, seed=args.seed, allow_unreviewed=args.allow_unreviewed)
        if not args.check_only:
            if args.output is None:
                raise PreparationError("--output is required unless --check-only")
            from backend.app.core.config import get_settings
            if not args.output.resolve().is_relative_to(get_settings().data_dir.resolve()):
                raise PreparationError("Output must stay inside configured DATA_DIR")
            write_bundle(args.output, files)
        print(encoded(manifest).decode(), end="")
    except (PreparationError, DatasetValidationError, OSError) as error:
        # Operator errors must not dump private training records or metadata input.
        print(f"Dataset preparation failed: {error if isinstance(error, PreparationError) else type(error).__name__}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
