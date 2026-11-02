"""Explicit offline SQLite reconciliation; never publishes messages or runs training."""

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.app.core.task_contract import TaskStatus
from backend.app.core.task_migration import _decode, _state
from backend.app.core.worker_lock import WorkerInstanceLock, WorkerLockBusy, WorkerLockError
from backend.app.services.task_records import execution_spec, identifier, task_detail
from trainer.artifacts import sha256, verify_training_artifacts
from trainer.contracts import TrainingError

ACTIVE = (TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING)
JSON_COLUMNS = {"training_summary"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(row):
    return hashlib.sha256(_json(row).encode("utf-8")).hexdigest()


def _dbtime(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(sep=" ", timespec="microseconds")


@dataclass
class ReconciliationItem:
    row: dict
    target: str | None
    reason: str
    values: dict
    blocked: bool = False

    def public(self):
        return {"task_id": self.row["id"], "from_status": self.row["status"],
                "to_status": self.target, "reason": self.reason,
                "outcome": "blocked" if self.blocked else "proposed" if self.target else "unchanged"}

    def signature(self):
        return self.target, self.reason, self.values, self.blocked


def _inspect(row, data_dir, now):
    if row.get("status") is None:
        return ReconciliationItem(row, None, "task_not_found", {}, True)
    try:
        detail = task_detail(row)
    except (ValueError, TypeError, KeyError):
        return ReconciliationItem(row, None, "invalid_task_record", {}, True)
    if detail.status not in ACTIVE:
        return ReconciliationItem(row, None, "terminal_preserved", {})
    outputs = data_dir / "outputs"
    root = outputs / str(detail.id)
    if outputs.is_symlink() or (outputs.exists() and not outputs.is_dir()) or root.is_symlink():
        return ReconciliationItem(row, None, "unsafe_output_path", {}, True)
    reason, verified = "artifacts_missing", None
    if root.exists():
        try:
            verified = verify_training_artifacts(root, outputs_root=outputs,
                expected_task_id=detail.id, expected_revision=detail.model_revision)
        except TrainingError:
            reason = "artifacts_invalid"
    if verified is not None:
        manifest, spec = verified.manifest, execution_spec(row)
        matching = (manifest.base_model == spec.base_model and manifest.config == spec.config
            and manifest.runtime == spec.runtime and manifest.train_dataset.sha256 == spec.dataset_sha256
            and manifest.train_dataset.size_bytes == spec.dataset_size_bytes
            and manifest.train_dataset.row_count == spec.dataset_row_count
            and manifest.validation_dataset is None
            and (detail.total_steps is None or detail.total_steps == manifest.summary.total_steps)
            and detail.current_step <= manifest.summary.completed_steps
            and (detail.started_at is None or manifest.started_at >= detail.started_at)
            and manifest.finished_at <= now)
        if matching and detail.status == TaskStatus.RUNNING:
            values = dict(status=TaskStatus.COMPLETED, current_step=manifest.summary.completed_steps,
                total_steps=manifest.summary.total_steps, progress=1.0, output_path=f"outputs/{detail.id}",
                manifest_sha256=sha256(root / "manifest.json"),
                training_summary=manifest.summary.model_dump(mode="json"),
                finished_at=_dbtime(manifest.finished_at), error_code=None, error_message=None)
            task_detail({**row, **values})
            return ReconciliationItem(row, TaskStatus.COMPLETED, "verified_completion", values)
        # A complete but unclaimed bundle is anomalous: never invent its owner/start.
        if detail.status != TaskStatus.RUNNING:
            return ReconciliationItem(row, None, "unclaimed_success_artifacts", {}, True)
        reason = "artifact_snapshot_mismatch"
    interrupted = detail.status == TaskStatus.RUNNING
    values = dict(status=TaskStatus.FAILED,
        error_code="WORKER_INTERRUPTED" if interrupted else "TASK_ABANDONED",
        error_message="离线对账确认训练进程已停止，任务未完成。" if interrupted else "离线对账结束未完成派发或排队的任务，未自动重投。",
        finished_at=_dbtime(now))
    task_detail({**row, **values})
    return ReconciliationItem(row, TaskStatus.FAILED, reason, values)


def _rows(connection, task_ids):
    if task_ids is None:
        return [_decode(row) for row in connection.execute("SELECT * FROM training_tasks ORDER BY created_at,id")]
    rows = []
    for task_id in task_ids:
        row = connection.execute("SELECT * FROM training_tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            rows.append({"id": task_id, "status": None})
        else:
            rows.append(_decode(row))
    return rows


def _commit(connection):
    connection.commit()


def _update(connection, item):
    """No artifact IO while holding the short SQLite write transaction."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        raw = connection.execute("SELECT * FROM training_tasks WHERE id=?", (item.row["id"],)).fetchone()
        if raw is None or _fingerprint(_decode(raw)) != _fingerprint(item.row):
            connection.rollback()
            return False
        task_detail({**item.row, **item.values})
        assignments = ",".join(f"{name}=?" for name in item.values)
        values = [_json(value) if name in JSON_COLUMNS else value for name, value in item.values.items()]
        count = connection.execute(f"UPDATE training_tasks SET {assignments} WHERE id=? AND status=? AND claim_token IS ?",
            (*values, item.row["id"], item.row["status"], item.row["claim_token"])).rowcount
        if count != 1:
            connection.rollback()
            return False
        _commit(connection)
        return True
    except BaseException:
        connection.rollback()
        raise


def _apply(connection, items, report, data_dir, log_dir, now):
    path = log_dir / f"reconciliation-{uuid4()}.jsonl"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    report["audit_log"] = str(path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as audit:
        def record(event, **fields):
            audit.write(_json({"event": event, "recorded_at": datetime.now(timezone.utc).isoformat(), **fields}) + "\n")
            audit.flush()
            os.fsync(audit.fileno())
        record("plan", report=report)
        for item, result in zip(items, report["items"]):
            if item.target is None:
                continue
            # Services are stopped and the instance lock stays held; detect accidental
            # filesystem changes again before the DB CAS, without long SQL locks.
            if _inspect(item.row, data_dir, now).signature() != item.signature():
                result["outcome"] = "artifacts_changed"
                report["state"] = "partial" if report["applied_count"] else "blocked"
                record("stopped", item=result)
                break
            record("intent", item=result, before_sha256=_fingerprint(item.row))
            try:
                changed = _update(connection, item)
            except Exception:
                result["outcome"] = "confirmation_unknown"
                report["state"] = "uncertain"
                record("stopped", item=result)
                break
            if not changed:
                result["outcome"] = "database_changed"
                report["state"] = "partial" if report["applied_count"] else "blocked"
                record("stopped", item=result)
                break
            result["outcome"] = "applied"
            report["applied_count"] += 1
            record("applied", item=result)
        else:
            report["state"] = "applied"
        record("result", report=report)
    return report


def reconcile_tasks(engine, data_dir, log_dir, *, apply=False, services_stopped=False, task_ids=None):
    """Check is read-only; apply requires operator shutdown acknowledgement + flock.

    Reports are proposals, never evidence that an online task has timed out.
    Only the current SQLite schema is supported. No table creation/migration.
    """
    now = datetime.now(timezone.utc)
    report = dict(version="1.0.0", mode="apply" if apply else "check", state="current",
        checked_at=now.isoformat(), services_stopped_acknowledged=bool(services_stopped),
        instance_lock_acquired=False, items=[], applied_count=0, audit_log=None)
    if apply and not services_stopped:
        return {**report, "state": "blocked", "code": "services_stopped_required"}
    if engine.dialect.name != "sqlite" or engine.url.query:
        return {**report, "state": "blocked", "code": "unsupported_database"}
    database = engine.url.database
    if not database or database == ":memory:" or not Path(database).is_file():
        return {**report, "state": "not_initialized"}
    data_dir, log_dir = Path(data_dir).absolute(), Path(log_dir).absolute()
    selected = None if task_ids is None else list(dict.fromkeys(identifier(value) for value in task_ids))

    def run():
        uri = Path(database).resolve().as_uri() + ("?mode=rw" if apply else "?mode=ro")
        with closing(sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN")
            state = _state(connection)
            if state != "current":
                connection.rollback()
                return {**report, "state": "not_initialized" if state == "not_initialized" else "blocked",
                        "code": "task_schema_migration_required"}
            rows = _rows(connection, selected)
            connection.rollback()
            items = [_inspect(row, data_dir, now) for row in rows]
            report["items"] = [item.public() for item in items]
            report["state"] = "blocked" if any(item.blocked for item in items) else "ready" if any(item.target for item in items) else "current"
            if apply and report["state"] == "ready":
                return _apply(connection, items, report, data_dir, log_dir, now)
            return report
    try:
        if not apply:
            return run()
        with WorkerInstanceLock(log_dir):
            report["instance_lock_acquired"] = True
            return run()
    except WorkerLockBusy:
        return {**report, "state": "blocked", "code": "instance_lock_busy"}
    except WorkerLockError:
        return {**report, "state": "blocked", "code": "instance_lock_unavailable"}
    except Exception:
        # A log/fsync failure after a DB commit cannot undo that commit. Keep the
        # known count and require a fresh check, never try a failure fallback.
        state = "uncertain" if report["applied_count"] or report["state"] == "uncertain" else "error"
        return {**report, "state": state, "code": "reconciliation_failed"}
