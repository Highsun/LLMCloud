"""Validated configuration shared with API contracts; no CUDA imports."""

from pydantic import BaseModel, ConfigDict, Field


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    lora_r: int = Field(default=8, ge=1, le=64)
    lora_alpha: int = Field(default=16, ge=1, le=128)
    lora_dropout: float = Field(default=0.05, ge=0, lt=1)
    target_modules: list[str] = Field(default_factory=lambda: ["q_proj", "v_proj"], min_length=1)
    learning_rate: float = Field(default=2e-4, gt=0, le=1e-2)
    num_train_epochs: int = Field(default=1, ge=1, le=10)
    per_device_train_batch_size: int = Field(default=1, ge=1, le=4)
    gradient_accumulation_steps: int = Field(default=8, ge=1, le=64)
    max_seq_length: int = Field(default=512, ge=64, le=2048)
    logging_steps: int = Field(default=1, ge=1, le=100)
    seed: int = Field(default=42, ge=0)
