"""Dataset persistence independent of multipart/HTTP and GPU libraries.

Each operation owns a fresh session. Call create with a binary stream positioned
at its beginning; the caller owns that stream. The synchronous API can be called
from a threadpool by future async HTTP handlers.
"""

import logging
import os
from pathlib import Path
from typing import BinaryIO
from collections.abc import Callable
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, TimeoutError as SQLTimeoutError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, get_settings
from backend.app.core.database import SessionLocal
from backend.app.core.dataset_contract import MAX_UPLOAD_NAME_BYTES
from backend.app.models.dataset_schemas import DatasetDetail, DatasetListQuery, DatasetPage, DatasetSummary, DatasetUploadMetadata
from backend.app.models.entities import Dataset
from backend.app.models.error_schemas import ApiErrorCode, ErrorDetail
from backend.app.services.dataset_paths import dataset_key, resolve_dataset_path, sanitize_filename
from backend.app.services.errors import DatasetServiceError, validation_failure
from trainer.dataset import DatasetScanner, DatasetValidationError, READ_CHUNK_BYTES, scan_dataset

logger = logging.getLogger(__name__)


def _field_failure(code, message, field="name", *, dataset=False):
    return DatasetServiceError(
        ApiErrorCode.INVALID_DATASET if dataset else ApiErrorCode.VALIDATION_ERROR,
        message, 422,
        [ErrorDetail(loc=["body", field], code=code, message=message, line=None, column=None)],
    )


def _database_failure(error):
    if isinstance(error, (OperationalError, SQLTimeoutError)):
        return DatasetServiceError(ApiErrorCode.DATABASE_UNAVAILABLE, "数据存储暂时不可用，请稍后重试。", 503)
    return DatasetServiceError(ApiErrorCode.INTERNAL_ERROR, "数据集操作失败，请联系维护人员。", 500)


def _summary(row: Dataset) -> dict:
    return {"id": row.id, "name": row.name, "format": "alpaca_jsonl", "size_bytes": row.size_bytes,
            "row_count": row.row_count, "created_at": row.created_at}


def _detail(row: Dataset) -> DatasetDetail:
    return DatasetDetail(**_summary(row), original_filename=row.original_filename, sha256=row.sha256)


