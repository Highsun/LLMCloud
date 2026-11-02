"""Known M0 schema, trusted legacy rows, backups, no-reset and rollback checks."""

from datetime import timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import inspect

from backend.app.core.database import create_database_engine, init_db
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION, TaskStatus
from backend.app.core.task_migration import (
    LEGACY_DDL, TaskSchemaMigrationRequired, _replace_table, migrate_tasks, require_task_schema,
)
from backend.app.models.entities import utcnow
from trainer.lora_config import TrainingConfig
from task_store_support import RAW, setup_store

ROOT = Path(__file__).resolve().parents[1]


class TaskMigrationTests(unittest.TestCase):
    def setUp(self):
        setup_store(self)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TABLE training_tasks")
            connection.execute(LEGACY_DDL)
            connection.execute("CREATE INDEX ix_training_tasks_dataset_id ON training_tasks(dataset_id)")
            connection.execute("CREATE INDEX ix_training_tasks_status ON training_tasks(status)")
        self.engine.dispose()

    def old_task(self, **update):
        row = dict(id=str(uuid4()), dataset_id=self.dataset_id,
            base_model="Qwen/Qwen2.5-0.5B-Instruct", status="PENDING",
            training_config=json.dumps(TrainingConfig().model_dump()), celery_task_id=str(uuid4()),
            progress=0.0, current_step=0, total_steps=0, output_path=None, error_message=None,
            created_at=(utcnow() - timedelta(seconds=10)).replace(tzinfo=None).isoformat(sep=" "),
            started_at=None, finished_at=None)
        row.update(update)
        with sqlite3.connect(self.database) as connection:
            columns = ",".join(row)
            placeholders = ",".join("?" for _ in row)
            connection.execute(f"INSERT INTO training_tasks ({columns}) VALUES ({placeholders})", tuple(row.values()))
        return row

    def mapping(self, row, **update):
        return {row["id"]: {"model_revision": DEFAULT_MODEL_REVISION, "runtime": {}, **update}}

    def test_empty_check_is_read_only_and_apply_has_restorable_backup(self):
        before = self.database.read_bytes()
        self.assertEqual(migrate_tasks(self.engine, self.data).state, "ready")
        self.assertEqual(before, self.database.read_bytes())
        self.assertFalse((self.data / "backups").exists())
        with self.assertRaises(TaskSchemaMigrationRequired):
            require_task_schema(self.engine)
        result = migrate_tasks(self.engine, self.data, apply=True)
        self.assertEqual(result.state, "applied")
        backup = Path(result.backup_path)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backup) as connection:
            self.assertNotIn("model_revision", [row[1] for row in connection.execute("PRAGMA table_info(training_tasks)")])
        require_task_schema(self.engine)
        self.assertEqual(migrate_tasks(self.engine, self.data, apply=True).state, "current")
        self.assertEqual(len(list((self.data / "backups").glob("*.sqlite3"))), 1)

    def test_missing_database_is_not_created_by_check_or_apply(self):
        missing = self.root / "absent.db"
        engine = create_database_engine(f"sqlite:///{missing}")
        try:
            for apply in (False, True):
                self.assertEqual(migrate_tasks(engine, self.data, apply=apply).state, "not_initialized")
                self.assertFalse(missing.exists())
        finally:
            engine.dispose()

    def test_startup_rejects_old_table_instead_of_create_all_migration(self):
        before = self.database.read_bytes()
        with self.assertRaises(TaskSchemaMigrationRequired):
            init_db(self.engine)
        self.assertEqual(before, self.database.read_bytes())

    def test_pending_row_requires_trusted_revision_and_preserves_references(self):
        row = self.old_task()
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE notes(task_id VARCHAR(36) REFERENCES training_tasks(id), note TEXT)")
            connection.execute("INSERT INTO notes VALUES (?,?)", (row["id"], "preserve"))
            connection.execute("CREATE INDEX task_custom_index ON training_tasks(base_model)")
        blocked = migrate_tasks(self.engine, self.data, apply=True)
        self.assertEqual(blocked.state, "blocked")
        self.assertEqual(blocked.issues[0]["code"], "trusted_snapshot_required")
        self.assertFalse((self.data / "backups").exists())
        result = migrate_tasks(self.engine, self.data, apply=True, snapshots=self.mapping(row))
        self.assertEqual(result.state, "applied")
        detail = self.repo.get_detail(row["id"])
        self.assertEqual(detail.status, TaskStatus.PENDING)
        self.assertEqual(detail.config.model_dump(), TrainingConfig().model_dump())
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT * FROM notes").fetchone(), (row["id"], "preserve"))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertIsNotNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='task_custom_index'").fetchone())
        spec = self.repo.claim(row["id"], uuid4(), "after-migration")
        self.assertEqual(spec.dataset_sha256, hashlib.sha256(RAW).hexdigest())
        columns = {column["name"]: column for column in inspect(self.engine).get_columns("training_tasks")}
        for name in ("model_revision", "dataset_key", "runtime_options", "celery_task_id"):
            self.assertFalse(columns[name]["nullable"])

    def test_explicit_celery_id_is_required_when_legacy_did_not_store_it(self):
        row = self.old_task(celery_task_id=None)
        report = migrate_tasks(self.engine, self.data, snapshots=self.mapping(row))
        self.assertEqual(report.issues[0]["code"], "celery_task_id_required")
        report = migrate_tasks(self.engine, self.data, apply=True,
                               snapshots=self.mapping(row, celery_task_id=str(uuid4())))
        self.assertEqual(report.state, "applied")

    def test_running_row_needs_explicit_offline_disposition_without_fake_owner(self):
        row = self.old_task(status="RUNNING", started_at=(utcnow() - timedelta(seconds=5)).replace(tzinfo=None).isoformat(sep=" "),
                            current_step=1, total_steps=2, progress=0.5)
        report = migrate_tasks(self.engine, self.data, snapshots=self.mapping(row))
        self.assertEqual(report.issues[0]["code"], "running_disposition_required")
        result = migrate_tasks(self.engine, self.data, apply=True, snapshots=self.mapping(row, interrupt_running=True))
        self.assertEqual(result.state, "applied")
        detail = self.repo.get_detail(row["id"])
        self.assertEqual((detail.status, detail.error_code, detail.current_step), (TaskStatus.FAILED, "WORKER_INTERRUPTED", 1))
        with sqlite3.connect(self.database) as connection:
            self.assertEqual(connection.execute("SELECT claim_token,worker_id FROM training_tasks").fetchone(), (None, None))

    def test_failed_row_requires_safe_failure_mapping(self):
        row = self.old_task(status="FAILED", error_message="private /home/example/file",
            finished_at=utcnow().replace(tzinfo=None).isoformat(sep=" "))
        report = migrate_tasks(self.engine, self.data, snapshots=self.mapping(row))
        self.assertEqual(report.issues[0]["code"], "safe_failure_mapping_required")
        result = migrate_tasks(self.engine, self.data, apply=True,
            snapshots=self.mapping(row, failure_code="TRAINING_FAILED", failure_message="历史训练失败。"))
        self.assertEqual(result.state, "applied")
        self.assertEqual(self.repo.get_detail(row["id"]).error_message, "历史训练失败。")

    def test_missing_and_changed_dataset_block_without_rewriting_any_rows(self):
        row = self.old_task()
        source = self.data / self.key
        for content in (b'{"instruction":"x","output":"z"}\n', None):
            if content is None:
                source.unlink()
            else:
                source.write_bytes(content)
            report = migrate_tasks(self.engine, self.data, apply=True, snapshots=self.mapping(row))
            self.assertEqual(report.state, "blocked")
            self.assertNotIn("model_revision", [c["name"] for c in inspect(self.engine).get_columns("training_tasks")])

    def test_completed_row_without_real_valid_bundle_is_not_promoted(self):
        row = self.old_task(status="COMPLETED", current_step=2, total_steps=2, progress=1.0,
            started_at=(utcnow() - timedelta(seconds=4)).replace(tzinfo=None).isoformat(sep=" "),
            finished_at=utcnow().replace(tzinfo=None).isoformat(sep=" "))
        report = migrate_tasks(self.engine, self.data, apply=True, snapshots=self.mapping(row))
        self.assertEqual(report.state, "blocked")
        self.assertEqual(report.issues[0]["code"], "invalid_task_or_artifacts")
        self.assertFalse((self.data / "backups").exists())

    def test_completed_migration_reuses_real_auditor_on_synthetic_cpu_bundle(self):
        from test_training_artifacts import TrainingArtifactTests
        bundle = TrainingArtifactTests()
        bundle.setUp()
        self.addCleanup(bundle.temp.cleanup)
        manifest = bundle.manifest
        target = self.data / "outputs" / str(manifest.task_id)
        shutil.copytree(bundle.root, target)
        value = manifest.model_dump(mode="json")
        value["train_dataset"] = {"sha256": hashlib.sha256(RAW).hexdigest(), "size_bytes": len(RAW), "row_count": 1}
        (target / "manifest.json").write_text(json.dumps(value))
        row = self.old_task(id=str(manifest.task_id), status="COMPLETED", progress=1.0, current_step=2, total_steps=2,
            output_path=str(target), training_config=json.dumps(manifest.config.model_dump()),
            created_at=(manifest.started_at - timedelta(seconds=1)).isoformat(),
            started_at=manifest.started_at.isoformat(), finished_at=manifest.finished_at.isoformat())
        before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
        report = migrate_tasks(self.engine, self.data, apply=True,
            snapshots=self.mapping(row, model_revision=manifest.model_revision, runtime=manifest.runtime.model_dump()))
        self.assertEqual(report.state, "applied", report.issues)
        self.assertEqual(self.repo.get_status(row["id"]), TaskStatus.COMPLETED)
        self.assertEqual(before, {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()})

    def test_unknown_columns_triggers_and_staging_objects_are_not_overwritten(self):
        with sqlite3.connect(self.database) as connection:
            connection.execute("CREATE TABLE training_tasks_m3_new(marker TEXT)")
        report = migrate_tasks(self.engine, self.data, apply=True)
        self.assertEqual(report.state, "blocked")
        self.assertEqual(report.issues[0]["code"], "staging_object_exists")
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TABLE training_tasks_m3_new")
            connection.execute("CREATE TRIGGER custom_trigger AFTER INSERT ON training_tasks BEGIN SELECT 1; END")
        self.assertEqual(migrate_tasks(self.engine, self.data, apply=True).state, "unsupported_schema")
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP TRIGGER custom_trigger")
            connection.execute("ALTER TABLE training_tasks ADD COLUMN custom TEXT")
        self.assertEqual(migrate_tasks(self.engine, self.data, apply=True).state, "unsupported_schema")

    def test_failure_after_drop_rolls_back_schema_rows_and_indexes(self):
        row = self.old_task()
        class FailRename:
            def __init__(self, connection): self.connection = connection
            def execute(self, sql, *args):
                if sql.startswith("ALTER TABLE training_tasks_m3_new"):
                    raise sqlite3.OperationalError("injected rename failure")
                return self.connection.execute(sql, *args)
            def executemany(self, *args): return self.connection.executemany(*args)
        with patch("backend.app.core.task_migration._replace_table",
                   side_effect=lambda connection, rows: _replace_table(FailRename(connection), rows)):
            with self.assertRaises(sqlite3.OperationalError):
                migrate_tasks(self.engine, self.data, apply=True, snapshots=self.mapping(row))
        with sqlite3.connect(self.database) as connection:
            connection.row_factory = sqlite3.Row
            self.assertEqual(dict(connection.execute("SELECT * FROM training_tasks").fetchone()), row)
            self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='training_tasks_m3_new'").fetchone())
        self.assertEqual(len(list((self.data / "backups").glob("*.sqlite3"))), 1)

    def test_unknown_mappings_and_fk_corruption_block_all_rows(self):
        row = self.old_task()
        mapping = {**self.mapping(row), str(uuid4()): {"model_revision": "a" * 40, "runtime": {}}}
        report = migrate_tasks(self.engine, self.data, snapshots=mapping)
        self.assertIn("unknown_snapshot_mapping", [issue["code"] for issue in report.issues])
        with sqlite3.connect(self.database) as connection:
            connection.execute("UPDATE training_tasks SET dataset_id=?", (str(uuid4()),))
        report = migrate_tasks(self.engine, self.data, snapshots=self.mapping(row))
        self.assertIn("existing_foreign_key_violation", [issue["code"] for issue in report.issues])

    def test_new_schema_missing_required_index_is_rejected(self):
        migrate_tasks(self.engine, self.data, apply=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP INDEX uq_training_tasks_idempotency_key")
        with self.assertRaises(TaskSchemaMigrationRequired):
            require_task_schema(self.engine)
        self.assertEqual(migrate_tasks(self.engine, self.data).state, "unsupported_schema")

    def test_partial_unique_index_cannot_impersonate_required_request_protection(self):
        migrate_tasks(self.engine, self.data, apply=True)
        with sqlite3.connect(self.database) as connection:
            connection.execute("DROP INDEX uq_training_tasks_idempotency_key")
            connection.execute("CREATE UNIQUE INDEX uq_training_tasks_idempotency_key ON training_tasks(idempotency_key) WHERE status='PENDING'")
        with self.assertRaises(TaskSchemaMigrationRequired):
            require_task_schema(self.engine)

    def test_cli_check_and_explicit_apply_use_isolated_database(self):
        command = [sys.executable, "scripts/migrate_tasks.py", "--database-url", f"sqlite:///{self.database}",
                   "--data-dir", str(self.data)]
        for mode, expected in (("--check", "ready"), ("--apply", "applied"), ("--check", "current")):
            result = subprocess.run([*command, mode], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["state"], expected)


if __name__ == "__main__":
    unittest.main()
