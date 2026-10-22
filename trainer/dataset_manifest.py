"""Verify prepare_dataset v1 metadata against consumed files; never read test text."""

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from trainer.contracts import DatasetSummary, Sha256
from trainer.preprocessing import _fail

Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]
SplitName = Literal["train", "validation", "test"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Split(_Strict):
    file: str
    sha256: Sha256
    row_count: int = Field(gt=0)
    size_bytes: int = Field(gt=0)
    group_ids: list[Identifier] = Field(min_length=1)


class _Annotation(_Strict):
    row: int = Field(gt=0)
    record_id: Identifier
    group_id: Identifier
    source_ids: list[Identifier] = Field(min_length=1)
    reviewed: bool


class _Manifest(_Strict):
    tool_version: Literal["1.0.0"]
    seed: int = Field(ge=0, le=2**32 - 1)
    source_sha256: Sha256
    curation_sha256: Sha256
    protocol_sha256: Sha256
    source_catalog_sha256: Sha256
    build_id: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    domain: Literal["cloud-basics-zh"]
    protocol_version: Literal["1.0.0"]
    review_status: Literal["reviewed", "draft_unreviewed"]
    split_policy: str = Field(min_length=1)
    splits: dict[SplitName, _Split]
    provenance_sha256: Sha256

    @model_validator(mode="after")
    def check_splits_and_recipe(self):
        if set(self.splits) != {"train", "validation", "test"}:
            raise ValueError("Expected three splits")
        groups = set()
        for name, split in self.splits.items():
            if split.file != f"{name}.jsonl" or len(set(split.group_ids)) != len(split.group_ids):
                raise ValueError("Unexpected split file or duplicated family")
            if groups.intersection(split.group_ids):
                raise ValueError("Question families overlap between splits")
            groups.update(split.group_ids)
        recipe = {key: getattr(self, key) for key in ("tool_version", "seed", "source_sha256", "curation_sha256",
                                                     "protocol_sha256", "source_catalog_sha256")}
        encoded = (json.dumps(recipe, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        if hashlib.sha256(encoded).hexdigest()[:16] != self.build_id:
            raise ValueError("Build identifier does not match recipe")
        return self


def _document(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate metadata key")
            value[key] = item
        return value
    with Path(path).open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Metadata exceeds 2 MiB")
    return raw, json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique)


def verify_prepared_metadata(manifest_path, train_summary, validation_summary=None):
    """Local consistency is not a proof of human review or semantic non-leakage."""
    try:
        path = Path(manifest_path).resolve(strict=True)
        _, document = _document(path)
        manifest = _Manifest.model_validate(document)
        provenance_path = path.parent / "provenance.json"
        if not provenance_path.resolve(strict=True).is_relative_to(path.parent):
            raise ValueError("Provenance must stay inside the bundle")
        raw, document = _document(provenance_path)
        if hashlib.sha256(raw).hexdigest() != manifest.provenance_sha256:
            raise ValueError("Provenance hash mismatch")
        provenance = TypeAdapter(dict[SplitName, list[_Annotation]]).validate_python(document)
        if set(provenance) != set(manifest.splits):
            raise ValueError("Missing provenance split")
        rows, record_ids, reviews = [], [], []
        for split, annotations in provenance.items():
            expected = manifest.splits[split]
            if len(annotations) != expected.row_count or {item.group_id for item in annotations} != set(expected.group_ids):
                raise ValueError("Provenance rows/families mismatch")
            rows.extend(item.row for item in annotations)
            record_ids.extend(item.record_id for item in annotations)
            reviews.extend(item.reviewed for item in annotations)
        if sorted(rows) != list(range(1, len(rows) + 1)) or len(set(record_ids)) != len(record_ids):
            raise ValueError("Source rows/record identifiers are not unique and complete")
        if ("reviewed" if all(reviews) else "draft_unreviewed") != manifest.review_status:
            raise ValueError("Review status differs from provenance")
        summaries = {}
        for name, actual in (("train", train_summary), ("validation", validation_summary)):
            if actual is None:
                continue
            expected = manifest.splits[name]
            if any(getattr(actual, key) != getattr(expected, key) for key in ("sha256", "size_bytes", "row_count")):
                raise ValueError("Consumed data does not match declared split")
            summaries[name] = DatasetSummary(**actual.model_dump(exclude={"review_status", "build_id"}),
                                              review_status=manifest.review_status, build_id=manifest.build_id)
        return summaries
    except Exception as error:
        _fail("INVALID_DATASET", f"数据准备清单或 provenance 不匹配（{type(error).__name__}）。", cause=error)
