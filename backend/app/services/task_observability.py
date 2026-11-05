"""Read-only SQL identity plus bounded task-local metrics and safe log tails."""

from collections import OrderedDict
import hashlib
import threading

from pydantic import ValidationError

from backend.app.core.observability_contract import (
    MAX_LOG_READ_BYTES, MAX_METRIC_LINE_BYTES, MAX_METRICS_RESPONSE_BYTES,
    MAX_METRICS_SCAN_BYTES, MAX_OBSERVED_LOG_TASKS, MAX_SAFE_INTEGER, OBSERVABILITY_ERROR_STATUS,
)
from backend.app.core.task_contract import TaskStatus
from backend.app.core.task_protocols import TaskStoreError
from backend.app.models.error_schemas import ApiErrorCode
from backend.app.models.observability_schemas import LogsPage, MetricRecord, MetricsPage
from backend.app.services.errors import DatasetServiceError
from backend.app.services.task_files import open_task_file, TaskFileChanged, TaskFileMissing
from backend.app.services.task_log_projection import load_json, project_log
from backend.app.services.tasks import database_error
from trainer.contracts import TrainingProgress


def failure(code):
    code = ApiErrorCode(code)
    message = {
        "METRICS_CURSOR_INVALID": "指标来源或读取位置已变化，请重置游标。",
        "METRICS_CORRUPTED": "任务指标内容不完整或格式损坏。",
        "METRICS_UNAVAILABLE": "任务指标文件不可安全读取。",
        "LOGS_UNAVAILABLE": "任务日志文件不可安全读取。",
    }[code]
    return DatasetServiceError(code, message, OBSERVABILITY_ERROR_STATUS[code])


def _metric(raw):
    if len(raw) + 1 > MAX_METRIC_LINE_BYTES:
        raise failure("METRICS_CORRUPTED")
    try:
        return TrainingProgress.model_validate(load_json(raw))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise failure("METRICS_CORRUPTED") from None


def _ordered(previous, event):
    if previous is not None and (event.total_steps != previous.total_steps or
            (event.step, event.kind == "eval") <= (previous.step, previous.kind == "eval")):
        raise failure("METRICS_CORRUPTED")


