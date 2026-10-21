"""CPU-only record contract and limits shared by upload and training readers."""

from pydantic import BaseModel, ConfigDict, field_validator

MAX_DATASET_BYTES = 50 * 1024 * 1024
MAX_JSONL_LINE_BYTES = 1024 * 1024


class InstructionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    instruction: str
    input: str = ""
    output: str

    @field_validator("instruction", "output")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("必须是非空白字符串")
        # Check whitespace without rewriting training text.
        return value
