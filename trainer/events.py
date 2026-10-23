"""CPU-only ordered metric writer; the callback observes already-flushed events."""

from datetime import datetime, timezone

from pydantic import ValidationError

from trainer.contracts import TrainingError, TrainingFailure, TrainingProgress


def fail(code, stage, message, *, cause=None):
    raise TrainingError(TrainingFailure(code=code, stage=stage, message=message)) from cause


class MetricWriter:
    def __init__(self, stream, on_progress=None):
        self.stream, self.on_progress = stream, on_progress
        self.total_steps = None
        self.last = {}
        self.last_step = 0

    def emit(self, *, kind, step, total_steps, loss, learning_rate, epoch):
        try:
            event = TrainingProgress(kind=kind, step=step, total_steps=total_steps, loss=loss,
                                     learning_rate=learning_rate, epoch=epoch,
                                     recorded_at=datetime.now(timezone.utc))
            previous = self.last.get(kind)
            if ((self.total_steps is not None and total_steps != self.total_steps)
                    or step < self.last_step or (previous is not None and step <= previous.step)):
                raise ValueError("Non-monotonic metrics")
        except (ValueError, ValidationError) as error:
            fail("TRAINING_FAILED", "training", "训练指标非有限、越界或顺序不一致。", cause=error)
        try:
            self.stream.write(event.model_dump_json() + "\n")
            self.stream.flush()
        except (OSError, ValueError) as error:
            fail("ARTIFACT_WRITE_FAILED", "training", "无法写入或 flush 训练指标。", cause=error)
        self.last[kind], self.total_steps, self.last_step = event, total_steps, step
        if self.on_progress is not None:
            try:
                self.on_progress(event)
            except Exception as error:
                fail("PROGRESS_CALLBACK_FAILED", "callback", "训练进度回调失败。", cause=error)
        return event
