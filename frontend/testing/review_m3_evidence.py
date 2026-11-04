"""B-side read-only checks for an existing M3-07 run; never launches services/GPU.

Report consistency is separate from independent artifact and visual verification.
All output goes to stdout; the source evidence is never updated.
"""

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import struct
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.core.task_contract import DEFAULT_MODEL_REVISION
from backend.app.models.task_schemas import TaskCreate, TaskDetail
from trainer.artifacts import read_json, sha256, verify_training_artifacts
from trainer.contracts import RunEnvironment, TrainingSummary


class EvidenceError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def snapshot(value, *, status=None, code=None):
    task = TaskDetail.model_validate(value)
    require(task.model_revision == DEFAULT_MODEL_REVISION, "Unexpected model revision")
    if status:
        require(task.status == status, f"Unexpected status for {task.id}")
    if code:
        require(task.error_code == code, f"Unexpected failure code for {task.id}")
    for field in (task.created_at, task.started_at, task.finished_at):
        require(field is None or field.utcoffset().total_seconds() == 0, "Expected UTC timestamps")
    return task


def review_report(report):
    require(report["version"] == "1.0.0" and report["status"] == "passed", "Run did not pass")
    require(report["gpu_execution_verified"] is True, "Source report does not record real GPU execution")
    require(report["engineering_draft"] is True, "Engineering draft boundary is missing")
    require(report["model_revision"] == DEFAULT_MODEL_REVISION, "Unexpected report revision")
    cases = report["cases"]
    serial = cases["two_serial_gpu_tasks_and_browser"]
    require(serial["no_overlap"] is True and serial["browser_mocked_routes"] is False, "Serial browser evidence is mocked or incomplete")
    pair = [snapshot(task, status="COMPLETED") for task in serial["tasks"]]
    require(len(pair) == 2 and serial["task_ids"] == [str(t.id) for t in pair], "Two serial task IDs must match snapshots")
    require(pair[1].started_at >= pair[0].finished_at, "GPU task intervals overlap")
    require(pair[1].created_at < pair[0].finished_at, "Second task was not submitted while first was active")
    require(pair[0].dataset_id == pair[1].dataset_id and pair[0].config == pair[1].config, "Serial task input snapshots differ")
    dedup = cases["request_and_message_deduplication"]
    require(dedup["task_id"] == str(pair[0].id) and dedup["http_replay"] == 200 and dedup["duplicate"] == "skipped", "Deduplication evidence is missing")

    after = cases["after_commit"]
    acknowledged = snapshot(after["task"], status="COMPLETED")
    require(after["task_id"] == str(acknowledged.id) and after["controlled_injection"] is True, "After-commit fault must be explicit")
    before = cases["before_commit"]
    pending = snapshot(before["before"], status="RUNNING")
    recovered = snapshot(before["after"], status="COMPLETED")
    require(str(pending.id) == str(recovered.id) == before["task_id"], "Recovery replaced the original task")
    immutable = ("dataset_id", "base_model", "model_revision", "config", "created_at", "started_at", "current_step", "total_steps", "progress")
    require(all(getattr(pending, field) == getattr(recovered, field) for field in immutable), "Recovery changed a task snapshot")
    require(before["apply"]["applied_count"] == 1, "Expected exactly one recovered task")
    saving = cases["saving"]
    saved_failure = snapshot(saving["task"], status="FAILED", code="ARTIFACT_WRITE_FAILED")
    require(saving["task_id"] == str(saved_failure.id) and saving["controlled_injection"] is True, "Saving fault must be explicit")
    interruption = cases["gpu_interruption_and_queued_abandonment"]
    interrupted = snapshot(interruption["interrupted"], status="FAILED", code="WORKER_INTERRUPTED")
    queued = snapshot(interruption["queued"], status="FAILED", code="TASK_ABANDONED")
    require(interrupted.total_steps and 0 < interrupted.current_step < interrupted.total_steps, "Interrupted optimizer progress was lost")
    require(queued.started_at is None and queued.current_step == 0, "Abandoned task unexpectedly started")
    require(interruption["preserved_files"] and interruption["apply"]["applied_count"] == 2, "Interrupted file/reconciliation evidence missing")
    residual = cases["residual_message_after_reconciliation"]
    require(residual["task_id"] == str(queued.id) and residual["outcome"] == "skipped", "Residual message was not skipped")
    invalid = snapshot(cases["controlled_dataset_tamper"], status="FAILED", code="INVALID_DATASET")
    missing = snapshot(cases["isolated_missing_cache"], status="FAILED", code="MODEL_NOT_CACHED")
    tasks = pair + [acknowledged, recovered, saved_failure, interrupted, queued, invalid, missing]
    require(len({t.id for t in tasks}) == 9, "Expected nine distinct tasks")
    require(Counter(t.status for t in tasks) == {"COMPLETED": 4, "FAILED": 5}, "Unexpected final task counts")
    start, end = (datetime.fromisoformat(report[key].replace("Z", "+00:00")) for key in ("started_at", "finished_at"))
    require(start.tzinfo and end.tzinfo and start.utcoffset().total_seconds() == end.utcoffset().total_seconds() == 0, "Run times must be UTC")
    require(start <= min(t.created_at for t in tasks) <= max(t.finished_at for t in tasks) <= end, "Task times fall outside the run")
    completed = {str(t.id): t for t in tasks if t.status == "COMPLETED"}
    require(set(report["artifacts"]) == set(completed), "Artifact audit IDs differ from successful tasks")
    for task_id, item in report["artifacts"].items():
        require(item["status"] == "artifacts_verified" and item["task_id"] == task_id, "Invalid source artifact audit")
        summary = TrainingSummary.model_validate(item["summary"])
        environment = RunEnvironment.model_validate(item["environment"])
        require(summary.completed_steps == summary.total_steps == completed[task_id].current_step == 2, "Success step totals differ")
        require(summary.peak_memory_allocated_bytes > 0 and not environment.working_tree_dirty, "GPU/clean-commit evidence is missing")
        require(len(item["manifest_sha256"]) == 64 and all(c in "0123456789abcdef" for c in item["manifest_sha256"]), "Invalid manifest digest")
    return completed


