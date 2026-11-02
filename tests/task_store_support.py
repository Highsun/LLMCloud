"""Isolated SQL fixtures; metadata completion is not evidence of real training."""

import hashlib
from pathlib import Path
import tempfile
from uuid import uuid4

from sqlalchemy.orm import sessionmaker

from backend.app.core.database import create_database_engine, init_db
from backend.app.core.task_contract import DEFAULT_MODEL_REVISION
from backend.app.models.entities import Dataset, utcnow
from backend.app.models.task_schemas import TaskCreate
from backend.app.services.task_repository import SqlTaskRepository
from trainer.contracts import RuntimeOptions, TrainingProgress, TrainingSummary

RAW = b'{"instruction":"x","output":"y"}\n'


def setup_store(test):
    temp = tempfile.TemporaryDirectory()
    test.addCleanup(temp.cleanup)
    test.root = Path(temp.name)
    test.data = test.root / "data"
    test.data.mkdir()
    test.database = test.root / "metadata.db"
    test.engine = create_database_engine(f"sqlite:///{test.database}")
    test.addCleanup(test.engine.dispose)
    init_db(test.engine)
    test.sessions = sessionmaker(bind=test.engine, expire_on_commit=False)
    test.repo = SqlTaskRepository(test.sessions)
    test.dataset_id = str(uuid4())
    test.key = f"datasets/{test.dataset_id}/train.jsonl"
    path = test.data / test.key
    path.parent.mkdir(parents=True)
    path.write_bytes(RAW)
    with test.sessions.begin() as session:
        session.add(Dataset(id=test.dataset_id, name="test", original_filename="train.jsonl",
            storage_path=test.key, sha256=hashlib.sha256(RAW).hexdigest(), size_bytes=len(RAW),
            row_count=1, created_at=utcnow()))


def create_task(test, *, key=None, config=None, runtime=None):
    return test.repo.create(TaskCreate(dataset_id=test.dataset_id, config=config or {}),
        model_revision=DEFAULT_MODEL_REVISION, runtime=runtime or RuntimeOptions(), idempotency_key=key)


def progress(step=1, total=2, kind="train"):
    return TrainingProgress(step=step, total_steps=total, kind=kind, loss=1.0,
                            learning_rate=0.0002, epoch=0.5, recorded_at=utcnow())


def summary(total=2):
    return TrainingSummary(completed_steps=total, total_steps=total, elapsed_seconds=1.0,
        peak_memory_allocated_bytes=0, trainable_parameters=4, total_parameters=104, final_loss=1.0)
