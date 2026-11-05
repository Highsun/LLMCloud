"""SQL/HTTP/lifecycle checks with existing synthetic CPU bundles, not GPU evidence."""

import asyncio
from contextlib import nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from uuid import UUID, uuid1, uuid4
import zipfile

from fastapi.testclient import TestClient
from sqlalchemy import update

from backend.app.api.task_download import AdapterResponse, prepare_response
from backend.app.core.config import Settings
from backend.app.core.observability_protocols import CompletedArtifactNotFound, CompletedArtifactNotReady, CompletedArtifactSpec
from backend.app.core.task_contract import PublishOutcome
from backend.app.core.task_protocols import TaskStoreError
from backend.app.main import create_app
from backend.app.models.entities import TrainingTask
from backend.app.models.error_schemas import ErrorResponse
from backend.app.models.task_schemas import TaskCreate
from backend.app.services import task_download as download_module
from backend.app.services.errors import DatasetServiceError
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import TrainRequest, TrainingFailure, RuntimeOptions
from worker_support import synthetic_train

ROOT = Path(__file__).resolve().parents[1]


class PublisherDouble:
    def publish(self, *_args): return PublishOutcome.ACCEPTED


class TaskDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = Settings(_env_file=None, data_dir=root / "data", log_dir=root / "logs", database_url="", training_max_steps=2)
        self.app = create_app(self.settings, task_publisher=PublisherDouble())
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.repo = self.app.state.task_repository
        self.service = self.app.state.task_download_service
        dataset = self.client.post("/api/v1/datasets", files={"file": ("fixture.jsonl", b'{"instruction":"x","output":"y"}\n')}).json()
        self.dataset_id = dataset["id"]
        self.task_id = self.new_task()
        self.output = self.settings.data_dir / "outputs" / self.task_id

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def new_task(self):
        result = self.client.post("/api/v1/tasks", json={"dataset_id": self.dataset_id,
            "config": {"lora_r": 1, "target_modules": ["q_proj"]}})
        self.assertEqual(result.status_code, 202, result.text)
        return result.json()["id"]

    def saved_bundle(self):
        token = uuid4()
        spec = self.repo.claim(self.task_id, token, "cpu-download-fixture")
        request = TrainRequest(task_id=spec.task_id, dataset_path=self.settings.data_dir / spec.dataset_key,
            output_dir=self.output, log_path=self.settings.log_dir / "tasks" / f"{spec.task_id}.log",
            base_model=spec.base_model, model_revision=spec.model_revision, config=spec.config,
            runtime=spec.runtime, cache_dir=self.settings.data_dir / "models" / "empty-cache")
        synthetic_train(request, lambda event: self.repo.record_progress(spec.task_id, token, event))
        audit = verify_training_artifacts(self.output)
        return token, audit

    def completed(self):
        token, audit = self.saved_bundle()
        self.repo.complete(self.task_id, token, f"outputs/{self.task_id}", sha256(self.output / "manifest.json"), audit.manifest.summary)
        return audit

    def get(self, **kwargs):
        return self.client.get(f"/api/v1/tasks/{self.task_id}/adapter", **kwargs)

    def error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        error = ErrorResponse.model_validate(response.json()).error
        self.assertEqual(error.code, code)
        self.assertEqual(str(error.request_id), response.headers["x-request-id"])
        self.assertNotIn(str(self.settings.data_dir), response.text)
        self.assertNotIn("Content-Disposition", response.headers)
        return error

    def empty_temporary_area(self):
        folder = self.settings.data_dir / "downloads"
        self.assertTrue(not folder.exists() or list(folder.iterdir()) == [])

    def test_snapshot_repository_business_outcomes_and_no_file_io(self):
        with self.assertRaises(CompletedArtifactNotFound):
            self.repo.get_completed_artifact(uuid4())
        with self.assertRaises(CompletedArtifactNotReady):
            self.repo.get_completed_artifact(self.task_id)
        self.completed()
        with patch.object(Path, "open", side_effect=AssertionError("SQL does not open artifacts")):
            snapshot = self.repo.get_completed_artifact(self.task_id)
        CompletedArtifactSpec.model_validate(snapshot.model_dump())
        snapshot.spec.config.target_modules.append("other")
        self.assertEqual(self.repo.get_completed_artifact(self.task_id).spec.config.target_modules, ["q_proj"])

    def test_all_unfinished_states_are_gated_and_missing_is_404(self):
        self.error(self.get(), 409, "ARTIFACT_NOT_READY")  # QUEUED
        self.repo.claim(self.task_id, uuid4(), "cpu-fixture")
        self.error(self.get(), 409, "ARTIFACT_NOT_READY")  # RUNNING
        other = self.new_task()
        self.task_id = other
        token = uuid4()
        self.repo.claim(other, token, "cpu-fixture")
        self.repo.fail(other, token, TrainingFailure(code="TRAINING_FAILED", stage="training", message="CPU fixture"))
        self.error(self.get(), 409, "ARTIFACT_NOT_READY")  # FAILED
        self.task_id = str(uuid4())
        self.error(self.get(), 404, "TASK_NOT_FOUND")
        pending = self.repo.create(TaskCreate(dataset_id=self.dataset_id),
            model_revision=self.settings.default_model_revision, runtime=RuntimeOptions())
        self.task_id = str(pending.task.id)
        self.error(self.get(), 409, "ARTIFACT_NOT_READY")  # PENDING
        self.empty_temporary_area()

    def test_running_at_full_progress_with_valid_bundle_still_cannot_download(self):
        self.saved_bundle()  # Valid files saved, SQL completion not committed.
        self.assertEqual(self.repo.get_detail(self.task_id).progress, 1.0)
        self.error(self.get(), 409, "ARTIFACT_NOT_READY")

    def test_valid_zip_headers_layout_bytes_and_independent_audit(self):
        audit = self.completed()
        before = {p.relative_to(self.output).as_posix(): sha256(p) for p in self.output.rglob("*") if p.is_file()}
        (self.output / "checkpoints").mkdir()
        (self.output / "checkpoints" / "not-downloadable.bin").write_bytes(b"ignored")
        with patch("backend.app.core.worker_lock.WorkerInstanceLock.acquire", side_effect=AssertionError("No GPU lock")):
            response = self.get(headers={"Origin": "http://localhost:5173"})
        self.assertEqual(response.status_code, 200, response.text[:100])
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(response.headers["content-length"], str(len(response.content)))
        self.assertEqual(response.headers["content-disposition"], f'attachment; filename="llmcloud-adapter-{self.task_id}.zip"')
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertIn("Content-Disposition", response.headers["access-control-expose-headers"])
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle, tempfile.TemporaryDirectory() as extracted:
            self.assertIsNone(bundle.testzip())
            self.assertEqual(set(bundle.namelist()), {f"{self.task_id}/{name}" for name in before})
            for name, expected in before.items():
                self.assertEqual(hashlib.sha256(bundle.read(f"{self.task_id}/{name}")).hexdigest(), expected)
            output = Path(extracted) / "outputs"
            bundle.extractall(output)
            reloaded = verify_training_artifacts(output / self.task_id, outputs_root=output)
            self.assertEqual(reloaded.manifest, audit.manifest)
        self.assertEqual({name: sha256(self.output / name) for name in before}, before)
        self.empty_temporary_area()

    def test_sql_corruption_and_unavailable_are_503_without_reading_files(self):
        self.completed()
        with patch.object(self.repo, "get_completed_artifact", side_effect=TaskStoreError()):
            self.error(self.get(), 503, "DATABASE_UNAVAILABLE")
        with self.repo.sessions.begin() as session:
            session.execute(update(TrainingTask).where(TrainingTask.id == self.task_id).values(training_summary={"bad": "record"}))
        self.error(self.get(), 503, "DATABASE_UNAVAILABLE")
        self.empty_temporary_area()

    def test_strict_path_and_no_query_parameters(self):
        for task_id in ("invalid", str(uuid1())):
            self.task_id = task_id
            self.error(self.get(), 422, "VALIDATION_ERROR")
        self.task_id = self.new_task()
        for params in ("path=/secret", "tail=1", "path=a&path=b"):
            response = self.client.get(f"/api/v1/tasks/{self.task_id}/adapter?{params}")
            self.error(response, 422, "VALIDATION_ERROR")

    def test_missing_or_tampered_source_is_invalid_and_state_unchanged(self):
        self.completed()
        original = self.repo.get_detail(self.task_id).model_dump_json()
        target = self.output / "adapter/adapter_model.safetensors"
        raw = target.read_bytes()
        target.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.error(self.get(), 500, "INVALID_ARTIFACT")
        target.unlink()
        self.error(self.get(), 500, "INVALID_ARTIFACT")
        self.assertEqual(self.repo.get_detail(self.task_id).model_dump_json(), original)
        self.empty_temporary_area()

    def test_manifest_hash_and_sql_snapshots_must_match(self):
        self.completed()
        original = self.output / "manifest.json"
        raw = original.read_bytes()
        original.write_bytes(raw + b" ")
        self.error(self.get(), 500, "INVALID_ARTIFACT")
        original.write_bytes(raw)
        original_snapshot = self.repo.get_completed_artifact(self.task_id)
        for field, value in (("dataset_sha256", "f" * 64), ("dataset_size_bytes", 999), ("dataset_row_count", 999),
                             ("model_revision", "a" * 40)):
            altered = original_snapshot.model_copy(update={"spec": original_snapshot.spec.model_copy(update={field: value})})
            with patch.object(self.repo, "get_completed_artifact", return_value=altered):
                self.error(self.get(), 500, "INVALID_ARTIFACT")
        for name, value in (("config", original_snapshot.spec.config.model_copy(update={"learning_rate": 0.001})),
                            ("runtime", original_snapshot.spec.runtime.model_copy(update={"precision": "fp32"}))):
            altered = original_snapshot.model_copy(update={"spec": original_snapshot.spec.model_copy(update={name: value})})
            with patch.object(self.repo, "get_completed_artifact", return_value=altered):
                self.error(self.get(), 500, "INVALID_ARTIFACT")
        altered = original_snapshot.model_copy(update={"training_summary": original_snapshot.training_summary.model_copy(update={"final_loss": 5.0})})
        with patch.object(self.repo, "get_completed_artifact", return_value=altered):
            self.error(self.get(), 500, "INVALID_ARTIFACT")

    def test_sparse_oversize_preflight_does_not_run_full_audit(self):
        self.completed()
        with (self.output / "adapter/adapter_model.safetensors").open("r+b") as stream:
            stream.truncate(download_module.MAX_DOWNLOAD_BYTES + 1)
        with patch.object(download_module, "verify_training_artifacts", side_effect=AssertionError("Preflight first")):
            self.error(self.get(), 413, "ARTIFACT_TOO_LARGE")
        self.empty_temporary_area()

    def test_unexpected_files_links_fifo_and_directories_are_rejected(self):
        self.completed()
        for name in ("failure.json", "dataset.jsonl"):
            path = self.output / name
            path.write_text("must not be delivered")
            self.error(self.get(), 500, "INVALID_ARTIFACT")
            path.unlink()
        target = self.output / "adapter/adapter_model.safetensors"
        outside = Path(self.temp.name) / "outside"
        target.rename(outside)
        for kind in ("symlink", "hardlink", "fifo", "directory"):
            if kind == "symlink": target.symlink_to(outside)
            elif kind == "hardlink": os.link(outside, target)
            elif kind == "fifo": os.mkfifo(target)
            else: target.mkdir()
            self.error(self.get(), 500, "INVALID_ARTIFACT")
            if target.is_dir(): target.rmdir()
            else: target.unlink()
        outside.rename(target)
        adapter = target.parent
        moved = adapter.with_name("adapter-old")
        adapter.rename(moved)
        adapter.symlink_to(moved)
        self.error(self.get(), 500, "INVALID_ARTIFACT")
        self.empty_temporary_area()

    def test_busy_slot_covers_preparation_response_and_cleanup_without_gpu_lock(self):
        self.completed()
        first = self.service.prepare(UUID(self.task_id))
        try:
            response = self.get(headers={"Origin": "http://localhost:5173"})
            self.error(response, 429, "DOWNLOAD_BUSY")
            self.assertEqual(response.headers["retry-after"], "2")
            self.assertIn("Retry-After", response.headers["access-control-expose-headers"])
            self.assertEqual(self.client.get(f"/api/v1/tasks/{self.task_id}/metrics").status_code, 200)
            self.assertEqual(self.client.get(f"/api/v1/tasks/{self.task_id}").status_code, 200)
        finally:
            first.close()
            first.close()
        self.empty_temporary_area()
        self.assertEqual(self.get().status_code, 200)

    def test_storage_failures_and_linked_temporary_directory_release_slot(self):
        self.completed()
        with patch.object(download_module.tempfile, "TemporaryDirectory", side_effect=OSError("/private disk full")):
            self.error(self.get(), 500, "STORAGE_UNAVAILABLE")
        destination = self.settings.data_dir / "downloads"
        destination.rmdir()
        destination.symlink_to(Path(self.temp.name))
        self.error(self.get(), 500, "STORAGE_UNAVAILABLE")
        destination.unlink()
        self.assertEqual(self.get().status_code, 200)
        self.empty_temporary_area()

    def test_pack_write_failure_is_storage_error_and_source_io_failure_is_artifact_error(self):
        self.completed()
        with patch.object(download_module.zipfile.ZipFile, "open", side_effect=OSError("disk full")):
            self.error(self.get(), 500, "STORAGE_UNAVAILABLE")
        self.empty_temporary_area()
        with patch("backend.app.services.task_files.os.pread", side_effect=PermissionError("source unreadable")):
            self.error(self.get(), 500, "INVALID_ARTIFACT")
        self.empty_temporary_area()
        self.assertEqual(self.get().status_code, 200)

    def test_mutation_after_audit_and_during_pack_is_rejected(self):
        self.completed()
        original_audit = download_module.verify_training_artifacts
        def corrupt_staging(output, **kwargs):
            result = original_audit(output, **kwargs)
            path = output / "adapter/adapter_model.safetensors"
            path.write_bytes(b"x" * path.stat().st_size)
            return result
        with patch.object(download_module, "verify_training_artifacts", side_effect=corrupt_staging):
            self.error(self.get(), 500, "INVALID_ARTIFACT")
        def corrupt_original(output, **kwargs):
            result = original_audit(output, **kwargs)
            path = self.output / "metrics.jsonl"
            path.write_bytes(path.read_bytes() + b" ")
            return result
        with patch.object(download_module, "verify_training_artifacts", side_effect=corrupt_original):
            self.error(self.get(), 500, "INVALID_ARTIFACT")
        self.empty_temporary_area()

    def test_failed_audit_uses_original_validator_and_cleans_staging(self):
        self.completed()
        from trainer.contracts import TrainingError
        with patch.object(download_module, "verify_training_artifacts", side_effect=TrainingError(
                TrainingFailure(code="INVALID_ARTIFACT", stage="reloading", message="CPU audit failure"))):
            self.error(self.get(), 500, "INVALID_ARTIFACT")
        self.empty_temporary_area()
        self.assertEqual(self.get().status_code, 200)

    def test_disconnect_send_failure_and_cancel_close_file_and_release_slot(self):
        self.completed()
        async def scenario(kind):
            prepared = self.service.prepare(UUID(self.task_id))
            response = AdapterResponse(prepared, UUID(self.task_id))
            sent = []
            async def receive():
                if kind == "disconnect":
                    await asyncio.sleep(0)
                    return {"type": "http.disconnect"}
                await asyncio.Event().wait()
            async def send(message):
                sent.append(message)
                if message["type"] == "http.response.body":
                    if kind == "send_failure": raise OSError("client closed")
                    if kind == "cancel": raise asyncio.CancelledError()
            try:
                with (patch.object(prepared.stream, "read", side_effect=OSError("read failed"))
                      if kind == "read_failure" else nullcontext()):
                    await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
            except BaseException as error:
                if kind == "disconnect": raise
                self.assertIsInstance(error, (BaseExceptionGroup, asyncio.CancelledError))
            self.assertTrue(prepared.stream.closed)
            self.assertFalse(any(m.get("type") == "http.response.body" and m.get("body", b"").startswith(b'{"error"') for m in sent))
        for kind in ("disconnect", "send_failure", "read_failure", "cancel"):
            asyncio.run(scenario(kind))
            self.empty_temporary_area()
        self.assertEqual(self.get().status_code, 200)

    def test_cancellation_while_preparing_eventually_cleans_without_releasing_slot_early(self):
        self.completed()
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        original = self.service.prepare
        original_close = download_module.PreparedDownload.close
        retained = []
        def blocked(task_id):
            prepared = original(task_id)
            retained.append(prepared)
            started.set()
            release.wait(5)
            return prepared
        def tracked_close(prepared):
            try:
                original_close(prepared)
            finally:
                finished.set()
        async def scenario():
            with patch.object(self.service, "prepare", side_effect=blocked), \
                    patch.object(download_module.PreparedDownload, "close", tracked_close):
                task = asyncio.create_task(prepare_response(self.service, UUID(self.task_id)))
                while not started.is_set(): await asyncio.sleep(0.005)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                with self.assertRaises(DatasetServiceError) as error: original(UUID(self.task_id))
                self.assertEqual(error.exception.code, "DOWNLOAD_BUSY")
                release.set()
                for _ in range(500):
                    if finished.is_set(): break
                    await asyncio.sleep(0.005)
                self.assertTrue(finished.is_set())
                self.assertTrue(retained[0].stream.closed)
        try:
            asyncio.run(scenario())
        finally:
            release.set()
        self.empty_temporary_area()
        self.assertEqual(self.get().status_code, 200)

    def test_success_error_openapi_headers_and_binary_body_are_consistent(self):
        operation = self.app.openapi()["paths"]["/api/v1/tasks/{task_id}/adapter"]["get"]
        self.assertEqual(set(operation["responses"]["200"]["content"]), {"application/zip"})
        self.assertIn("application/json", operation["responses"]["429"]["content"])
        self.assertIn("Retry-After", operation["responses"]["429"]["headers"])
        self.assertNotIn("application/json", operation["responses"]["200"]["content"])

    def test_download_import_and_actual_audit_work_without_gpu_dependencies(self):
        program = """
import sys
sys.path.insert(0,'tests')
from test_task_download import TaskDownloadTests
test=TaskDownloadTests()
test.setUp()
try:
    test.completed()
    assert test.get().status_code == 200
finally: test.tearDown()
for name in ('torch','numpy','transformers','datasets','peft','trl','accelerate'):
    assert name not in sys.modules, name
"""
        result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
