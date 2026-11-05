"""CPU download preparation: bounded snapshot, existing audit, verified ZIP."""

from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile
import threading
import zipfile

from backend.app.core.observability_contract import (
    DOWNLOAD_CHUNK_BYTES, MAX_CONCURRENT_DOWNLOADS, MAX_DOWNLOAD_BYTES, MAX_DOWNLOAD_MANIFEST_BYTES,
)
from backend.app.core.observability_protocols import CompletedArtifactNotFound, CompletedArtifactNotReady
from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.services.errors import DatasetServiceError
from backend.app.services.task_files import open_task_directory, open_task_file
from backend.app.services.task_log_projection import load_json
from backend.app.services.tasks import database_error
from trainer.artifacts import ADAPTER_FILES, TOKENIZER_FILES, REQUIRED, verify_training_artifacts
from trainer.contracts import TrainingError, TrainingManifest


def download_error(code):
    status, message = {
        "INVALID_ARTIFACT": (500, "训练产物不完整或与完成记录不一致。"),
        "ARTIFACT_TOO_LARGE": (413, "训练产物超过单次下载大小上限。"),
        "DOWNLOAD_BUSY": (429, "已有下载正在处理，请稍后重试。"),
        "STORAGE_UNAVAILABLE": (500, "下载临时存储不可用。"),
    }[code]
    return DatasetServiceError(ApiErrorCode(code), message, status)


@contextmanager
def _source(root, parts):
    try:
        with open_task_file(root, parts) as source:
            yield source
    except OSError:
        raise download_error("INVALID_ARTIFACT") from None


def _fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _manifest(settings, completed):
    with _source(settings.data_dir, ("outputs", str(completed.spec.task_id), "manifest.json")) as source:
        if not 0 < source.info.st_size <= MAX_DOWNLOAD_MANIFEST_BYTES:
            raise download_error("INVALID_ARTIFACT")
        raw = source.read(source.info.st_size, 0)
    try:
        if hashlib.sha256(raw).hexdigest() != completed.manifest_sha256:
            raise ValueError("Manifest hash mismatch")
        manifest = TrainingManifest.model_validate(load_json(raw))
        spec = completed.spec
        if (manifest.task_id != spec.task_id or manifest.base_model != spec.base_model
                or manifest.model_revision != spec.model_revision or manifest.config != spec.config
                or manifest.runtime != spec.runtime or manifest.validation_dataset is not None
                or manifest.train_dataset.sha256 != spec.dataset_sha256
                or manifest.train_dataset.size_bytes != spec.dataset_size_bytes
                or manifest.train_dataset.row_count != spec.dataset_row_count
                or manifest.summary != completed.training_summary):
            raise ValueError("Completion snapshot mismatch")
        allowed = {f"adapter/{name}" for name in ADAPTER_FILES} | {f"tokenizer/{name}" for name in TOKENIZER_FILES}
        allowed |= {"metrics.jsonl", "training_config.json"}
        if any(item.path not in allowed for item in manifest.artifacts):
            raise ValueError("Unexpected artifact layout")
        if not REQUIRED.issubset({item.path for item in manifest.artifacts}):
            raise ValueError("Missing required artifacts")
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise download_error("INVALID_ARTIFACT") from None
    return manifest, raw


def _inventory(settings, task_id):
    """Metadata only, with fixed name/count bounds; never descend checkpoints."""
    values = {}
    try:
        with open_task_directory(settings.data_dir, ("outputs", str(task_id))) as root:
            with os.scandir(root) as entries:
                names = set()
                for entry in entries:
                    if entry.name not in {"adapter", "tokenizer", "checkpoints", "training_config.json", "metrics.jsonl", "manifest.json"}:
                        raise ValueError("Unexpected task entry")
                    names.add(entry.name)
            for name in ("adapter", "tokenizer", "checkpoints"):
                if name == "checkpoints" and name not in names:
                    continue
                with open_task_directory(settings.data_dir, ("outputs", str(task_id), name)) as directory:
                    if name == "checkpoints":
                        continue
                    allowed = ADAPTER_FILES if name == "adapter" else TOKENIZER_FILES
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            if entry.name not in allowed:
                                raise ValueError("Unexpected deliverable")
                            values[f"{name}/{entry.name}"] = entry.stat(follow_symlinks=False)
            for name in ("manifest.json", "training_config.json", "metrics.jsonl"):
                values[name] = os.stat(name, dir_fd=root, follow_symlinks=False)
        if any(not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size <= 0 for info in values.values()):
            raise ValueError("Unsafe source file")
    except (OSError, ValueError):
        raise download_error("INVALID_ARTIFACT") from None
    if sum(info.st_size for info in values.values()) > MAX_DOWNLOAD_BYTES:
        raise download_error("ARTIFACT_TOO_LARGE")
    return {name: _fingerprint(info) for name, info in values.items()}


def _copy_source(settings, task_id, record, target):
    digest = hashlib.sha256()
    try:
        destination = target.open("xb")
    except OSError:
        raise download_error("STORAGE_UNAVAILABLE") from None
    with destination, _source(settings.data_dir, ("outputs", str(task_id), *record.path.split("/"))) as source:
        if source.info.st_size != record.size_bytes:
            raise download_error("INVALID_ARTIFACT")
        offset = 0
        while offset < record.size_bytes:
            chunk = source.read(min(DOWNLOAD_CHUNK_BYTES, record.size_bytes - offset), offset)
            digest.update(chunk)
            try:
                destination.write(chunk)
            except OSError:
                raise download_error("STORAGE_UNAVAILABLE") from None
            offset += len(chunk)
        if digest.hexdigest() != record.sha256:
            raise download_error("INVALID_ARTIFACT")


