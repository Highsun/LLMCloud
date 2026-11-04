"""Synthetic fixtures test the reviewer; they are NEVER real GPU evidence."""

from copy import deepcopy
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4
from zipfile import ZipFile

from review_m3_evidence import ROOT, EvidenceError, review, review_report


def fixture():
    template = json.loads((ROOT / "docs/examples/tasks/detail-completed.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "docs/examples/training/manifest.json").read_text(encoding="utf-8"))
    tasks = []
    for index in range(9):
        task = {**deepcopy(template), "id": str(uuid4())}
        if index == 1:
            task.update(started_at="2026-10-24T01:00:04Z", finished_at="2026-10-24T01:00:06Z")
        tasks.append(task)
    for task, code in zip(tasks[4:], ["ARTIFACT_WRITE_FAILED", "WORKER_INTERRUPTED", "TASK_ABANDONED", "INVALID_DATASET", "MODEL_NOT_CACHED"]):
        task.update(status="FAILED", error_code=code, error_message="Synthetic reviewer test")
    tasks[5].update(current_step=1, total_steps=64, progress=1 / 64)
    tasks[6].update(current_step=0, total_steps=None, progress=None, started_at=None)
    for task in tasks[7:]:
        task.update(current_step=0, total_steps=None, progress=None)
    a, b, after, recovered, saving, interrupted, queued, invalid, missing = tasks
    report = {"version": "1.0.0", "status": "passed", "gpu_execution_verified": True,
        "engineering_draft": True, "model_revision": template["model_revision"],
        "started_at": "2026-10-24T00:59:00Z", "finished_at": "2026-10-24T01:01:00Z",
        "cases": {
            "two_serial_gpu_tasks_and_browser": {"task_ids": [a["id"], b["id"]], "tasks": [a, b], "no_overlap": True, "browser_mocked_routes": False},
            "request_and_message_deduplication": {"task_id": a["id"], "http_replay": 200, "duplicate": "skipped"},
            "after_commit": {"task_id": after["id"], "task": after, "controlled_injection": True},
            "before_commit": {"task_id": recovered["id"], "before": {**deepcopy(recovered), "status": "RUNNING", "finished_at": None}, "after": recovered, "apply": {"applied_count": 1}},
            "saving": {"task_id": saving["id"], "task": saving, "controlled_injection": True},
            "gpu_interruption_and_queued_abandonment": {"interrupted": interrupted, "queued": queued, "preserved_files": {"metrics.jsonl": "a" * 64}, "apply": {"applied_count": 2}},
            "residual_message_after_reconciliation": {"task_id": queued["id"], "outcome": "skipped"},
            "controlled_dataset_tamper": invalid, "isolated_missing_cache": missing,
        }, "artifacts": {}}
    for task in tasks[:4]:
        report["artifacts"][task["id"]] = {"task_id": task["id"], "status": "artifacts_verified",
            "summary": manifest["summary"], "environment": manifest["environment"], "manifest_sha256": "a" * 64}
    return report


def write_fixture(root, report, *, mocked=False, trace_url="/api/v1/tasks"):
    (root / "report.json").write_text(json.dumps(report), encoding="utf-8")
    serial = report["cases"]["two_serial_gpu_tasks_and_browser"]
    original = root / "browser-success"
    original.mkdir()
    data = {"actual_services": True, "mocked_routes": False, "task_ids": serial["task_ids"], "tasks": serial["tasks"],
        "submissions": [{"id": task["id"], "key": str(uuid4()), "body": {"dataset_id": task["dataset_id"], "config": task["config"]}} for task in serial["tasks"]],
        "observations": [[{"id": task["id"], "status": "RUNNING" if i == 0 else "QUEUED"} for i, task in enumerate(serial["tasks"])]]}
    (original / "result.json").write_text(json.dumps(data), encoding="utf-8")
    cases = report["cases"]
    targets = [("success", serial["task_ids"][1], "COMPLETED"), ("recovered", cases["before_commit"]["task_id"], "COMPLETED"),
        ("saving-failed", cases["saving"]["task_id"], "FAILED"), ("interrupted", cases["gpu_interruption_and_queued_abandonment"]["interrupted"]["id"], "FAILED"),
        ("invalid-dataset", cases["controlled_dataset_tamper"]["id"], "FAILED")]
    for name, task_id, status in targets:
        directory = root / f"browser-{name}-cjk"
        directory.mkdir()
        (directory / "result.json").write_text(json.dumps({"actual_services": True, "mocked_routes": mocked, "task_ids": [task_id], "status": status}), encoding="utf-8")
        # Header-only placeholders intentionally test metadata checks, NOT visual validity.
        for filename, width in (("desktop.png", 1440), ("mobile.png", 390)):
            (directory / filename).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", width, 1000))
        with ZipFile(directory / "trace.zip", "w") as archive:
            archive.writestr("trace.network", json.dumps({"url": trace_url}))


class EvidenceTests(unittest.TestCase):
    def test_report_accepts_consistent_synthetic_structure_only(self):
        self.assertEqual(len(review_report(fixture())), 4)

    def test_rejects_overlap_even_when_no_overlap_flag_is_true(self):
        report = fixture()
        report["cases"]["two_serial_gpu_tasks_and_browser"]["tasks"][1]["started_at"] = "2026-10-24T01:00:02Z"
        with self.assertRaises(EvidenceError):
            review_report(report)

    def test_rejects_loss_of_progress_and_changed_recovery_snapshot(self):
        for mutation in ("progress", "config"):
            report = fixture()
            if mutation == "progress":
                report["cases"]["gpu_interruption_and_queued_abandonment"]["interrupted"].update(current_step=0, progress=0.0)
            else:
                report["cases"]["before_commit"]["after"]["config"]["lora_r"] = 16
            with self.assertRaises(EvidenceError):
                review_report(report)

    def test_report_and_trace_checks_never_claim_stage_or_visual_completion(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_fixture(root, fixture())
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
            result = review(root)
            self.assertEqual(before, {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()})
            self.assertEqual(result["status"], "evidence_consistent")
            self.assertFalse(result["milestone_complete"])
            self.assertEqual(result["visual_review"], "still_required")
            self.assertEqual(result["independent_artifact_audit"], "not_requested")

    def test_rejects_mocked_results_and_control_routes(self):
        for options in ({"mocked": True}, {"trace_url": "/__test__/tasks"}):
            with tempfile.TemporaryDirectory() as name:
                root = Path(name)
                write_fixture(root, fixture(), **options)
                with self.assertRaises(EvidenceError):
                    review(root)

    def test_missing_full_bundles_cannot_pass_independent_artifact_audit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write_fixture(root, fixture())
            with self.assertRaises(Exception):
                review(root, audit_artifacts=True)

    def test_missing_source_is_blocked_without_creating_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            missing = Path(name) / "not-present"
            result = subprocess.run([sys.executable, str(ROOT / "frontend/testing/review_m3_evidence.py"), str(missing)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["code"], "EVIDENCE_FILE_MISSING")
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
