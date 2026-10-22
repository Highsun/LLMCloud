"""GPU training boundary. Actual Hugging Face training follows in milestone M2."""

import argparse
from collections.abc import Callable

# Retain the original import locations; execution remains owned by M2-04.
from trainer.contracts import TrainRequest, TrainResult, TrainingProgress


def train(
    request: TrainRequest,
    on_progress: Callable[[TrainingProgress], None] | None = None,
) -> TrainResult:
    """Save an adapter and report metrics; not implemented in initialization."""
    raise NotImplementedError("真实 LoRA 训练将在 M2 实现；当前仅定义训练模块接口。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLMCloud 训练入口（初始化占位）")
    parser.parse_args()
    parser.exit(2, "训练功能尚未实现，请参阅 docs/requirements.md 的 M2。\n")
