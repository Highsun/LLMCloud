"""Controlled fault Worker for M3-07 only; production entrypoints stay unchanged."""

import argparse
from pathlib import Path
import sys
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def install_fault(task_id, mode):
    """Inject at a real publication/SQL commit boundary after real GPU training."""
    if mode == "saving":
        from trainer import run_storage
        original = run_storage.publish_manifest
        def publish(root, manifest):
            if str(manifest.task_id) == task_id:
                print(f"acceptance_fault=saving task_id={task_id}", flush=True)
                raise OSError("Controlled M3-07 manifest publication failure")
            return original(root, manifest)
        run_storage.publish_manifest = publish
        return
    from sqlalchemy import event
    from sqlalchemy.exc import OperationalError
    from backend.app.services.task_repository import SqlTaskRepository
    original = SqlTaskRepository.complete
    def complete(repository, current, *args):
        if str(current) != task_id:
            return original(repository, current, *args)
        def failure(_session):
            print(f"acceptance_fault={mode} task_id={task_id}", flush=True)
            raise OperationalError("Controlled M3-07 commit boundary failure", {}, Exception())
        event.listen(repository.sessions.class_, mode, failure)
        try:
            return original(repository, current, *args)
        finally:
            event.remove(repository.sessions.class_, mode, failure)
    SqlTaskRepository.complete = complete


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", type=UUID, required=True)
    parser.add_argument("--fault", choices=("before_commit", "after_commit", "saving"), required=True)
    args = parser.parse_args()
    if args.task_id.version != 4:
        parser.error("Expected UUIDv4")
    install_fault(str(args.task_id), args.fault)
    from worker.__main__ import main as start
    return start()


if __name__ == "__main__":
    main()
