"""Value-checked projection of existing Trainer JSONL, never raw traceback text."""

from datetime import datetime, timezone
import json
import math
import re
from typing import get_args

from backend.app.core.observability_contract import (
    LOG_FIELDS_BY_STAGE, MAX_LOG_DIAGNOSTICS, MAX_LOG_FRAMES, MAX_LOG_TARGET_MODULES, MAX_SAFE_INTEGER,
)
from trainer.contracts import FailureCode, FailureStage, TrainingProgress


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def reject_constant(_value):
    raise ValueError("Non-finite JSON")


def load_json(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=reject_constant)


def _integer(value):
    return type(value) is int and 0 <= value <= MAX_SAFE_INTEGER


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _identifier(value, pattern=r"[A-Za-z_][A-Za-z0-9_]{0,127}"):
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _utc(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value
    ):
        raise ValueError("Invalid recorded_at")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dataset(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        return None
    checks = {"sha256": _sha, "size_bytes": _integer, "row_count": _integer,
              "review_status": lambda v: v in ("unknown", "draft_unreviewed", "reviewed") if isinstance(v, str) else False,
              "build_id": lambda v: v is None or _identifier(v, r"[0-9a-f]{16}")}
    return {k: v for k, v in value.items() if k in checks and checks[k](v)}


def _failure(value, task_id):
    if not isinstance(value, dict):
        return None
    result = {}
    if value.get("task_id") == str(task_id):
        result["task_id"] = str(task_id)
    if value.get("code") in get_args(FailureCode):
        result["code"] = value["code"]
    if value.get("stage") in get_args(FailureStage):
        result["stage"] = value["stage"]
    return result


def _diagnostic(value):
    if not isinstance(value, list):
        return None
    result = []
    for item in value[:MAX_LOG_DIAGNOSTICS]:
        if not isinstance(item, dict) or not _identifier(item.get("type")):
            continue
        frames = []
        raw_frames = item.get("frames", [])
        if isinstance(raw_frames, list):
            for frame in raw_frames[-MAX_LOG_FRAMES:]:
                if (isinstance(frame, dict)
                        and _identifier(frame.get("file"), r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\.py")
                        and _identifier(frame.get("function"), r"(?:[A-Za-z_][A-Za-z0-9_]{0,127}|<module>|<listcomp>|<genexpr>|<lambda>)")
                        and _integer(frame.get("line")) and frame["line"] > 0):
                    frames.append({k: frame[k] for k in ("file", "function", "line")})
        result.append({"type": item["type"], "frames": frames})
    return result


def project_log(raw, task_id):
    """Return (single safe JSON line or None, altered/dropped-record flag).

    Comparison precedes timestamp normalization: normal formatting is not a
    filtering warning. A dropped nested field still counts its source line once.
    """
    try:
        value = load_json(raw)
        if not isinstance(value, dict) or value.get("stage") not in LOG_FIELDS_BY_STAGE:
            return None, True
        timestamp = _utc(value.get("recorded_at"))
        stage = value["stage"]
        result = {"recorded_at": value["recorded_at"], "stage": stage}
        checks = {
            "task_id": lambda v: v == str(task_id),
            "precision": lambda v: v in ("bf16", "fp32") if isinstance(v, str) else False,
            "base_sha256_before": _sha, "base_sha256_after": _sha,
            "base_unchanged": lambda v: type(v) is bool,
            "target_modules": lambda v: isinstance(v, list) and len(v) <= MAX_LOG_TARGET_MODULES and all(
                _identifier(x, r"[A-Za-z_][A-Za-z0-9_.]{0,127}") for x in v),
            "framework_learning_rate": lambda v: v is None or _number(v),
        }
        nested = {"train": _dataset, "validation": _dataset,
                  "failure": lambda v: _failure(v, task_id), "diagnostic": _diagnostic}
        metric_fields = ("contract_version", "kind", "step", "total_steps", "loss", "learning_rate", "epoch")
        if stage == "metric":
            TrainingProgress.model_validate({k: value[k] for k in (*metric_fields, "recorded_at")})
            result.update({k: value[k] for k in metric_fields})
        for key in LOG_FIELDS_BY_STAGE[stage]:
            if key not in value or (stage == "metric" and key in metric_fields):
                continue
            candidate = value[key]
            if key in nested:
                projected = nested[key](candidate)
                if projected is not None or (key == "validation" and candidate is None):
                    result[key] = projected
            elif checks.get(key, _integer)(candidate):
                result[key] = candidate
        filtered = result != value
        result["recorded_at"] = timestamp
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False), filtered
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None, True