class TaskObservabilityService:
    def __init__(self, settings, repository):
        self.settings, self.repository = settings, repository
        # Logs have no client cursor. Remember observed files within a bounded
        # process-local LRU; SQL progress remains the durable evidence of output.
        self._seen_logs = OrderedDict()
        self._seen_lock = threading.Lock()

    def _seen(self, task_id, *, mark=False):
        with self._seen_lock:
            if mark:
                self._seen_logs[task_id] = None
                self._seen_logs.move_to_end(task_id)
                while len(self._seen_logs) > MAX_OBSERVED_LOG_TASKS:
                    self._seen_logs.popitem(last=False)
            return task_id in self._seen_logs

    def _task(self, task_id):
        try:
            task = self.repository.get_detail(task_id)
        except TaskStoreError:
            raise database_error() from None
        if task is None:
            raise DatasetServiceError(ApiErrorCode.TASK_NOT_FOUND, "训练任务不存在。", 404)
        return task

    def metrics(self, task_id, query):
        task = self._task(task_id)  # release the short SQL read before file access
        try:
            with open_task_file(self.settings.data_dir, ("outputs", str(task.id), "metrics.jsonl")) as source:
                page = self._metrics(source, task, query)
            return page
        except TaskFileMissing:
            if query.source_id is not None or query.cursor:
                raise failure("METRICS_CURSOR_INVALID") from None
            if task.status != TaskStatus.COMPLETED and task.current_step == 0:
                return MetricsPage(task_id=task.id, task_status=task.status, source_state="not_created",
                    source_id=None, items=[], next_cursor=0, has_more=False, tail_incomplete=False)
            raise failure("METRICS_UNAVAILABLE") from None
        except TaskFileChanged:
            raise failure("METRICS_CURSOR_INVALID") from None
        except OSError:
            raise failure("METRICS_UNAVAILABLE") from None

    def _metrics(self, source, task, query):
        size, cursor = source.info.st_size, query.cursor
        identity = hashlib.sha256(f"{task.id}:{source.info.st_dev}:{source.info.st_ino}".encode()).hexdigest()
        if (size > MAX_SAFE_INTEGER or cursor > size
                or (query.source_id is not None and query.source_id != identity)):
            raise failure("METRICS_CURSOR_INVALID")
        completed = task.status == TaskStatus.COMPLETED
        partial = bool(size and source.read(1, size - 1) != b"\n")
        if completed and (not size or partial):
            raise failure("METRICS_CORRUPTED")
        previous, spent = None, int(bool(size))
        if cursor:
            count = min(cursor, MAX_METRIC_LINE_BYTES + 1)
            prior = source.read(count, cursor - count)
            spent += count
            if not prior.endswith(b"\n"):
                raise failure("METRICS_CURSOR_INVALID")
            # Inspect only the immediate predecessor, never rescan history.
            start = prior.rfind(b"\n", 0, len(prior) - 1) + 1
            if cursor > count and start == 0:
                raise failure("METRICS_CORRUPTED")
            previous = _metric(prior[start:-1])
        amount = min(size - cursor, MAX_METRICS_SCAN_BYTES - spent)
        raw = source.read(amount, cursor)
        reaches_eof = cursor + amount == size
        end = raw.rfind(b"\n") + 1
        if not end and len(raw) >= MAX_METRIC_LINE_BYTES:
            raise failure("METRICS_CORRUPTED")
        if reaches_eof and len(raw) - end >= MAX_METRIC_LINE_BYTES:
            raise failure("METRICS_CORRUPTED")
        lines = [line + b"\n" for line in raw[:end].split(b"\n")[:-1]] if end else []
        items, next_cursor, more = [], cursor, False
        for index, line in enumerate(lines):
            event = _metric(line[:-1])
            _ordered(previous, event)
            # Keep the last available complete line as lookahead when the byte
            # budget, rather than EOF, ended the scan. has_more is then proven.
            if len(items) == query.limit or (not reaches_eof and index == len(lines) - 1):
                more = True
                break
            record = MetricRecord(**event.model_dump(), offset=next_cursor)
            items.append(record)
            next_cursor += len(line)
            previous = event
        page = MetricsPage(task_id=task.id, task_status=task.status, source_state="ready",
            source_id=identity, items=items, next_cursor=next_cursor, has_more=more, tail_incomplete=partial)
        if len(page.model_dump_json().encode("utf-8")) > MAX_METRICS_RESPONSE_BYTES:
            raise failure("METRICS_CORRUPTED")
        return page

    def logs(self, task_id, query):
        task = self._task(task_id)
        try:
            with open_task_file(self.settings.log_dir, ("tasks", f"{task.id}.log")) as source:
                self._seen(task.id, mark=True)
                size = source.info.st_size
                start = max(0, size - MAX_LOG_READ_BYTES)
                raw = source.read(size - start, start)
                partial = bool(size and not raw.endswith(b"\n"))
                truncated = start > 0
                if start:
                    # The window may start mid UTF-8 codepoint/record. Always
                    # discard its first fragment; no unbounded lookbehind.
                    boundary = raw.find(b"\n")
                    raw = raw[boundary + 1:] if boundary >= 0 else b""
                end = raw.rfind(b"\n") + 1
                complete = raw[:end].split(b"\n")[:-1]
                truncated = truncated or len(complete) > query.tail
                lines, filtered = [], 0
                for line in complete[-query.tail:]:
                    projected, altered = project_log(line, task.id)
                    filtered += int(altered)
                    if projected is not None:
                        lines.append(projected)
                return LogsPage(task_id=task.id, task_status=task.status, source_state="ready",
                    lines=lines, truncated=truncated, tail_incomplete=partial, filtered_lines=filtered)
        except TaskFileMissing:
            if task.status != TaskStatus.COMPLETED and task.current_step == 0 and not self._seen(task.id):
                return LogsPage(task_id=task.id, task_status=task.status, source_state="not_created",
                    lines=[], truncated=False, tail_incomplete=False, filtered_lines=0)
            raise failure("LOGS_UNAVAILABLE") from None
        except (OSError, ValidationError):
            raise failure("LOGS_UNAVAILABLE") from None