def _pack(work, task_id, manifest, manifest_raw, archive):
    """Rehash the exact bytes fed into ZIP, including the original manifest."""
    members = [(item.path, item.size_bytes, item.sha256) for item in manifest.artifacts]
    members.append(("manifest.json", len(manifest_raw), hashlib.sha256(manifest_raw).hexdigest()))
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        for name, size, expected in members:
            digest = hashlib.sha256()
            with _source(work, ("outputs", str(task_id), *name.split("/"))) as source:
                if source.info.st_size != size:
                    raise download_error("INVALID_ARTIFACT")
                try:
                    with bundle.open(f"{task_id}/{name}", "w") as destination:
                        offset = 0
                        while offset < size:
                            try:
                                chunk = source.read(min(DOWNLOAD_CHUNK_BYTES, size - offset), offset)
                            except OSError:
                                raise download_error("INVALID_ARTIFACT") from None
                            digest.update(chunk)
                            destination.write(chunk)
                            offset += len(chunk)
                except OSError:
                    raise download_error("STORAGE_UNAVAILABLE") from None
                if digest.hexdigest() != expected:
                    raise download_error("INVALID_ARTIFACT")
    archive.flush()
    archive.seek(0)
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None or len(bundle.infolist()) != len(members):
            raise download_error("INVALID_ARTIFACT")
    archive.seek(0)


@dataclass
class PreparedDownload:
    stream: object
    size: int
    resources: ExitStack

    def __post_init__(self):
        self._close_lock = threading.Lock()
        self._closed = False

    def close(self):
        with self._close_lock:
            if not self._closed:
                self._closed = True
                self.resources.close()


class TaskDownloadService:
    def __init__(self, settings, repository):
        self.settings, self.repository = settings, repository
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_DOWNLOADS)

    def prepare(self, task_id):
        try:
            completed = self.repository.get_completed_artifact(task_id)
        except CompletedArtifactNotFound:
            raise DatasetServiceError(ApiErrorCode.TASK_NOT_FOUND, "训练任务不存在。", 404) from None
        except CompletedArtifactNotReady:
            raise DatasetServiceError(ApiErrorCode.ARTIFACT_NOT_READY, "训练任务尚未完成，不能下载。", 409) from None
        except TaskStoreError:
            raise database_error() from None
        if not self._slots.acquire(blocking=False):
            raise download_error("DOWNLOAD_BUSY")
        resources = ExitStack()
        resources.callback(self._slots.release)
        try:
            manifest, raw = _manifest(self.settings, completed)
            if len(raw) + sum(item.size_bytes for item in manifest.artifacts) > MAX_DOWNLOAD_BYTES:
                raise download_error("ARTIFACT_TOO_LARGE")
            before = _inventory(self.settings, task_id)
            expected = {item.path: item.size_bytes for item in manifest.artifacts}
            expected["manifest.json"] = len(raw)
            if {name: info[2] for name, info in before.items()} != expected:
                raise download_error("INVALID_ARTIFACT")
            with open_task_directory(self.settings.data_dir) as root:
                try:
                    os.mkdir("downloads", mode=0o700, dir_fd=root)
                except FileExistsError:
                    pass
            directory = resources.enter_context(open_task_directory(self.settings.data_dir, ("downloads",)))
            if os.fstat(directory).st_mode & 0o022:
                raise download_error("STORAGE_UNAVAILABLE")
            # Keep the parent fd alive through response cleanup; temporary area
            # allocation/cleanup cannot be redirected by replacing downloads/.
            temporary = resources.enter_context(tempfile.TemporaryDirectory(prefix="llmcloud-", dir=f"/proc/self/fd/{directory}"))
            work = Path(temporary).resolve(strict=True)
            output = work / "outputs" / str(task_id)
            for name in ("adapter", "tokenizer"):
                (output / name).mkdir(parents=True)
            (output / "manifest.json").write_bytes(raw)
            for item in manifest.artifacts:
                _copy_source(self.settings, task_id, item, output / item.path)
            if _inventory(self.settings, task_id) != before:
                raise download_error("INVALID_ARTIFACT")
            verified = verify_training_artifacts(output, outputs_root=work / "outputs",
                expected_task_id=task_id, expected_revision=completed.spec.model_revision)
            if verified.manifest != manifest:
                raise download_error("INVALID_ARTIFACT")
            stream = resources.enter_context((work / "adapter.zip").open("x+b"))
            _pack(work, task_id, manifest, raw, stream)
            if _inventory(self.settings, task_id) != before:
                raise download_error("INVALID_ARTIFACT")
            size = os.fstat(stream.fileno()).st_size
            return PreparedDownload(stream, size, resources.pop_all())
        except (TrainingError, zipfile.BadZipFile):
            raise download_error("INVALID_ARTIFACT") from None
        except OSError:
            raise download_error("STORAGE_UNAVAILABLE") from None
        finally:
            resources.close()


class PreparationTicket:
    """If an awaiting request is cancelled, the worker owns eventual cleanup."""
    def __init__(self, service, task_id):
        self.service, self.task_id = service, task_id
        self._lock = threading.Lock()
        self._abandoned = False
        self._prepared = None

    def run(self):
        prepared = self.service.prepare(self.task_id)
        with self._lock:
            abandoned = self._abandoned
            if not abandoned:
                self._prepared = prepared
        if abandoned:
            prepared.close()
            return None
        return prepared

    def abandon(self):
        with self._lock:
            self._abandoned = True
            return self._prepared