class DatasetService:
    def __init__(self, settings: Settings | None = None, session_factory: Callable[[], Session] | None = None):
        self.settings = settings or get_settings()
        self.session_factory = session_factory or SessionLocal

    def _directories(self) -> tuple[Path, Path]:
        root = self.settings.data_dir.resolve()
        datasets = root / "datasets"
        temporary = datasets / ".tmp"
        if datasets.is_symlink() or temporary.is_symlink():
            raise OSError("Dataset directories must not be symlinks")
        temporary.mkdir(parents=True, exist_ok=True, mode=0o700)
        return datasets, temporary

    def _close_session(self, session) -> None:
        if session is not None:
            try:
                session.close()
            except Exception as error:
                logger.error("dataset_session_close_failed reason=%s", type(error).__name__)

    def _confirm_commit(self, identifier: str, key: str, sha256: str) -> bool | None:
        """Read on a fresh connection; None means the commit outcome is unknown."""
        probe = None
        try:
            probe = self.session_factory()
            row = probe.get(Dataset, identifier)
            if row is None:
                return False
            return True if row.storage_path == key and row.sha256 == sha256 else None
        except Exception:
            return None
        finally:
            self._close_session(probe)

    def _cleanup(self, identifier, temporary, temporary_owned, final, final_owned) -> None:
        # Never recursively remove directories, and never delete another upload.
        paths = ([temporary] if temporary_owned else []) + ([final] if final_owned else [])
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                logger.error("dataset_cleanup_failed dataset_id=%s reason=%s", identifier, type(error).__name__)
        if final_owned:
            try:
                final.parent.rmdir()
            except OSError as error:
                logger.error("dataset_directory_cleanup_failed dataset_id=%s reason=%s", identifier, type(error).__name__)

    def create(self, source: BinaryIO, *, filename: str, name: str | None = None) -> DatasetDetail:
        try:
            original = sanitize_filename(filename)
        except ValueError as error:
            code = str(error)
            if code == "unsupported_extension":
                raise _field_failure(code, "仅支持 .jsonl 数据文件。", "file", dataset=True) from None
            raise _field_failure("invalid_filename", "文件名不符合要求。", "file") from None
        try:
            if name is not None and len(name.encode("utf-8")) > MAX_UPLOAD_NAME_BYTES:
                raise _field_failure("out_of_range", "名称编码长度超过限制。")
            metadata = DatasetUploadMetadata(name=name)
        except ValidationError as error:
            reason = error.errors(include_input=False, include_context=False, include_url=False)[0]['type']
            code = {'string_too_short': 'blank', 'string_too_long': 'out_of_range'}.get(reason, 'invalid_type')
            raise _field_failure(code, "名称必须是合法的非空文本，最多 255 个字符。") from None
        except UnicodeError:
            raise _field_failure("invalid_encoding", "名称必须为有效 UTF-8 文本。") from None
        except AttributeError:
            raise _field_failure("invalid_type", "名称必须是文本。") from None

        identifier = str(uuid4())
        key = dataset_key(identifier)
        temporary = final = None
        temporary_owned = final_owned = False
        session = None
        commit_started = committed = False
        scanner = DatasetScanner()
        try:
            _, staging = self._directories()
            temporary = staging / f"{identifier}.part"
            final = resolve_dataset_path(self.settings.data_dir, key)
            descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            temporary_owned = True
            with os.fdopen(descriptor, "wb") as output:
                while chunk := source.read(READ_CHUNK_BYTES):
                    scanner.feed(chunk)
                    if output.write(chunk) != len(chunk):
                        raise OSError("Incomplete dataset write")
                scanner.finish()
                output.flush()
                os.fsync(output.fileno())
            stats = scanner.stats
            final.parent.mkdir(mode=0o700)
            final_owned = True
            temporary.rename(final)
            session = self.session_factory()
            row = Dataset(id=identifier, name=metadata.name or original, original_filename=original,
                          sha256=stats.sha256, storage_path=key, size_bytes=stats.size_bytes, row_count=stats.row_count)
            session.add(row)
            session.flush()
            result = _detail(row)  # Validate the response before committing.
            commit_started = True
            session.commit()
            committed = True
            return result
        except BaseException as error:
            if session is not None:
                try:
                    session.rollback()
                except Exception as rollback_error:
                    logger.error("dataset_rollback_failed dataset_id=%s reason=%s", identifier, type(rollback_error).__name__)
            outcome = self._confirm_commit(identifier, key, scanner.stats.sha256) if commit_started else False
            if outcome is True:
                committed = True
                logger.warning("dataset_commit_recovered dataset_id=%s", identifier)
                if isinstance(error, Exception):
                    return result
            if not committed and outcome is not None:
                self._cleanup(identifier, temporary, temporary_owned, final, final_owned)
            if outcome is None:
                logger.error("dataset_commit_uncertain dataset_id=%s storage_key=%s", identifier, key)
            if not isinstance(error, Exception):
                raise
            if outcome is None:
                raise DatasetServiceError(ApiErrorCode.DATABASE_UNAVAILABLE, "提交结果暂时无法确认，请刷新列表后检查。", 503) from None
            if isinstance(error, DatasetServiceError):
                raise
            if isinstance(error, DatasetValidationError):
                raise validation_failure(error) from None
            logger.error("dataset_create_failed dataset_id=%s reason=%s", identifier, type(error).__name__)
            if isinstance(error, OSError):
                raise DatasetServiceError(ApiErrorCode.STORAGE_UNAVAILABLE, "数据文件暂时无法保存。", 503) from None
            raise _database_failure(error) from None
        finally:
            self._close_session(session)

    def get(self, dataset_id: str | UUID) -> DatasetDetail:
        try:
            identifier = str(UUID(str(dataset_id)))
        except (ValueError, TypeError, AttributeError):
            raise DatasetServiceError(ApiErrorCode.VALIDATION_ERROR, "数据集 ID 必须为 UUID。", 422,
                [ErrorDetail(loc=["path", "dataset_id"], code="invalid_type", message="必须为 UUID。", line=None, column=None)]) from None
        try:
            with self.session_factory() as session:
                row = session.get(Dataset, identifier)
                if row is None:
                    raise DatasetServiceError(ApiErrorCode.DATASET_NOT_FOUND, "数据集不存在。", 404)
                return _detail(row)
        except DatasetServiceError:
            raise
        except Exception as error:
            logger.error("dataset_get_failed dataset_id=%s reason=%s", identifier, type(error).__name__)
            raise _database_failure(error) from None

    def list(self, query: DatasetListQuery | None = None) -> DatasetPage:
        query = query or DatasetListQuery()
        try:
            with self.session_factory() as session:
                total = session.scalar(select(func.count()).select_from(Dataset))
                pages = (total + query.page_size - 1) // query.page_size
                items = []
                if query.page <= pages:
                    rows = session.scalars(select(Dataset).order_by(Dataset.created_at.desc(), Dataset.id.desc())
                        .offset((query.page - 1) * query.page_size).limit(query.page_size))
                    items = [DatasetSummary(**_summary(row)) for row in rows]
                return DatasetPage(items=items, total=total, page=query.page, page_size=query.page_size, total_pages=pages)
        except Exception as error:
            logger.error("dataset_list_failed reason=%s", type(error).__name__)
            raise _database_failure(error) from None

    def audit_storage(self, *, verify_hash: bool = False) -> dict:
        """Read-only candidates; run with writers stopped before manual repair."""
        with self.session_factory() as session:
            rows = list(session.scalars(select(Dataset)))
        report = {key: [] for key in ("temporary_candidates", "orphan_candidates", "missing_files", "invalid_storage_keys", "unreadable_files", "checksum_mismatches")}
        referenced = set()
        for row in rows:
            try:
                expected_key = dataset_key(row.id)
                if row.storage_path != expected_key:
                    raise ValueError("Mismatched dataset key")
                path = resolve_dataset_path(self.settings.data_dir, row.storage_path)
                referenced.add(row.storage_path)
            except ValueError:
                report["invalid_storage_keys"].append(row.id)
                continue
            if not path.exists():
                report["missing_files"].append(row.id)
            elif verify_hash:
                try:
                    stats = scan_dataset(path)
                    if stats.sha256 != row.sha256 or stats.size_bytes != row.size_bytes or stats.row_count != row.row_count:
                        report["checksum_mismatches"].append(row.id)
                except (OSError, DatasetValidationError):
                    report["unreadable_files"].append(row.id)
        root = self.settings.data_dir / "datasets"
        if root.is_symlink() or (root / ".tmp").is_symlink():
            raise ValueError("Dataset directories must not be symlinks")
        for path in root.glob(".tmp/*.part"):
            report["temporary_candidates"].append(path.relative_to(self.settings.data_dir).as_posix())
        for path in root.glob("*/train.jsonl"):
            key = path.relative_to(self.settings.data_dir).as_posix()
            if key not in referenced:
                report["orphan_candidates"].append(key)
        return report