def review_original_browser(directory, serial):
    original = read_json(directory / "browser-success" / "result.json")
    ids = serial["task_ids"]
    require(original["actual_services"] is True and original["mocked_routes"] is False, "Original submission used test substitutes")
    require(original["task_ids"] == ids and original["tasks"] == serial["tasks"], "Original browser tasks differ from report")
    submissions = original["submissions"]
    require(len(submissions) == 2 and submissions[0]["key"] != submissions[1]["key"], "Browser submissions did not use two distinct keys")
    for submission, raw in zip(submissions, serial["tasks"]):
        body = TaskCreate.model_validate(submission["body"])
        task = snapshot(raw)
        require(submission["id"] == str(task.id) and body.dataset_id == task.dataset_id and body.config == task.config,
            "Browser request differs from task snapshot")
    observations = original["observations"]
    require(observations, "Original live observations are missing")
    for observed in observations:
        require([task["id"] for task in observed] == ids, "Observation contains different task IDs")
        require(sum(task["status"] == "RUNNING" for task in observed) <= 1, "Observation contains two RUNNING tasks")
    require(any(task["status"] == "RUNNING" for group in observations for task in group), "No live RUNNING observation was recorded")


def review_browser(directory, task_id, status):
    result = read_json(directory / "result.json")
    require(result["actual_services"] is True and result["mocked_routes"] is False, "Browser used substitute services/routes")
    require(result["task_ids"] == [task_id] and result["status"] == status, "Browser reviewed another task")
    for filename, width in (("desktop.png", 1440), ("mobile.png", 390)):
        with (directory / filename).open("rb") as stream:
            header = stream.read(24)
        require(header[:8] == b"\x89PNG\r\n\x1a\n" and len(header) == 24, "Invalid screenshot")
        require(struct.unpack(">II", header[16:24])[0] == width, "Screenshot viewport differs")
    with ZipFile(directory / "trace.zip") as archive:
        records = [item for item in archive.infolist() if item.filename.endswith((".trace", ".network"))]
        require(records and sum(item.file_size for item in records) <= 128 * 1024 * 1024, "Missing or oversized trace records")
        for item in records:
            require(b"/__test__/" not in archive.read(item), "Test control endpoint appears in trace")


def review(directory, *, audit_artifacts=False):
    report = read_json(directory / "report.json")
    completed = review_report(report)
    cases = report["cases"]
    review_original_browser(directory, cases["two_serial_gpu_tasks_and_browser"])
    targets = [
        ("browser-success-cjk", cases["two_serial_gpu_tasks_and_browser"]["task_ids"][1], "COMPLETED"),
        ("browser-recovered-cjk", cases["before_commit"]["task_id"], "COMPLETED"),
        ("browser-saving-failed-cjk", cases["saving"]["task_id"], "FAILED"),
        ("browser-interrupted-cjk", cases["gpu_interruption_and_queued_abandonment"]["interrupted"]["id"], "FAILED"),
        ("browser-invalid-dataset-cjk", cases["controlled_dataset_tamper"]["id"], "FAILED"),
    ]
    for name, task_id, status in targets:
        review_browser(directory / name, task_id, status)
    if audit_artifacts:
        for task_id, task in completed.items():
            bundle = directory / "data" / "outputs" / task_id
            checked = verify_training_artifacts(bundle, outputs_root=bundle.parent,
                expected_task_id=task_id, expected_revision=report["model_revision"])
            require(sha256(bundle / "manifest.json") == report["artifacts"][task_id]["manifest_sha256"], "Manifest digest differs from original report")
            require(checked.manifest.config == task.config, "Artifact config differs from API snapshot")
    return {"status": "evidence_consistent", "report_sha256": sha256(directory / "report.json"),
        "task_count": 9, "completed": 4, "expected_failed": 5, "browser_evidence_sets": 5,
        "independent_artifact_audit": "passed" if audit_artifacts else "not_requested",
        "gpu_rerun": False, "visual_review": "still_required", "milestone_complete": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--audit-artifacts", action="store_true", help="Require all four complete bundles and reuse the shared CPU auditor")
    args = parser.parse_args()
    try:
        result = review(args.run_dir, audit_artifacts=args.audit_artifacts)
    except FileNotFoundError:
        print(json.dumps({"status": "blocked", "code": "EVIDENCE_FILE_MISSING", "milestone_complete": False}))
        return 2
    except Exception as error:
        result = {"status": "rejected", "code": "EVIDENCE_INCONSISTENT", "error_type": type(error).__name__, "milestone_complete": False}
        if isinstance(error, EvidenceError):
            result["reason"] = str(error)
        print(json.dumps(result))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
