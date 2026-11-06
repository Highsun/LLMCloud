"""CPU-only evidence checks for M4; never manufacture training or human evidence."""

from datetime import datetime
import json
from pathlib import Path
import shutil
import stat
from uuid import UUID
import zipfile

from trainer.artifacts import sha256, verify_training_artifacts

MAX_BYTES = 256 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def new_run_directory(parent, requested=None):
    """Only a new direct UUID child of the ignored evidence root is writable."""
    from uuid import uuid4

    parent = Path(parent).absolute()
    require(parent.resolve() == parent, "Evidence root must not contain symlinks")
    target = Path(requested).absolute() if requested else parent / str(uuid4())
    require(target.parent == parent, "Run directory must be a direct child of data/acceptance/m4-07")
    require(str(UUID(target.name)) == target.name, "Run directory name must be a canonical UUID")
    parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o700, exist_ok=False)
    return target


def check_serial(tasks):
    require(len(tasks) == 2 and len({task['id'] for task in tasks}) == 2, "Two distinct tasks required")
    require(all(task['status'] == 'COMPLETED' for task in tasks), "Both tasks must complete")
    times = []
    for task in tasks:
        start, end = (datetime.fromisoformat(task[key].replace('Z', '+00:00'))
                      for key in ('started_at', 'finished_at'))
        require(start.utcoffset() is not None and end.utcoffset() is not None and start <= end,
                "Invalid timezone-aware task interval")
        times.append((start, end))
    require(times[1][0] >= times[0][1], "Task execution intervals overlap")
    return {"task_ids": [task['id'] for task in tasks], "sql_intervals_do_not_overlap": True}


def audit_gpu_output(output, task, completed, *, revision, steps, commit):
    audited = verify_training_artifacts(output, outputs_root=output.parent,
        expected_task_id=task['id'], expected_revision=revision)
    manifest = audited.manifest
    require(task['status'] == 'COMPLETED', "SQL must be COMPLETED before publication")
    require(manifest.environment.code_commit == commit and not manifest.environment.working_tree_dirty,
            "Training used a different or dirty code baseline")
    require(manifest.summary.peak_memory_allocated_bytes > 0 and bool(manifest.environment.cuda_runtime),
            "No actual GPU allocation recorded")
    sql_start = datetime.fromisoformat(task['started_at'].replace('Z', '+00:00'))
    sql_end = datetime.fromisoformat(task['finished_at'].replace('Z', '+00:00'))
    require(sql_start <= manifest.started_at <= manifest.finished_at <= sql_end,
            "SQL completion must follow the saved manifest/audit interval")
    require(manifest.runtime.max_steps == steps and manifest.summary.completed_steps == steps,
            "Internal optimizer step limit differs")
    require(manifest.config.logging_steps == 1, "Each actual optimizer step must be observable")
    raw_metrics = [json.loads(line) for line in (output / 'metrics.jsonl').read_text().splitlines()]
    train = [item for item in raw_metrics if item['kind'] == 'train']
    require(len(train) >= 5, "At least five real train points required")
    require(completed.training_summary == manifest.summary and
            completed.manifest_sha256 == sha256(output / 'manifest.json'), "SQL summary or manifest hash differs")
    require(manifest.config == completed.spec.config and manifest.runtime == completed.spec.runtime and
            manifest.train_dataset.sha256 == completed.spec.dataset_sha256 and
            manifest.train_dataset.size_bytes == completed.spec.dataset_size_bytes and
            manifest.train_dataset.row_count == completed.spec.dataset_row_count, "SQL execution snapshot differs")
    return {**audited.summary(), "manifest_sha256": sha256(output / 'manifest.json'),
            "summary": manifest.summary.model_dump(mode='json'),
            "environment": manifest.environment.model_dump(mode='json'),
            "train_points": len(train), "last_train": train[-1]}


def audit_download(archive, original, destination):
    """Bounded extraction with exact source inventory, then the original shared audit."""
    original, destination = Path(original), Path(destination)
    verified = verify_training_artifacts(original, outputs_root=original.parent,
                                         expected_task_id=original.name)
    expected = {f'{original.name}/{item.path}': (item.size_bytes, item.sha256)
                for item in verified.manifest.artifacts}
    raw = original / 'manifest.json'
    expected[f'{original.name}/manifest.json'] = (raw.stat().st_size, sha256(raw))
    require(sum(size for size, _ in expected.values()) <= MAX_BYTES, "Source exceeds download bound")
    require(Path(archive).stat().st_size <= MAX_BYTES + 1024 * 1024, "ZIP exceeds download bound")
    # Never reuse a partially extracted or previously audited destination.
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            require(len(members) == len(expected) and {entry.filename for entry in members} == set(expected),
                    "ZIP inventory differs, is duplicated, or contains unsafe paths")
            for entry in members:
                size, digest = expected[entry.filename]
                mode = entry.external_attr >> 16
                require(not entry.is_dir() and not stat.S_ISLNK(mode) and not entry.flag_bits & 1,
                        "ZIP contains a linked, encrypted or directory entry")
                require(entry.file_size == size, "ZIP declared size differs")
                target = destination / entry.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open('xb') as sink:
                    remaining = size
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        require(bool(chunk), "Truncated ZIP member")
                        sink.write(chunk)
                        remaining -= len(chunk)
                    require(source.read(1) == b'', "ZIP member exceeds bound")
                require(sha256(target) == digest, "Downloaded bytes differ from original")
        extracted = verify_training_artifacts(destination / original.name, outputs_root=destination,
                                              expected_task_id=original.name)
        require(extracted.manifest == verified.manifest, "Downloaded manifest differs")
        return {"zip_sha256": sha256(archive), "zip_size_bytes": Path(archive).stat().st_size,
                "source_manifest_sha256": sha256(raw), "extracted": extracted.summary(),
                "exact_source_bytes": True}
    except BaseException:
        shutil.rmtree(destination)
        raise
